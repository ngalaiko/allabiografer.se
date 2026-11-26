"""Delete what recent runs no longer reach.

Kept: the registry; the newest `keep` completed runs with every action recorded during
them; the newest render of each run's result; and everything those reach by links,
part links and stored MediaObjects (including images downloaded or resized from a kept
image or URL). The rendered site's asset links are kept too.
"""

import json
import os
from pathlib import Path
from urllib.parse import unquote

from .graph import Graph

REGISTRY = {"AdministrativeArea", "City", "Country", "DataFeed", "MovieTheater"}
COMPLETED = "https://schema.org/CompletedActionStatus"


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


def prune(graph: Graph, keep: int = 1) -> tuple[int, int]:
    """Delete unreachable entities and assets; return how many of each were deleted."""
    actions = {
        path: graph.read(path)
        for kind in ("UpdateAction", "DownloadAction", "CreateAction")
        for path in graph.schema.glob(f"{kind}/*.jsonld")
    }
    runs = sorted(
        (
            (action["endTime"], action["startTime"], path)
            for path, action in actions.items()
            if path.parent.name == "UpdateAction" and action.get("actionStatus") == COMPLETED and "result" in action
        ),
        reverse=True,
    )[:keep]
    if not runs:
        return 0, 0
    roots = []
    for end, start, run in runs:
        roots.append(run)
        result = graph.resolve(run, actions[run]["result"])
        renders = []
        for path, action in actions.items():
            if start <= action["startTime"] <= end:
                roots.append(path)
            elif action.get("name") == "Render" and graph.resolve(path, action["object"]) == result:
                renders.append((action["startTime"], path))
        roots += [max(renders)[1]] if renders else []

    reached: set[Path] = set()
    strings: set[str] = set()
    pending = list(roots)

    def visit(origin: Path, document: dict) -> None:
        found: list[str] = []
        _links(document, found, strings)
        pending.extend((origin.parent / unquote(iri)).resolve() for iri in found)

    while pending:
        path = Path(pending.pop()).resolve()
        if path in reached or not path.is_file() or path.parent.parent != graph.schema.resolve():
            continue
        reached.add(path)
        entity = graph.read(path)
        visit(path, entity)
        if path.parent.name == "Dataset" and isinstance(entity.get("distribution"), dict):
            # Parts link relative to their Dataset.
            visit(path, {"hasPart": list(graph.parts(path).values())})

    # Media stored from kept media or kept URLs: downloaded and resized images.
    media = {
        path.resolve(): graph.read(path)
        for kind in ("ImageObject", "DataDownload")
        for path in graph.schema.glob(f"{kind}/*.jsonld")
    }
    changed = True
    while changed:
        changed = False
        sources = strings | {media[path]["contentUrl"] for path in reached if path in media}
        for path, entity in media.items():
            if path not in reached and entity.get("isBasedOn") in sources:
                reached.add(path)
                strings.update(v for v in entity.values() if isinstance(v, str))
                changed = True

    hashes = {media[path]["sha256"] for path in reached if path in media}
    site = graph.root / "www"
    for link in site.rglob("*") if site.exists() else []:
        if link.is_symlink():
            hashes.add(Path(os.readlink(link)).name)

    entities = [
        path
        for path in graph.schema.glob("*/*.jsonld")
        if path.parent.name not in REGISTRY and path.resolve() not in reached
    ]
    assets = [path for path in graph.assets.iterdir() if path.name not in hashes] if graph.assets.exists() else []
    for path in entities + assets:
        path.unlink()
    for directory in graph.schema.iterdir():
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return len(entities), len(assets)


def main() -> None:
    import argparse

    from .graph import DATA

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--keep", type=int, default=1, help="Completed runs to keep")
    cli.add_argument("--data", type=Path, default=DATA)
    args = cli.parse_args()
    entities, assets = prune(Graph(args.data.resolve()), args.keep)
    print(json.dumps({"entities": entities, "assets": assets}))
