"""Build the Programme: new listings folded into the previous Programme.

The Programme carries the state between runs:

- `isBasedOn` lists the parse Datasets in effect, oldest first. Each registry DataFeed's
  screenings come from the newest one with a snapshot of it, so feeds left out of a run, or
  whose adapter failed, keep their previous screenings. A snapshot listing nothing from the
  run day on does not replace one that does: a source that reads empty has more likely
  changed than emptied its programme. The held feeds are reported.
- Its parts are every film ever identified, the screenings from the run day onward, and
  past screenings of the last `HISTORY` days, carried from the previous result: the
  newsletter tells new films from those shown recently. A show listed by several feeds of
  one cinema appears once.

Every part links its sources in `isBasedOn`: a screening the parsed screening it is, a film
its parsed records and, when TMDB filled it, the responses and posters that decided it.

A film without screenings is settled: it keeps its fields and identity, and links the files
its records were read from instead of the records, so the day's listings around them can be
pruned. Settled films are kept for good and group with new records like records do: a film
listed again finds its slug, and pages once published keep resolving.

Films keep a stable slug, the `allabiografer:film` identifier. Grouping is re-evaluated
on every run; a group reuses the oldest identity among its members, slugs are never
reassigned, and slugs of films merged into another remain as `allabiografer:film-alias`.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from . import enrich as tmdb
from .graph import fragment
from .movie_matching import groups, references
from .sources._shared import STOCKHOLM

if TYPE_CHECKING:
    from pathlib import Path

    from .graph import Graph

FILM = "allabiografer:film"
# Past screenings kept, in days.
HISTORY = 30
# Feeds listing at least this many screenings are reported when a read loses most of them.
LOST_FLOOR = 10
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


def _identity(film: dict, source: Path) -> Identity:
    values = {item["propertyID"]: [] for item in film["identifier"]}
    for item in film["identifier"]:
        values[item["propertyID"]].append(item["value"])
    if FILM not in values:
        raise ValueError(f"{source} has no film identities; start with --fresh")
    return Identity(values[FILM][0], film["dateCreated"], set(values.get(ALIAS, [])))


def _slug(film: dict) -> str:
    return next(item["value"] for item in film["identifier"] if item["propertyID"] == FILM)


def _previous_films(graph: Graph, previous: Path) -> tuple[list[Identity], dict[str, Identity], dict[str, Part]]:
    identities, owners, records = [], {}, {}
    for _, film in _of(graph, previous, "Movie"):
        identity = _identity(film, previous)
        identities.append(identity)
        for reference in _records(film):
            dataset, member = graph.find(previous, reference)
            key = _key(member)
            owners[key] = identity
            records[key] = (dataset, reference["@id"].partition("#")[2])
    return identities, owners, records


def _records(film: dict) -> list[dict]:
    """A film's links to parsed records; the others lead to TMDB responses and posters."""
    return [reference for reference in film["isBasedOn"] if "#" in reference["@id"]]


@dataclass
class Combined:
    """A merge before it is stored: the Dataset's fields, its films and its screenings."""

    fields: dict
    films: list[dict]
    screenings: list[dict]
    day: date
    # Feeds read empty whose earlier screenings were kept, and feeds that lost most of theirs.
    warnings: dict[str, str] = field(default_factory=dict)


def merge_datasets(
    graph: Graph, previous: Path | None, parsed: list[Path], day: date, capture: Path | None = None
) -> Path:
    return build(graph, previous, parsed, day, capture)[0]


def build(
    graph: Graph, previous: Path | None, parsed: list[Path], day: date, capture: Path | None = None
) -> tuple[Path, dict[str, str]]:
    """The Programme, and warnings about feeds.

    Films needing it are filled from the TMDB answers in `capture` alone; without a capture,
    from the answers that decided the previous Programme's films, so a TMDB outage loses nothing.
    """
    combined = combine(graph, previous, parsed, day)
    parts = combined.films + combined.screenings
    answers = (
        tmdb.replaying(graph, capture)
        if capture is not None
        else tmdb.previous_answers(graph, previous)
        if previous is not None
        else None
    )
    if answers is not None:
        parts, count = tmdb.enrich_parts(graph, parts, day, answers)
        print(f"Filled {count} films from TMDB")
    shown = {part["workPresented"]["@id"] for part in parts if part["@type"] == "ScreeningEvent"}
    parts = [_settle(graph, part) if part["@type"] == "Movie" and part["@id"] not in shown else part for part in parts]
    return graph.put_dataset(combined.fields, parts), combined.warnings


def _settle(graph: Graph, film: dict) -> dict:
    """A film without screenings, linking the files its records were read from instead of the records."""
    origin = graph.path("Dataset", "_")
    links = []
    for link in film["isBasedOn"]:
        if "#" not in link["@id"]:
            links.append(link)
            continue
        dataset, record = graph.find(origin, link)
        links += [graph.ref(graph.resolve(dataset, file)) for file in _list(record.get("isBasedOn"))]
    return film | {"isBasedOn": list({link["@id"]: link for link in links}.values())}


def _list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def combine(graph: Graph, previous: Path | None, parsed: list[Path], day: date) -> Combined:
    identities, owners, records = _previous_films(graph, previous) if previous else ([], {}, {})
    # Past screenings name the previous film; any of its source records identifies it now.
    past_keys = {}
    for _, film in _of(graph, previous, "Movie") if previous else []:
        for reference in _records(film):
            past_keys.setdefault(film["@id"], _key(graph.find(previous, reference)[1]))
    datasets = [graph.resolve(previous, ref) for ref in graph.read(previous).get("isBasedOn", [])] if previous else []
    datasets += parsed
    # Settled films stand for themselves among the records: a group holding one keeps its identity.
    settled = {}
    for _, film in _of(graph, previous, "Movie") if previous else []:
        if not _records(film):
            key = json.dumps(["settled", _slug(film)], ensure_ascii=False)
            owners[key] = _identity(film, previous)
            settled[key] = film

    # The newest snapshot of a feed supplies it; feeds gone from the registry drop out.
    suppliers: dict[Path, tuple[Path, Part]] = {}
    upcoming: dict[Path, int] = {}
    warnings: dict[str, str] = {}
    for dataset in datasets:
        for feed, snapshot in _snapshots(graph, dataset):
            if not graph.exists(feed):
                continue
            count = _upcoming(graph, snapshot, day)
            if count == 0 and upcoming.get(feed):
                warnings[graph.read(feed)["name"]] = f"read no screenings; kept the {upcoming[feed]} listed before"
                continue
            if dataset in parsed and feed in upcoming and upcoming[feed] >= LOST_FLOOR and count < upcoming[feed] / 2:
                warnings[graph.read(feed)["name"]] = f"read {count} screenings, down from {upcoming[feed]}"
            suppliers[feed] = (dataset, snapshot)
            upcoming[feed] = count
    in_effect = [dataset for dataset in dict.fromkeys(datasets) if dataset in {d for d, _ in suppliers.values()}]

    # Newer source records replace older ones with the same identity. Screenings resolve
    # by that identity, so those from older datasets still find the current record.
    keys = {}
    for dataset in in_effect:
        for part, movie in _of(graph, dataset, "Movie"):
            records[_key(movie)] = part
            keys[part] = _key(movie)
    movies = {key: graph.parts(dataset)[part] for key, (dataset, part) in records.items()} | settled

    screenings = []
    # Screenings per source record: the record listed most often names the film.
    shown = dict.fromkeys(movies, 0)
    cinemas = set()
    for feed, (_, (dataset, part)) in sorted(suppliers.items(), key=lambda item: str(item[0])):
        snapshot = graph.parts(dataset)[part]
        cinemas.add(graph.resolve(feed, graph.read(feed)["about"]))
        for screening in snapshot["hasPart"]:
            start = datetime.fromisoformat(screening["startDate"])
            if start.astimezone(STOCKHOLM).date() < day:
                continue
            key = keys[(dataset, screening["workPresented"]["@id"][1:])]
            shown[key] += 1
            screenings.append((key, graph.resolve(dataset, screening["location"]), feed, dataset, screening))

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
        film = _film(graph, identity, members, movies, records, previous)
        for key in group:
            films[key] = film

    parts = {}
    for screening in _history(graph, previous, day) if previous else []:
        # Repointed to the film its source record belongs to now; records gone keep no history.
        if (key := past_keys.get(screening["workPresented"]["@id"])) in films:
            parts[screening["@id"]] = screening | {"workPresented": {"@id": films[key]["@id"]}}
    for key, dataset, screening in _distinct(screenings, {key: film["@id"] for key, film in films.items()}):
        merged = {k: v for k, v in screening.items() if k != "@id"} | {
            "workPresented": {"@id": films[key]["@id"]},
            "isBasedOn": graph.part_ref(dataset, screening["@id"][1:]),
        }
        merged = {"@id": "#" + fragment("screening", merged), **merged}
        parts[merged["@id"]] = merged
    days = sorted({_captured(graph, dataset)["temporalCoverage"] for dataset in in_effect})
    unique_films = {film["@id"]: film for film in films.values()}
    return Combined(
        {
            "name": "Programme",
            "temporalCoverage": days[0] if len(days) == 1 else f"{days[0]}/{days[-1]}",
            "isBasedOn": [graph.ref(dataset) for dataset in in_effect],
            "about": [graph.ref(cinema) for cinema in sorted(cinemas, key=str)],
        },
        [unique_films[key] for key in sorted(unique_films)],
        [parts[key] for key in sorted(parts)],
        day,
        warnings,
    )


def _upcoming(graph: Graph, snapshot: Part, day: date) -> int:
    """How many of a feed snapshot's screenings are on `day` or later."""
    dataset, key = snapshot
    return sum(
        datetime.fromisoformat(show["startDate"]).astimezone(STOCKHOLM).date() >= day
        for show in graph.parts(dataset)[key]["hasPart"]
    )


def _captured(graph: Graph, parsed: Path) -> dict:
    """The capture a parse Dataset was read from."""
    return graph.read(graph.resolve(parsed, graph.read(parsed)["isBasedOn"]))


def _history(graph: Graph, previous: Path, day: date) -> list[dict]:
    """The previous result's screenings before `day`, within `HISTORY` days."""
    since = day - timedelta(days=HISTORY)
    found = []
    for _, screening in _of(graph, previous, "ScreeningEvent"):
        if since <= datetime.fromisoformat(screening["startDate"]).astimezone(STOCKHOLM).date() < day:
            found.append(screening)
    return found


def _distinct(screenings: list, films: dict) -> list[tuple]:
    """One screening per show: feeds of one cinema may list the same one.

    A show is a film at a cinema at a start time in one version. Within a feed, matching
    entries stay apart; a source lists what it sells, such as two halls.
    """
    shows: dict[tuple, dict[Path, list[tuple]]] = {}
    for key, cinema, feed, dataset, screening in screenings:
        version = json.dumps(
            [screening.get(name) for name in ("inLanguage", "subtitleLanguage", "videoFormat")],
            sort_keys=True,
        )
        show = (films[key], cinema, datetime.fromisoformat(screening["startDate"]), version)
        shows.setdefault(show, {}).setdefault(feed, []).append((key, dataset, screening))
    result = []
    for by_feed in shows.values():
        # The cinema's own feed, then the one naming an organiser, keeps the show.
        feed = min(by_feed, key=lambda feed: ("organizer" in by_feed[feed][0][2], str(feed)))
        result += by_feed[feed]
    return result


def _film(
    graph: Graph, identity: Identity, members: list[str], movies: dict, records: dict, previous: Path | None
) -> dict:
    """A film's fields: preferred values from the member with the most screenings.

    It links its members' records, and the files a settled member links.
    """
    fields = {}
    same_as = set()
    image = None
    for key in members:
        movie = movies[key]
        for name, value in movie.items():
            if name not in _OWN_FIELDS:
                fields.setdefault(name, value)
        links = movie.get("sameAs", [])
        # TMDB and IMDb entries identify the film; source pages are reached through `isBasedOn`.
        same_as |= {link for link in (links if isinstance(links, list) else [links]) if references({"sameAs": [link]})}
        if image is None and (found := movie.get("image")):
            origin = records[key][0] if key in records else previous
            image = graph.ref(graph.resolve(origin, found)) if isinstance(found, dict) else found
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
        "isBasedOn": [_link(graph, records[key]) for key in sorted(members) if key in records]
        + [link for key in sorted(members) if key not in records for link in movies[key]["isBasedOn"]],
    }
