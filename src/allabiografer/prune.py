"""Delete what recent runs no longer reach.

Kept: the registry; whole completed runs, newest first, while they fit the storage budget,
each with every action recorded during it, the newest render of its result, and everything
those reach by links, part links and stored MediaObjects (including images downloaded or
resized from a kept image or URL); and anything a run still going wrote.
"""

import json
from pathlib import Path
from urllib.parse import unquote

from .graph import Graph
from .store import registry

COMPLETED = "https://schema.org/CompletedActionStatus"
ACTIVE = "https://schema.org/ActiveActionStatus"
# R2's free tier stores 10 GB; the rest is headroom for a run in progress.
BUDGET = 9 * 10**9


def _links(value, found: list[str], strings: set[str]) -> None:
    if isinstance(value, dict):
        if isinstance(iri := value.get("@id"), str) and iri and not iri.startswith(("#", "http", "ni:")):
            found.append(iri.partition("#")[0])
        for item in value.values():
            _links(item, found, strings)
    elif isinstance(value, list):
        for item in value:
            _links(item, found, strings)
    elif isinstance(value, str):
        strings.add(value)


def _list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def _reach(graph: Graph, roots: list[Path], stored: set[Path], media: dict[Path, dict]) -> tuple[set[Path], set[str]]:
    """Entities `roots` reach by links, part links and stored media, and the assets they name."""
    reached: set[Path] = set()
    strings: set[str] = set()
    pending = list(roots)

    def visit(origin: Path, document: dict) -> None:
        found: list[str] = []
        _links(document, found, strings)
        pending.extend((origin.parent / unquote(iri)).resolve() for iri in found)

    while pending:
        path = Path(pending.pop()).resolve()
        if path in reached or path not in stored:
            continue
        reached.add(path)
        entity = graph.read(path)
        visit(path, entity)
        if path.parent.name == "Dataset" and isinstance(entity.get("distribution"), dict):
            # Parts link relative to their Dataset.
            visit(path, {"hasPart": list(graph.parts(path).values())})

    # Media stored from kept media or kept URLs: downloaded and resized images.
    changed = True
    while changed:
        changed = False
        sources = strings | {media[path]["contentUrl"] for path in reached if path in media}
        for path, entity in media.items():
            if path not in reached and entity.get("isBasedOn") in sources:
                reached.add(path)
                strings.update(v for v in entity.values() if isinstance(v, str))
                changed = True
    return reached, {media[path]["sha256"] for path in reached if path in media}


def prune(graph: Graph, keep: int | None = None, budget: int = BUDGET) -> tuple[int, int]:
    """Delete what the kept runs do not reach; return how many entities and assets were deleted.

    Runs are kept whole, newest first: each with every action recorded during it, the newest
    render of its result, and all they reach. The newest completed run is always kept; older
    ones while everything kept fits in `budget` bytes, at most `keep` runs when given.
    A run still going is never pruned, nor anything it wrote.
    """
    actions = {
        path: graph.read(path)
        for kind in ("UpdateAction", "DownloadAction", "CreateAction")
        for path in graph.entities(kind)
    }
    runs = sorted(
        (
            (action["endTime"], action["startTime"], path)
            for path, action in actions.items()
            if path.parent.name == "UpdateAction" and action.get("actionStatus") == COMPLETED and "result" in action
        ),
        reverse=True,
    )
    if not runs:
        return 0, 0
    stored = {graph.path_of(key) for key in graph.store.list("schema/") if not registry(key)}
    media = {path: graph.read(path) for path in stored if path.parent.name in ("ImageObject", "DataDownload")}
    reached: set[Path] = set()
    hashes: set[str] = set()
    used = 0
    for count, (end, start, run) in enumerate(runs):
        roots = [run]
        result = graph.resolve(run, actions[run]["result"])
        renders = []
        for path, action in actions.items():
            if start <= action["startTime"] <= end:
                roots.append(path)
            elif "@id" not in action.get("result", {"@id": ""}) and any(
                graph.resolve(path, link) == result for link in _list(action.get("object"))
            ):
                # A render: it used the run's result and stored nothing.
                renders.append((action["startTime"], path))
        roots += [max(renders)[1]] if renders else []
        entities, assets = _reach(graph, roots, stored, media)
        added = sum(graph.store.size(graph.key(path)) for path in entities - reached) + sum(
            graph.store.size(f"assets/{sha}") for sha in assets - hashes if graph.store.exists(f"assets/{sha}")
        )
        if count and (used + added > budget or (keep is not None and count >= keep)):
            break
        reached |= entities
        hashes |= assets
        used += added
    # A run still going keeps every action recorded since it started and what they reach.
    going = [
        action["startTime"]
        for path, action in actions.items()
        if path.parent.name == "UpdateAction" and action.get("actionStatus") == ACTIVE
    ]
    unfinished = [path for path, action in actions.items() if going and action["startTime"] >= min(going)]
    unfinished_reach, unfinished_assets = _reach(graph, unfinished, stored, media)
    reached |= unfinished_reach
    hashes |= unfinished_assets
    entities = sorted(graph.key(path) for path in stored - reached)
    assets = sorted(key for key in graph.store.list("assets/") if key.removeprefix("assets/") not in hashes)
    graph.store.delete(entities + assets)
    return len(entities), len(assets)


def main() -> None:
    import argparse

    from .graph import DATA

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--keep", type=int, help="At most this many completed runs; default: as many as fit")
    cli.add_argument("--data", type=Path, default=DATA)
    cli.add_argument("--production", action="store_true", help="Prune the production R2 store")
    args = cli.parse_args()
    from .pipeline import open_store

    store = open_store(args.data.resolve(), production=args.production)
    entities, assets = prune(Graph(args.data.resolve(), store), args.keep)
    print(json.dumps({"entities": entities, "assets": assets}))
