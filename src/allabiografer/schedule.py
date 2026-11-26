"""Schedule routing from MovieTheater identifiers."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .graph import DATA

PREFIX = "allabiografer:schedule:"


@dataclass(frozen=True)
class Route:
    cinema: str
    adapter: str
    venue_id: str | None


def routes(data: Path = DATA) -> dict[str, Route]:
    """Every registry cinema's single schedule binding, keyed by MovieTheater ID."""
    result = {}
    used = set()
    for path in sorted((data / "schema" / "MovieTheater").glob("*.jsonld")):
        document = json.loads(path.read_bytes())
        identifiers = document["identifier"]
        if len(identifiers) != 1 or not identifiers[0]["propertyID"].startswith(PREFIX):
            raise ValueError(f"{path}: expected exactly one schedule identifier")
        binding = identifiers[0]
        adapter = binding["propertyID"].removeprefix(PREFIX)
        # Single-cinema adapters need no venue ID.
        venue_id = binding.get("value")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", adapter) or (
            venue_id is not None and not (isinstance(venue_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", venue_id))
        ):
            raise ValueError(f"{path}: invalid schedule binding")
        package = Path(__file__).parent / "sources" / adapter
        if not all((package / f"{step}.py").is_file() for step in ("fetch", "parse")):
            raise ValueError(f"{path}: unknown schedule adapter {adapter}")
        key = (adapter, venue_id)
        if key in used:
            raise ValueError(f"{path}: duplicate schedule binding {adapter}:{venue_id}")
        used.add(key)
        result[path.stem] = Route(path.stem, adapter, venue_id)
    if not result:
        raise ValueError(f"No cinemas under {data}")
    return result


def checked(selectors: set[str] | None, known) -> None:
    if selectors is not None and (unknown := selectors.difference(known)):
        raise ValueError(f"Unknown cinema selectors: {', '.join(sorted(unknown))}")
