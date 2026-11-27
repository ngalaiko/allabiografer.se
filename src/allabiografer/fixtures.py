"""Adapter fixtures: a site's downloaded pages and what its reader makes of them.

A fixture is `tests/allabiografer/fixtures/sources/<adapter>/`:

- `pages.tar.zst`: the files of one download, images replaced by empty placeholders
  (readers only check that an image was downloaded);
- `rows.json.zst`: the capture day and every row the adapter's `rows` yields, as JSON.

`allabiografer-fixture save <adapter>` takes the newest download of `<adapter>` in the store;
`allabiografer-fixture update <adapter>` rewrites the rows from the saved pages after an
intended reader change; `allabiografer-fixture diff <adapter>` shows how the reader's rows
differ from the saved ones.
"""

import argparse
import difflib
import io
import json
import sys
import tarfile
import tempfile
from compression import zstd
from datetime import date
from importlib import import_module
from pathlib import Path

from .graph import DATA, Graph
from .movie_fields import normalise
from .parsing import screening_fields
from .schedule import PREFIX

ROOT = Path(__file__).resolve().parents[2] / "tests" / "allabiografer" / "fixtures" / "sources"


def snapshot(adapter: str, inputs: Path, today: date) -> list[dict]:
    """The rows `adapter` reads from `inputs`, as JSON, in a stable order."""
    rows = import_module(f"allabiografer.sources.{adapter}.parse").rows
    found = []
    for venue, show_id, start, ticket, version, presentation, movie_id, capture, movie, listing in rows(inputs, today):
        found.append(
            {
                "venue": list(venue),
                "show": show_id,
                "start": start.isoformat(),
                "ticket": ticket,
                "screening": screening_fields(version, presentation)
                | {"audio": str(version.audio.kind), **({"edition": version.edition} if version.edition else {})},
                "movie": movie_id,
                "capture": capture,
                "fields": normalise(movie),
                "listing": [listing] if isinstance(listing, str) else list(listing),
            }
        )
    return sorted(found, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))


def _pack(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    return zstd.compress(buffer.getvalue(), 19)


def _extract(adapter: str, target: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(zstd.decompress((ROOT / adapter / "pages.tar.zst").read_bytes()))) as tar:
        tar.extractall(target, filter="data")


def unpack(adapter: str, target: Path) -> date:
    """Write a fixture's pages into `target`; return its capture day."""
    _extract(adapter, target)
    return date.fromisoformat(saved(adapter)["day"])


def saved(adapter: str) -> dict:
    return json.loads(zstd.decompress((ROOT / adapter / "rows.json.zst").read_bytes()))


def _write_rows(adapter: str, day: date, rows: list[dict]) -> None:
    document = {"day": day.isoformat(), "rows": rows}
    data = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True).encode()
    (ROOT / adapter / "rows.json.zst").write_bytes(zstd.compress(data, 19))


def _newest_pages(graph: Graph, adapter: str) -> Path:
    """The newest download whose feeds are `adapter`'s."""
    downloads = []
    for path in graph.entities("DownloadAction"):
        action = graph.read(path)
        if "result" not in action:
            continue
        pages = graph.resolve(path, action["result"])
        feeds = graph.read(pages).get("about") or []
        # Older downloads may name feeds since renamed or removed from the registry.
        feeds = [graph.resolve(pages, feed) for feed in (feeds if isinstance(feeds, list) else [feeds])]
        identifiers = [graph.read(feed).get("identifier", {}) for feed in feeds if graph.exists(feed)]
        if identifiers and identifiers[0].get("propertyID") == PREFIX + adapter:
            downloads.append((action["endTime"], pages))
    if not downloads:
        raise SystemExit(f"No download of {adapter} in the store; run it or `nix run .#pull` first")
    return max(downloads)[1]


def save(graph: Graph, adapter: str) -> None:
    """Save the newest download of `adapter` in the store, and its rows."""
    pages = _newest_pages(graph, adapter)
    capture = graph.read(pages)
    files = {}
    for reference in capture["distribution"]:
        entity = graph.read(graph.resolve(pages, reference))
        image = entity["@type"] == "ImageObject"
        files[entity["name"]] = b"" if image else graph.content(entity)
    (ROOT / adapter).mkdir(parents=True, exist_ok=True)
    (ROOT / adapter / "pages.tar.zst").write_bytes(_pack(files))
    _rewrite(adapter, date.fromisoformat(capture["temporalCoverage"]))


def update(adapter: str) -> None:
    """Rewrite a fixture's rows from its pages with the current reader."""
    _rewrite(adapter, date.fromisoformat(saved(adapter)["day"]))


def _rewrite(adapter: str, day: date) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        _extract(adapter, Path(scratch))
        _write_rows(adapter, day, snapshot(adapter, Path(scratch), day))


def diff(adapter: str) -> list[str]:
    """How the current reader's rows differ from the saved ones, as a unified diff."""
    with tempfile.TemporaryDirectory() as scratch:
        day = unpack(adapter, Path(scratch))
        current = snapshot(adapter, Path(scratch), day)
    before = json.dumps(saved(adapter)["rows"], ensure_ascii=False, indent=1, sort_keys=True).splitlines()
    after = json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True).splitlines()
    return list(difflib.unified_diff(before, after, "saved", "reader", lineterm=""))


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("command", choices=("save", "update", "diff"))
    cli.add_argument("adapter", nargs="+", help="Adapter package names, e.g. filmstaden_se")
    cli.add_argument("--data", type=Path, default=DATA, help="Local store to save from")
    args = cli.parse_args()
    changed = False
    for adapter in args.adapter:
        if args.command == "save":
            save(Graph(args.data.resolve()), adapter)
        elif args.command == "update":
            update(adapter)
        else:
            lines = diff(adapter)
            changed |= bool(lines)
            print("\n".join(lines) or f"{adapter}: no change")
    sys.exit(1 if changed else 0)
