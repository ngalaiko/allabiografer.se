"""Fold new parse Datasets into the previous merged Dataset.

The merged Dataset carries the state between runs:

- `isBasedOn` lists the parse Datasets in effect, oldest first. Each registry DataFeed's
  screenings come from the newest one with a snapshot of it, so feeds left out of a run, or
  whose adapter failed, keep their previous screenings.
- Its parts are every film ever identified, the screenings from the run day onward, and
  past screenings of the last `HISTORY` days, carried from the previous result: the
  newsletter tells new films from those shown recently. A show listed by several feeds of
  one cinema appears once.

Films keep a stable slug, the `allabiografer:film` identifier. Grouping is re-evaluated
on every run; a group reuses the oldest identity among its members, slugs are never
reassigned, and slugs of films merged into another remain as `allabiografer:film-alias`.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from .graph import fragment
from .movie_matching import groups
from .sources._shared import STOCKHOLM

if TYPE_CHECKING:
    from pathlib import Path

    from .graph import Graph

FILM = "allabiografer:film"
# Past screenings kept, in days.
HISTORY = 30
ALIAS = "allabiografer:film-alias"
SITE = "https://allabiografer.se"
# Source records whose fields are replaced by the merged film's own.
_OWN_FIELDS = {"@context", "@id", "@type", "identifier", "isBasedOn", "url", "sameAs", "image"}


def slugify(text: str) -> str:
    """Slug preserving å ä ö, as published film URLs do."""
    text = re.sub(r"[^\wåäö\s-]", "", text.lower().strip())
    return re.sub(r"[-\s]+", "-", text).strip("-") or "unnamed"


@dataclass
class Identity:
    slug: str
    created: str
    aliases: set[str] = field(default_factory=set)


def _key(movie: dict) -> str:
    """A source record's identity: its adapter and the adapter's movie ID."""
    identifier = movie["identifier"]
    return json.dumps([identifier["propertyID"], identifier["value"]], ensure_ascii=False)


# A part's address: the Dataset holding it, and its fragment there.
Part = tuple["Path", str]


def _snapshots(graph: Graph, dataset: Path) -> list[tuple[Path, Part]]:
    """A parse Dataset's per-feed screening snapshots, with the registry feed each is of."""
    found = []
    for key, part in graph.parts(dataset).items():
        if part["@type"] == "Dataset" and "#" + key in {p["@id"] for p in _top(graph, dataset)}:
            found.append((graph.resolve(dataset, part["isBasedOn"]), (dataset, key)))
    return found


def _top(graph: Graph, dataset: Path) -> list[dict]:
    """A Dataset's own parts, without those of its nested Datasets."""
    nested = {
        part["@id"] for p in graph.parts(dataset).values() if p["@type"] == "Dataset" for part in p.get("hasPart", [])
    }
    return [part for key, part in graph.parts(dataset).items() if "#" + key not in nested]


def _of(graph: Graph, dataset: Path, kind: str) -> list[tuple[Part, dict]]:
    return [((dataset, part["@id"][1:]), part) for part in _top(graph, dataset) if part["@type"] == kind]


def _link(graph: Graph, part: Part) -> dict:
    return graph.part_ref(*part)


def _previous_films(graph: Graph, previous: Path) -> tuple[list[Identity], dict[str, Identity], dict[str, Part]]:
    identities, owners, records = [], {}, {}
    for _, film in _of(graph, previous, "Movie"):
        values = {item["propertyID"]: [] for item in film["identifier"]}
        for item in film["identifier"]:
            values[item["propertyID"]].append(item["value"])
        if FILM not in values:
            raise ValueError(f"{previous} has no film identities; start with --fresh")
        identity = Identity(values[FILM][0], film["dateCreated"], set(values.get(ALIAS, [])))
        identities.append(identity)
        for reference in film["isBasedOn"]:
            dataset, member = graph.find(previous, reference)
            key = _key(member)
            owners[key] = identity
            records[key] = (dataset, reference["@id"].partition("#")[2])
    return identities, owners, records


def merge_datasets(graph: Graph, previous: Path | None, parsed: list[Path], day: date) -> Path:
    identities, owners, records = _previous_films(graph, previous) if previous else ([], {}, {})
    # Past screenings name the previous film; any of its source records identifies it now.
    past_keys = {}
    for _, film in _of(graph, previous, "Movie") if previous else []:
        for reference in film["isBasedOn"]:
            past_keys.setdefault(film["@id"], _key(graph.find(previous, reference)[1]))
    datasets = [graph.resolve(previous, ref) for ref in graph.read(previous)["isBasedOn"]] if previous else []
    datasets += parsed

    # The newest snapshot of a feed supplies it; feeds gone from the registry drop out.
    suppliers: dict[Path, tuple[Path, Part]] = {}
    for dataset in datasets:
        for feed, snapshot in _snapshots(graph, dataset):
            if graph.exists(feed):
                suppliers[feed] = (dataset, snapshot)
    in_effect = [dataset for dataset in dict.fromkeys(datasets) if dataset in {d for d, _ in suppliers.values()}]

    # Newer source records replace older ones with the same identity. Screenings resolve
    # by that identity, so those from older datasets still find the current record.
    keys = {}
    for dataset in in_effect:
        for part, movie in _of(graph, dataset, "Movie"):
            records[_key(movie)] = part
            keys[part] = _key(movie)
    movies = {key: graph.parts(dataset)[part] for key, (dataset, part) in records.items()}

    screenings = []
    # Screenings per source record: the record listed most often names the film.
    shown = dict.fromkeys(records, 0)
    cinemas = set()
    for feed, (_, (dataset, part)) in sorted(suppliers.items(), key=lambda item: str(item[0])):
        snapshot = graph.parts(dataset)[part]
        cinemas.add(graph.resolve(dataset, snapshot["about"]))
        for screening in snapshot["hasPart"]:
            start = datetime.fromisoformat(screening["startDate"])
            if start.astimezone(STOCKHOLM).date() < day:
                continue
            key = keys[(dataset, screening["workPresented"]["@id"][1:])]
            shown[key] += 1
            screenings.append((key, graph.resolve(dataset, screening["location"]), feed, screening))

    used = {slug for identity in identities for slug in (identity.slug, *identity.aliases)}
    claimed: set[str] = set()
    films = {}
    for group in groups(movies):
        members = sorted(group, key=lambda key: (-shown[key], key))
        candidates = sorted(
            {
                owners[key].slug: owners[key] for key in group if key in owners and owners[key].slug not in claimed
            }.values(),
            key=lambda identity: (identity.created, identity.slug),
        )
        if candidates:
            identity = Identity(candidates[0].slug, candidates[0].created, set(candidates[0].aliases))
            for losing in candidates[1:]:
                identity.aliases |= {losing.slug, *losing.aliases}
        else:
            base = slugify(movies[members[0]]["name"])
            slug, suffix = base, 2
            while slug in used:
                slug, suffix = f"{base}-{suffix}", suffix + 1
            identity = Identity(slug, day.isoformat())
        used.add(identity.slug)
        claimed |= {identity.slug, *identity.aliases}
        film = _film(graph, identity, members, movies, records)
        for key in group:
            films[key] = film

    parts = {}
    for screening in _history(graph, previous, day) if previous else []:
        # Repointed to the film its source record belongs to now; records gone keep no history.
        if (key := past_keys.get(screening["workPresented"]["@id"])) in films:
            parts[screening["@id"]] = screening | {"workPresented": {"@id": films[key]["@id"]}}
    for key, screening in _distinct(screenings, {key: film["@id"] for key, film in films.items()}):
        merged = {k: v for k, v in screening.items() if k != "@id"} | {"workPresented": {"@id": films[key]["@id"]}}
        merged = {"@id": "#" + fragment("screening", merged), **merged}
        parts[merged["@id"]] = merged
    days = sorted({graph.read(dataset)["temporalCoverage"] for dataset in in_effect})
    unique_films = {film["@id"]: film for film in films.values()}
    return graph.put_dataset(
        {
            "name": "Merged screenings",
            "temporalCoverage": days[0] if len(days) == 1 else f"{days[0]}/{days[-1]}",
            "isBasedOn": [graph.ref(dataset) for dataset in in_effect],
            "spatialCoverage": graph.ref(graph.path("Country", "Sverige")),
            "about": [graph.ref(cinema) for cinema in sorted(cinemas, key=str)],
        },
        [unique_films[key] for key in sorted(unique_films)] + [parts[key] for key in sorted(parts)],
    )


def _history(graph: Graph, previous: Path, day: date) -> list[dict]:
    """The previous result's screenings before `day`, within `HISTORY` days."""
    since = day - timedelta(days=HISTORY)
    found = []
    for _, screening in _of(graph, previous, "ScreeningEvent"):
        if since <= datetime.fromisoformat(screening["startDate"]).astimezone(STOCKHOLM).date() < day:
            found.append(screening)
    return found


def _distinct(screenings: list, films: dict) -> list[dict]:
    """One screening per show: feeds of one cinema may list the same one.

    A show is a film at a cinema at a start time in one version. Within a feed, matching
    entries stay apart; a source lists what it sells, such as two halls.
    """
    shows: dict[tuple, dict[Path, list[dict]]] = {}
    for key, cinema, feed, screening in screenings:
        version = json.dumps(
            [screening.get(name) for name in ("inLanguage", "subtitleLanguage", "videoFormat")],
            sort_keys=True,
        )
        show = (films[key], cinema, datetime.fromisoformat(screening["startDate"]), version)
        shows.setdefault(show, {}).setdefault(feed, []).append((key, screening))
    result = []
    for by_feed in shows.values():
        # The cinema's own feed, then the one naming an organiser, keeps the show.
        feed = min(by_feed, key=lambda feed: ("organizer" in by_feed[feed][0][1], str(feed)))
        result += [(key, screening) for key, screening in by_feed[feed]]
    return result


def _film(graph: Graph, identity: Identity, members: list[str], movies: dict, records: dict) -> dict:
    """A film's fields: preferred values from the member with the most screenings."""
    fields = {}
    same_as = set()
    image = None
    for key in members:
        movie = movies[key]
        for name, value in movie.items():
            if name not in _OWN_FIELDS:
                fields.setdefault(name, value)
        links = movie.get("sameAs", [])
        # Source pages identify the film too; the film's own url is its allabiografer page.
        same_as |= {movie.get("url", ""), *(links if isinstance(links, list) else [links])} - {""}
        if image is None and (found := movie.get("image")):
            image = graph.ref(graph.resolve(records[key][0], found)) if isinstance(found, dict) else found
    return {
        "@id": "#" + fragment("film", identity.slug),
        "@type": "Movie",
        "identifier": [{"@type": "PropertyValue", "propertyID": FILM, "value": identity.slug}]
        + [{"@type": "PropertyValue", "propertyID": ALIAS, "value": alias} for alias in sorted(identity.aliases)],
        "url": f"{SITE}/film/{identity.slug}/",
        "dateCreated": identity.created,
        **fields,
        **({"sameAs": sorted(same_as)} if same_as else {}),
        **({"image": image} if image else {}),
        "isBasedOn": [_link(graph, records[key]) for key in sorted(members)],
    }
