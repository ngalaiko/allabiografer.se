"""Schedule routing from MovieTheater identifiers."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

PREFIX = "allabiografer:schedule:"
DATA = Path(__file__).resolve().parent / "data"
SELECTION = "selection.json"


@dataclass(frozen=True)
class Route:
    cinema: str
    adapter: str
    venue_id: str


def schedule_identifier(source: str, venue_id: str) -> list[dict[str, str]]:
    return [{"@type": "PropertyValue", "propertyID": f"{PREFIX}{source}", "value": venue_id}]


def routes(data: Path = DATA) -> dict[str, Route]:
    result = {}
    used = set()
    for path in sorted((data / "schema" / "MovieTheater").glob("*.jsonld")):
        document = json.loads(path.read_bytes())
        identifiers = document["identifier"]
        if len(identifiers) != 1 or not identifiers[0]["propertyID"].startswith(PREFIX):
            raise ValueError(f"{path}: expected exactly one schedule identifier")
        binding = identifiers[0]
        adapter = binding["propertyID"].removeprefix(PREFIX)
        venue_id = binding["value"]
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]*", adapter)
            or not isinstance(venue_id, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]+", venue_id)
        ):
            raise ValueError(f"{path}: invalid schedule binding")
        package = Path(__file__).parent / "source" / adapter
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


def selection(inputs: Path) -> list[dict] | None:
    path = inputs / SELECTION
    return json.loads(path.read_bytes()) if path.is_file() else None


_LEGACY_PREFIXES = {
    "bio_se": "bio-se-",
    "bioguiden_se": "bioguiden-",
    "biosverige_se": "biosverige-",
    "cinemascenen_se": "cinemascenen-",
    "doclounge_se": "doclounge-",
    "filmstaden_se": "filmstaden-",
    "nfbio_se": "nfbio-",
    "nortic_se": "nortic-",
    "svenskabio_se": "svenskabio-",
}


def local_venue_id(source: str, venue: str) -> str:
    return venue.removeprefix(_LEGACY_PREFIXES.get(source, ""))


def selected_venues(inputs: Path) -> set[str] | None:
    selected = selection(inputs)
    if selected is None:
        return None
    venues = {
        venue for route in selected for venue in ((route["venue_id"],) if "venue_id" in route else route["venue_ids"])
    }
    return {local_venue_id(inputs.name, venue) for venue in venues}


def checked(selectors: set[str] | None, known) -> None:
    if selectors is not None and (unknown := selectors.difference(known)):
        raise ValueError(f"Unknown cinema selectors: {', '.join(sorted(unknown))}")
