"""Update the merged screenings, as Schema.org actions over one data directory.

A run is an UpdateAction: its `object` lists the registry DataFeeds run and its
`targetCollection` the previous result. It fans out to a DownloadAction (fetch) and
CreateAction (parse) per adapter. A DownloadAction captures TMDB answers for films missing
critical details, then one CreateAction (merge) builds the result from the previous result,
the parsed Datasets and that capture. Each step's `object` links its inputs and `result` the
Dataset it produced; the run's result is the merge's.
"""

import argparse
import os
import sys
import tempfile
import traceback
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, date, datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from allabiografer import session as _http

from . import enrich as tmdb
from .code import source_code
from .graph import DATA, Graph, media_type
from .merge import build, combine
from .parsing import parse_capture, site
from .prune import prune
from .render import render as render_site
from .schedule import Feed, checked, feeds
from .site.pages import BASE_URL as SITE
from .sources._shared import STOCKHOLM
from .store import BucketStore, LocalStore

if TYPE_CHECKING:
    from collections.abc import Iterator


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class Recorder:
    """A requests-compatible session that remembers where each capture came from."""

    def __init__(self, session):
        self.session = session
        self.headers = session.headers
        self.origins: dict[str, tuple[str, str]] = {}

    def note(self, name: str, url: str, content_type: str) -> None:
        self.origins[name] = (url, content_type)

    def get(self, url, **kwargs):
        return self.session.get(url, **kwargs)

    def post(self, url, **kwargs):
        return self.session.post(url, **kwargs)


@contextmanager
def action(graph: Graph, kind: str, fields: dict) -> Iterator[dict]:
    """Record an action and its outcome; the caller fills `result`."""
    run = str(uuid.uuid4())
    record = {"startTime": timestamp(), **fields}
    graph.save(kind, run, record | {"actionStatus": "https://schema.org/ActiveActionStatus"})
    outcome: dict = {}
    try:
        yield outcome
    except BaseException as error:
        failure = {
            "@type": "Thing",
            "name": type(error).__name__,
            "description": "".join(traceback.format_exception_only(error)).strip(),
        }
        graph.save(
            kind,
            run,
            record
            | {"endTime": timestamp(), "actionStatus": "https://schema.org/FailedActionStatus", "error": failure},
        )
        raise
    graph.save(
        kind,
        run,
        record | {"endTime": timestamp(), "actionStatus": "https://schema.org/CompletedActionStatus"} | outcome,
    )


def instrument(graph: Graph, path: str) -> dict:
    """The module a step runs, as part of the snapshot of all pipeline code."""
    return graph.ref(graph.put("SoftwareSourceCode", {"name": path, "isPartOf": graph.ref(source_code(graph))}))


def fetch(graph: Graph, adapter: str, selected: list[Feed], day: date) -> Path:
    """Capture one adapter's selected feeds into a Dataset of DataDownloads."""
    module = import_module(f".sources.{adapter}.fetch", __package__)
    about = [graph.ref(graph.path("DataFeed", feed.name)) for feed in selected]
    selectors = {feed.venue_id for feed in selected}
    fields = {
        "name": f"Download {site(adapter)}",
        "instrument": instrument(graph, f"src/allabiografer/sources/{adapter}/fetch.py"),
    }
    with (
        action(graph, "DownloadAction", fields) as outcome,
        tempfile.TemporaryDirectory() as scratch,
        _http.session() as session,
    ):
        inputs = Path(scratch)
        recorder = Recorder(session)
        module.fetch_pages(recorder, inputs, day, selectors=selectors)
        downloads = []
        for path in sorted(item for item in inputs.iterdir() if item.is_file()):
            url, content_type = recorder.origins.get(path.name, ("", ""))
            downloads.append(
                graph.put_bytes(path.read_bytes(), media_type(path.name, content_type), name=path.name, url=url)
            )
        dataset = graph.put(
            "Dataset",
            {
                "name": f"{site(adapter)} pages",
                "temporalCoverage": day.isoformat(),
                "about": about,
                "distribution": [graph.ref(path) for path in downloads],
            },
        )
        outcome["result"] = graph.ref(dataset)
    return dataset


def parse(graph: Graph, adapter: str, captured: Path) -> Path:
    fields = {
        "name": f"Read {site(adapter)}",
        "object": graph.ref(captured),
        "instrument": instrument(graph, f"src/allabiografer/sources/{adapter}/parse.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        dataset = parse_capture(graph, adapter, captured)
        outcome["result"] = graph.ref(dataset)
    return dataset


def inputs(graph: Graph, previous: Path | None, parsed: list[Path]) -> list[dict]:
    return [graph.ref(path) for path in ([previous] if previous else []) + parsed]


def fetch_tmdb(graph: Graph, previous: Path | None, parsed: list[Path], day: date) -> Path:
    """Capture the TMDB answers and source posters that films missing critical details need."""
    fields = {
        "name": "Look up films on TMDB",
        "object": inputs(graph, previous, parsed),
        "instrument": instrument(graph, "src/allabiografer/enrich.py"),
    }
    with action(graph, "DownloadAction", fields) as outcome, _http.session() as session:
        combined = combine(graph, previous, parsed, day)
        answers = tmdb.recording(graph, session)
        tmdb.enrich_parts(graph, combined.films + combined.screenings, day, answers)
        capture = graph.put(
            "Dataset",
            {
                "name": "TMDB answers",
                "temporalCoverage": day.isoformat(),
                "distribution": [graph.ref(path) for path in dict.fromkeys(answers.used)],
            },
        )
        outcome["result"] = graph.ref(capture)
    return capture


def merge(
    graph: Graph, previous: Path | None, parsed: list[Path], day: date, capture: Path | None
) -> tuple[Path, dict[str, str]]:
    fields = {
        "name": "Build programme",
        "object": inputs(graph, previous, parsed) + ([graph.ref(capture)] if capture else []),
        "instrument": instrument(graph, "src/allabiografer/merge.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        dataset, warnings = build(graph, previous, parsed, day, capture)
        outcome["result"] = graph.ref(dataset)
    return dataset, warnings


def published(graph: Graph) -> Path | None:
    """The pages of the newest completed render: every address the site has published.

    A render's result is the Dataset of the site's `WebPage`s; other steps' results hold none.
    """
    renders = []
    for path in graph.entities("CreateAction"):
        record = graph.read(path)
        if record.get("actionStatus") != COMPLETED or "@id" not in record.get("result", {}):
            continue
        result = graph.resolve(path, record["result"])
        if graph.read(result).get("url") == SITE:
            renders.append((record["endTime"], result))
    return max(renders)[1] if renders else None


def render(graph: Graph, merged: Path) -> Path:
    """Write the static site for `merged` to <data>/www, replacing the previous one.

    Its result lists every page published, by this render and every one before.
    """
    out = graph.root / "www"
    previous = published(graph)
    fields = {
        "name": "Render allabiografer.se",
        "object": [graph.ref(merged)] + ([graph.ref(previous)] if previous else []),
        "instrument": instrument(graph, "src/allabiografer/render.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        outcome["result"] = graph.ref(render_site(graph, merged, out, previous=previous))
    return out


def open_store(data: Path, *, production: bool = False):
    """The data directory; with `production`, the R2 bucket, caching objects under <data>/.cache.

    Credentials alone never select production: a run there becomes the programme the site and
    the next run build on. `nix run .#pull` copies production into the data directory.
    """
    if not production:
        return LocalStore(data)
    return BucketStore.from_environment(cache=data / ".cache")


COMPLETED = "https://schema.org/CompletedActionStatus"


def latest(graph: Graph) -> Path | None:
    """The result of the most recent completed run."""
    runs = []
    for path in graph.entities("UpdateAction"):
        record = graph.read(path)
        if record.get("actionStatus") == "https://schema.org/CompletedActionStatus" and "result" in record:
            runs.append((record["endTime"], graph.resolve(path, record["result"])))
    return max(runs)[1] if runs else None


def run(graph: Graph, selected: list[Feed], *, previous: Path | None) -> tuple[Path, dict[str, str]]:
    """Fan out into download and read per site; fan in to one build with the previous Programme.

    Returns the Programme and the problems to report, by site or feed. A failing site is
    recorded as a failed action; its feeds keep their previous screenings, as do feeds read
    empty. Without TMDB, films keep the answers that decided them before.
    """
    day = datetime.now(STOCKHOLM).date()
    by_adapter = defaultdict(list)
    for feed in selected:
        by_adapter[feed.adapter].append(feed)
    fields = {
        "name": "Update programme",
        "object": [graph.ref(graph.path("DataFeed", feed.name)) for feed in selected],
        **({"targetCollection": graph.ref(previous)} if previous else {}),
        "instrument": instrument(graph, "src/allabiografer/pipeline.py"),
    }
    with action(graph, "UpdateAction", fields) as outcome:
        parsed = []
        failures = {}
        for adapter, group in sorted(by_adapter.items()):
            try:
                parsed.append(parse(graph, adapter, fetch(graph, adapter, group, day)))
            except Exception as error:
                failures[adapter] = "".join(traceback.format_exception_only(error)).strip()
                print(f"{adapter}: {failures[adapter]}", file=sys.stderr)
        if not parsed and previous is None:
            raise RuntimeError("Every adapter failed")
        capture = None
        try:
            capture = fetch_tmdb(graph, previous, parsed, day)
        except Exception as error:
            # Films stay as their sources state them.
            failures["tmdb"] = "".join(traceback.format_exception_only(error)).strip()
            print(f"tmdb: {failures['tmdb']}", file=sys.stderr)
        result, warnings = merge(graph, previous, parsed, day, capture)
        failures |= warnings
        for name, warning in sorted(warnings.items()):
            print(f"{name}: {warning}", file=sys.stderr)
        outcome["result"] = graph.ref(result)
    return result, failures


def report(failures: dict[str, str]) -> None:
    """Write problems to $PROBLEMS when set: CI files them as an issue."""
    if target := os.environ.get("PROBLEMS"):
        lines = [f"- **{name}**: {problem.splitlines()[0]}" for name, problem in sorted(failures.items())]
        Path(target).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--cinema", action="append", default=[], help="Limit to this cinema's feeds (MovieTheater filename stem)"
    )
    cli.add_argument("--fresh", action="store_true", help="Ignore the previous run's result")
    cli.add_argument("--render-only", action="store_true", help="Render the latest result without fetching")
    cli.add_argument("--keep", type=int, help="At most this many completed runs kept; default: as many as fit")
    cli.add_argument("--data", type=Path, default=DATA, help="Registry, site output and local store")
    cli.add_argument("--production", action="store_true", help="Use the production R2 store")
    args = cli.parse_args()
    graph = Graph(args.data.resolve(), open_store(args.data.resolve(), production=args.production))
    if args.render_only:
        if (previous := latest(graph)) is None:
            cli.error("no completed run to render")
        print(render(graph, previous))
        return
    try:
        available = list(feeds(graph.root).values())
        checked(set(args.cinema), {feed.cinema for feed in available})
    except ValueError as error:
        cli.error(str(error))
    selected = [feed for feed in available if not args.cinema or feed.cinema in args.cinema]
    result, failures = run(graph, selected, previous=None if args.fresh else latest(graph))
    print(result)
    print(render(graph, result))
    if failures:
        # Earlier runs stay until a clean one: they hold what a fixed source should be compared with.
        print("Not pruning: the run had problems", file=sys.stderr)
    else:
        entities, assets = prune(graph, args.keep)
        print(f"Pruned {entities} entities and {assets} assets")
    if failures:
        report(failures)
        sys.exit(f"{len(failures)} problem(s): {', '.join(sorted(failures))}")


if __name__ == "__main__":
    main()
