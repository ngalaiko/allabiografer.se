"""Update the merged screenings, as Schema.org actions over one data directory.

A run is an UpdateAction: its `object` lists the registry DataFeeds run and its
`targetCollection` the previous result. It fans out to a DownloadAction (fetch) and
CreateAction (parse) per adapter, then fans in to one CreateAction (merge). A DownloadAction
captures TMDB answers for films missing critical details, and a CreateAction (enrich) fills
them from that capture. Each step's `object` links its inputs and `result` the Dataset it produced.
"""

import argparse
import sys
import tempfile
import traceback
import uuid
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from importlib import import_module
from pathlib import Path

from allabiografer import session as _http

from . import enrich as tmdb
from .code import source_code
from .graph import DATA, Graph, media_type
from .merge import merge_datasets
from .parsing import parse_capture
from .render import render as render_site
from .schedule import Feed, checked, feeds
from .site.pages import BASE_URL as SITE
from .sources._shared import STOCKHOLM


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
        "name": f"Fetch {adapter}",
        "object": about,
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
                "name": f"{adapter} capture",
                "temporalCoverage": day.isoformat(),
                "about": about,
                "distribution": [graph.ref(path) for path in downloads],
            },
        )
        outcome["result"] = graph.ref(dataset)
    return dataset


def parse(graph: Graph, adapter: str, captured: Path) -> Path:
    fields = {
        "name": f"Parse {adapter}",
        "object": graph.ref(captured),
        "instrument": instrument(graph, f"src/allabiografer/sources/{adapter}/parse.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        dataset = parse_capture(graph, adapter, captured)
        outcome["result"] = graph.ref(dataset)
    return dataset


def merge(graph: Graph, previous: Path | None, parsed: list[Path], day: date) -> Path:
    fields = {
        "name": "Merge",
        "object": [graph.ref(path) for path in ([previous] if previous else []) + parsed],
        "instrument": instrument(graph, "src/allabiografer/merge.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        dataset = merge_datasets(graph, previous, parsed, day)
        outcome["result"] = graph.ref(dataset)
    return dataset


def enrich(graph: Graph, merged: Path) -> Path:
    """Capture TMDB answers for films missing critical details, then fill them from the capture."""
    fields = {
        "name": "Fetch TMDB",
        "object": graph.ref(merged),
        "instrument": instrument(graph, "src/allabiografer/enrich.py"),
    }
    with action(graph, "DownloadAction", fields) as outcome, _http.session() as session:
        downloads: list[Path] = []
        # Source poster URLs are downloaded here, so the replay below decides from stored images only.
        tmdb.enrich_dataset(graph, merged, tmdb.recording(graph, session, downloads), session)
        capture = graph.put(
            "Dataset",
            {
                "name": "TMDB capture",
                "about": graph.ref(merged),
                "distribution": [graph.ref(path) for path in dict.fromkeys(downloads)],
            },
        )
        outcome["result"] = graph.ref(capture)
    fields = {
        "name": "Enrich",
        "object": [graph.ref(merged), graph.ref(capture)],
        "instrument": instrument(graph, "src/allabiografer/enrich.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        enriched, count = tmdb.enrich_dataset(graph, merged, tmdb.replaying(graph, capture))
        print(f"Enriched {count} films from TMDB")
        outcome["result"] = graph.ref(enriched)
    return enriched


def render(graph: Graph, merged: Path) -> Path:
    """Write the static site for `merged` to <data>/www, replacing the previous one."""
    out = graph.root / "www"
    fields = {
        "name": "Render",
        "object": graph.ref(merged),
        "instrument": instrument(graph, "src/allabiografer/render.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        pages = render_site(graph, merged, out)
        # The site is a directory, not an entity; record where it is and how much it holds.
        outcome["result"] = {"@type": "WebSite", "name": "allabiografer.se", "url": SITE, "size": f"{pages} pages"}
    return out


def latest(graph: Graph) -> Path | None:
    """The result of the most recent completed run."""
    runs = []
    for path in graph.schema.glob("UpdateAction/*.jsonld"):
        record = graph.read(path)
        if record.get("actionStatus") == "https://schema.org/CompletedActionStatus" and "result" in record:
            runs.append((record["endTime"], graph.resolve(path, record["result"])))
    return max(runs)[1] if runs else None


def run(graph: Graph, selected: list[Feed], *, previous: Path | None) -> tuple[Path, dict[str, str]]:
    """Fan out into fetch and parse per adapter; fan in to one merge with the previous result.

    A failing adapter is recorded as a failed action and reported; its feeds keep their
    previous screenings.
    """
    day = datetime.now(STOCKHOLM).date()
    by_adapter = defaultdict(list)
    for feed in selected:
        by_adapter[feed.adapter].append(feed)
    fields = {
        "name": "Run",
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
        result = merge(graph, previous, parsed, day)
        try:
            result = enrich(graph, result)
        except Exception as error:
            failures["tmdb"] = "".join(traceback.format_exception_only(error)).strip()
            print(f"tmdb: {failures['tmdb']}", file=sys.stderr)
        outcome["result"] = graph.ref(result)
    return result, failures


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--cinema", action="append", default=[], help="Limit to this cinema's feeds (MovieTheater filename stem)"
    )
    cli.add_argument("--fresh", action="store_true", help="Ignore the previous run's result")
    cli.add_argument("--render-only", action="store_true", help="Render the latest result without fetching")
    cli.add_argument("--data", type=Path, default=DATA)
    args = cli.parse_args()
    graph = Graph(args.data.resolve())
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
        sys.exit(f"{len(failures)} adapter(s) failed: {', '.join(sorted(failures))}")


if __name__ == "__main__":
    main()
