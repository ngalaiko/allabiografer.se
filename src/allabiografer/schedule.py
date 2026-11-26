"""Schedule routing from the registry's DataFeeds.

A DataFeed is one published programme: one source adapter and, for adapters covering many
venues, the source's venue ID. Its `about` is the MovieTheater the screenings take place in;
a cinema may have several feeds, a feed has one cinema.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from .graph import DATA

PREFIX = "allabiografer:schedule:"


@dataclass(frozen=True)
class Feed:
    name: str
    cinema: str
    adapter: str
    venue_id: str | None


def feeds(data: Path = DATA) -> dict[str, Feed]:
    """Every registry DataFeed, keyed by its ID."""
    result = {}
    used = set()
    cinemas = data / "schema" / "MovieTheater"
    for path in sorted((data / "schema" / "DataFeed").glob("*.jsonld")):
        document = json.loads(path.read_bytes())
        identifier = document.get("identifier")
        if not isinstance(identifier, dict) or not identifier.get("propertyID", "").startswith(PREFIX):
            raise ValueError(f"{path}: expected one schedule identifier")
        adapter = identifier["propertyID"].removeprefix(PREFIX)
        # Single-cinema adapters need no venue ID.
        venue_id = identifier.get("value")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", adapter) or (
            venue_id is not None and not (isinstance(venue_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", venue_id))
        ):
            raise ValueError(f"{path}: invalid schedule identifier")
        package = Path(__file__).parent / "sources" / adapter
        if not all((package / f"{step}.py").is_file() for step in ("fetch", "parse")):
            raise ValueError(f"{path}: unknown schedule adapter {adapter}")
        cinema = (path.parent / unquote(document["about"]["@id"])).resolve()
        if cinema.parent != cinemas.resolve() or not cinema.is_file():
            raise ValueError(f"{path}: about must be a registry MovieTheater")
        key = (adapter, venue_id)
        if key in used:
            raise ValueError(f"{path}: duplicate schedule identifier {adapter}:{venue_id}")
        used.add(key)
        result[path.stem] = Feed(path.stem, cinema.stem, adapter, venue_id)
    if not result:
        raise ValueError(f"No feeds under {data}")
    return result


def checked(selectors: set[str] | None, known) -> None:
    if selectors is not None and (unknown := selectors.difference(known)):
        raise ValueError(f"Unknown selectors: {', '.join(sorted(unknown))}")
