"""Run fetch, parse, and merge as Schema.org actions over one data directory.

Every run is a DownloadAction (fetch) or CreateAction (parse, merge) whose `object`
links its inputs and whose `result` links the Dataset it produced.
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

from parse import _http

from .code import source_code
from .graph import DATA, Graph, media_type
from .merge import merge_datasets
from .parse import parse_capture
from .schedule import PREFIX, Route, checked, routes
from .source._shared import STOCKHOLM


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


def binding(graph: Graph, route: Route) -> dict:
    return graph.ref(graph.path("MovieTheater", route.cinema)) | {
        "identifier": {"@type": "PropertyValue", "propertyID": PREFIX + route.adapter}
        | ({"value": route.venue_id} if route.venue_id is not None else {})
    }


def fetch(graph: Graph, adapter: str, selected: list[Route], day: date) -> Path:
    """Capture one adapter's programmes for the selected cinemas into a Dataset of DataDownloads."""
    module = import_module(f".source.{adapter}.fetch", __package__)
    cinemas = [binding(graph, route) for route in selected]
    selectors = {route.venue_id for route in selected}
    fields = {
        "name": f"Fetch {adapter}",
        "object": cinemas,
        "instrument": instrument(graph, f"v2/source/{adapter}/fetch.py"),
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
                "about": cinemas,
                "distribution": [graph.ref(path) for path in downloads],
            },
        )
        outcome["result"] = graph.ref(dataset)
    return dataset


def parse(graph: Graph, adapter: str, captured: Path) -> Path:
    fields = {
        "name": f"Parse {adapter}",
        "object": graph.ref(captured),
        "instrument": instrument(graph, f"v2/source/{adapter}/parse.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        dataset = parse_capture(graph, adapter, captured)
        outcome["result"] = graph.ref(dataset)
    return dataset


def merge(graph: Graph, parsed: list[Path]) -> Path:
    fields = {
        "name": "Merge",
        "object": [graph.ref(path) for path in parsed],
        "instrument": instrument(graph, "v2/merge.py"),
    }
    with action(graph, "CreateAction", fields) as outcome:
        dataset = merge_datasets(graph, parsed)
        outcome["result"] = graph.ref(dataset)
    return dataset


def run(graph: Graph, selected: list[Route]) -> tuple[Path, dict[str, str]]:
    """Fetch and parse each adapter, then merge the ones that succeeded.

    A failing adapter is recorded as a failed action and reported; it does not stop the others.
    """
    day = datetime.now(STOCKHOLM).date()
    by_adapter = defaultdict(list)
    for route in selected:
        by_adapter[route.adapter].append(route)
    parsed = []
    failures = {}
    for adapter, group in sorted(by_adapter.items()):
        try:
            parsed.append(parse(graph, adapter, fetch(graph, adapter, group, day)))
        except Exception as error:
            failures[adapter] = "".join(traceback.format_exception_only(error)).strip()
            print(f"{adapter}: {failures[adapter]}", file=sys.stderr)
    if not parsed:
        raise RuntimeError("Every adapter failed")
    return merge(graph, parsed), failures


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("cinema", nargs="*", help="Cinema ID (MovieTheater filename stem)")
    cli.add_argument("--all", action="store_true", help="Run every registered cinema")
    cli.add_argument("--data", type=Path, default=DATA)
    args = cli.parse_args()
    if args.all == bool(args.cinema):
        cli.error("provide cinema IDs or --all")
    graph = Graph(args.data.resolve())
    try:
        available = routes(graph.root)
        checked(set(args.cinema), available)
    except ValueError as error:
        cli.error(str(error))
    selected = list(available.values()) if args.all else [available[cinema] for cinema in dict.fromkeys(args.cinema)]
    result, failures = run(graph, selected)
    print(result)
    if failures:
        sys.exit(f"{len(failures)} adapter(s) failed: {', '.join(sorted(failures))}")


if __name__ == "__main__":
    main()
