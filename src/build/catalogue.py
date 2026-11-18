"""Reconcile source observations, reserve film URLs, and publish a saved schedule.

Ambiguous candidates remain separate. Their evidence is saved for inspection;
only a complete catalogue and schedule replaces the previous snapshot.
"""

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from itertools import combinations, cycle
from pathlib import Path
from zoneinfo import ZoneInfo

from parse.tmdb import _clean_title
from store import (
    DB_FILE,
    Film,
    Movie,
    Screening,
    Venue,
    connect,
    film_key,
    poster_key_for_film,
    poster_keys,
    read_all_films,
    read_movies,
    read_screenings,
)
from store.film import shared_synopsis, title_key

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalogue_films (
  id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE,
  tmdb_id INTEGER, merged_into INTEGER REFERENCES catalogue_films(id)
);
CREATE TABLE IF NOT EXISTS catalogue_slugs (
  slug TEXT PRIMARY KEY, film_id INTEGER NOT NULL REFERENCES catalogue_films(id)
);
CREATE TABLE IF NOT EXISTS catalogue_members (
  key TEXT PRIMARY KEY, film_id INTEGER NOT NULL REFERENCES catalogue_films(id), data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_candidates (
  left_key TEXT NOT NULL, right_key TEXT NOT NULL, reason TEXT NOT NULL,
  evidence TEXT NOT NULL, PRIMARY KEY (left_key, right_key)
);
CREATE TABLE IF NOT EXISTS catalogue_snapshot (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS catalogue_tmdb_matches (key TEXT PRIMARY KEY, data TEXT NOT NULL);
"""


def observation_key(screening: Screening) -> str:
    """Keep conflicting source TMDB claims separate, even under one source title."""
    base = screening.film_key or (
        f"tmdb:{screening.tmdb_id}" if screening.tmdb_id else film_key(screening.source, screening.title)
    )
    return json.dumps([base, screening.tmdb_id], ensure_ascii=False)


@dataclass
class _Observation:
    key: str
    film: Film
    tmdb_id: int | None
    slots: set[tuple[str, ...]]
    existing: int | None = None

    def to_dict(self) -> dict:
        return {"film": self.film.to_dict(), "tmdb_id": self.tmdb_id, "slots": sorted(self.slots)}


def _metadata(node: _Observation, movies: dict[int, Movie]) -> Film:
    film = node.film
    movie = movies.get(node.tmdb_id)
    return replace(
        film,
        runtime=film.runtime or (movie.runtime if movie else None),
        release_date=film.release_date or (movie.release_date if movie else ""),
    )


def _runtime_compatible(a: Film, b: Film, *, programme: bool = False) -> bool:
    if not a.runtime or not b.runtime:
        return True
    difference = abs(a.runtime - b.runtime)
    # Substantial shared descriptions can identify a work despite a short,
    # interval or pre-programme. This is not permission to join different cuts.
    return difference * 4 <= min(a.runtime, b.runtime) if programme else difference <= 2


def _evidence(
    left: _Observation, right: _Observation, movies: dict[int, Movie], *, shared_title: bool = False
) -> tuple[bool, str]:
    if left.tmdb_id and right.tmdb_id:
        return left.tmdb_id == right.tmdb_id, "same_tmdb" if left.tmdb_id == right.tmdb_id else "different_tmdb"
    if left.film.key == right.film.key and left.film.url and left.film.url == right.film.url:
        return True, "source_identity"

    def titles(node):
        movie = movies.get(node.tmdb_id)
        return {
            title_key(_clean_title(t))
            for t in (
                node.film.title,
                node.film.title_original,
                movie.title_sv if movie else "",
                movie.title_original if movie else "",
            )
            if t
        }

    if not shared_title and not titles(left) & titles(right):
        return False, "different_titles"

    a, b = _metadata(left, movies), _metadata(right, movies)
    close_runtime = bool(a.runtime and b.runtime and abs(a.runtime - b.runtime) <= 2)
    years = (a.release_date[:4], b.release_date[:4])
    if all(y.isdigit() for y in years) and abs(int(years[0]) - int(years[1])) > 1:
        return False, "year_disagreement"
    credited_director = any(
        f" {credit} " in f" {title_key(candidate.film.overview)} "
        for known, candidate in ((left, right), (right, left))
        for director in (movies[known.tmdb_id].directors or [] if known.tmdb_id in movies else [])
        for credit in (
            f"regi {title_key(director)}",
            f"regisserad av {title_key(director)}",
            f"directed by {title_key(director)}",
            f"{title_key(director)}s",
        )
    )
    if shared_synopsis(a.overview, b.overview, corroborated=credited_director) and _runtime_compatible(
        left.film, right.film, programme=True
    ):
        return True, "shared_synopsis"
    # A complete short synopsis can identify sources, but cannot justify
    # programme-length differences or relax TMDB's runtime validation.
    if shared_synopsis(a.overview, b.overview, allow_short=True) and _runtime_compatible(left.film, right.film):
        return True, "complete_synopsis"
    # Missing source runtimes may use TMDB as positive corroboration, but an
    # inferred duration must not contradict agreeing first-hand source facts.
    if left.film.runtime and right.film.runtime and abs(left.film.runtime - right.film.runtime) > 5:
        return False, "runtime_disagreement"
    if a.key == b.key:
        return True, "source_identity"
    left_unknown = {slot[:4] for slot in left.slots if not slot[4]}
    right_unknown = {slot[:4] for slot in right.slots if not slot[4]}
    if (
        left.slots & right.slots
        or left_unknown & {slot[:4] for slot in right.slots}
        or right_unknown & {slot[:4] for slot in left.slots}
    ):
        return True, "shared_showtime"
    if close_runtime and years[0] and years[0] == years[1]:
        return True, "title_year_runtime"
    return False, "insufficient_evidence"


def _groups(nodes: dict[str, _Observation], movies: dict[int, Movie]) -> tuple[list[list[str]], list[dict]]:
    """Validate entire components, not order-dependent similarity chains."""
    parent = {key: key for key in nodes}

    def root(key):
        while parent[key] != key:
            key = parent[key]
        return key

    def union(keys):
        roots = sorted({root(key) for key in keys})
        for key in roots[1:]:
            parent[key] = roots[0]

    anchors = defaultdict(list)
    for key, node in nodes.items():
        if node.tmdb_id:
            anchors[("tmdb", node.tmdb_id)].append(key)
    for keys in anchors.values():
        union(keys)

    source_identities = defaultdict(list)
    for key, node in nodes.items():
        if node.film.url:
            source_identities[(node.film.key, node.film.url)].append(key)
    for keys in source_identities.values():
        if len(keys) < 2:
            continue
        roots = {root(key) for key in keys}
        known = {node.tmdb_id for key, node in nodes.items() if root(key) in roots and node.tmdb_id}
        if len(known) <= 1:
            union(keys)

    def compatible(a, b, units, programme):
        evidence = [_evidence(nodes[x], nodes[y], movies, shared_title=True) for x in units[a] for y in units[b]]
        return not any(reason in {"different_tmdb", "year_disagreement"} for _, reason in evidence) and any(
            _runtime_compatible(nodes[x].film, nodes[y].film, programme=programme) for x in units[a] for y in units[b]
        )

    candidates = []
    # Establish strong textual identities before considering year/runtime
    # similarity. Repeat to propagate newly confirmed title aliases as well.
    previous_count = len({root(key) for key in nodes})
    for programme in cycle((True, False)):
        units = defaultdict(list)
        for key in nodes:
            units[root(key)].append(key)
        by_title = defaultdict(set)
        for key, node in nodes.items():
            movie = movies.get(node.tmdb_id)
            for title in (
                node.film.title,
                node.film.title_original,
                movie.title_sv if movie else "",
                movie.title_original if movie else "",
            ):
                if title:
                    by_title[title_key(_clean_title(title))].add(root(key))
        pairs = {pair for values in by_title.values() for pair in combinations(sorted(values), 2)}
        edges = defaultdict(set)

        for a, b in sorted(pairs):
            # Title aliases belong to the established work, not just the member
            # that happens to carry its best synopsis or runtime.
            evidence = [_evidence(nodes[x], nodes[y], movies, shared_title=True) for x in units[a] for y in units[b]]
            known = {nodes[key].tmdb_id for key in units[a] + units[b] if nodes[key].tmdb_id}
            positive = any(match and (not programme or reason == "shared_synopsis") for match, reason in evidence)
            if len(known) <= 1 and positive and compatible(a, b, units, programme):
                edges[a].add(b)
                edges[b].add(a)
            elif not programme and len(known) <= 1:
                conflicts = {reason for _, reason in evidence if reason.endswith("disagreement")}
                candidates.append(
                    {
                        "left": a,
                        "right": b,
                        "reason": sorted(conflicts)[0] if conflicts else "insufficient_evidence",
                        "evidence": sorted({reason for _, reason in evidence}),
                    }
                )

        visited = set()
        for start in sorted(edges):
            if start in visited:
                continue
            component, pending = set(), [start]
            while pending:
                key = pending.pop()
                if key not in component:
                    component.add(key)
                    pending.extend(edges[key] - component)
            visited.update(component)
            known = {nodes[key].tmdb_id for unit in component for key in units[unit] if nodes[key].tmdb_id}
            # Validate nonadjacent units too: neither weak runtime chains nor
            # an unmatched bridge may join conflicting works transitively.
            if len(known) <= 1 and all(
                compatible(a, b, units, programme) for a, b in combinations(sorted(component), 2)
            ):
                union(component)
            else:
                for a, b in combinations(sorted(component), 2):
                    candidates.append(
                        {
                            "left": a,
                            "right": b,
                            "reason": "ambiguous_chain",
                            "evidence": {"component": sorted(component)},
                        }
                    )
        if not programme:
            count = len({root(key) for key in nodes})
            if count == previous_count:
                break
            previous_count = count
    result = defaultdict(list)
    for key in sorted(nodes):
        result[root(key)].append(key)
    candidates = list(
        {
            (item["left"], item["right"]): item for item in candidates if root(item["left"]) != root(item["right"])
        }.values()
    )
    return list(result.values()), candidates


def reconcile(*, path: Path = DB_FILE, today: date | None = None, enrich: bool = False) -> dict:
    """Publish one consistent snapshot. Offline by default for reproducible backtests."""
    import build

    today = today or datetime.now(ZoneInfo("Europe/Stockholm")).date()
    films = {film.key: film for film in read_all_films(path=path)}
    # Fetch completion order must not select fallback titles or schedule order.
    screenings = sorted(
        (s for s in read_screenings(path=path) if s.date >= today),
        key=lambda s: json.dumps(s.to_dict(), sort_keys=True),
    )

    source = build._load_data(Path("."), screenings=screenings, today=today, path=path)
    conn = connect(path)
    try:
        conn.executescript(_SCHEMA)
        records = {
            row[0]: {"slug": row[1], "tmdb_id": row[2]}
            for row in conn.execute("SELECT id, slug, tmdb_id FROM catalogue_films WHERE merged_into IS NULL")
        }
        bootstrap = not records
        nodes = {}
        for key, identifier, data in conn.execute("SELECT key, film_id, data FROM catalogue_members"):
            data = json.loads(data)
            historical = Film.from_dict(data["film"])
            # Keep past screening evidence, not superseded source metadata.
            film = films.get(historical.key, historical)
            nodes[key] = _Observation(key, film, data["tmdb_id"], {tuple(slot) for slot in data["slots"]}, identifier)
        active = set()
        for s in screenings:
            key = observation_key(s)
            film = films.get(s.film_key) or Film(
                key=s.film_key or film_key(s.source, s.title), source=s.source, title=s.title
            )
            if key not in nodes:
                nodes[key] = _Observation(key, film, s.tmdb_id, set())
            node = nodes[key]
            active.add(key)
            node.film = film
            # A past shared screening remains identity evidence even after
            # either source stops listing it. Only the final schedule expires.
            node.slots.add((s.city, s.cinema_name, s.date.isoformat(), s.time.isoformat(), s.screen))

        from parse import tmdb
        from parse.queries import read_requests

        # Neither a historical TMDB assignment nor metadata inferred from it
        # may establish the source groups that will validate that assignment.
        groups, candidates = _groups({k: replace(n, tmdb_id=None) for k, n in nodes.items()}, {})
        movies = read_movies([row[0] for row in conn.execute("SELECT tmdb_id FROM movies")], path=path)
        requests = read_requests(path=path)
        matches = {}
        previous_matches = {
            key: json.loads(data) for key, data in conn.execute("SELECT key,data FROM catalogue_tmdb_matches")
        }
        if enrich:
            # Discover the entire inventory before deciding: a later alias
            # search may reveal a competing candidate for an earlier group.
            for group in groups:
                matches[group[0]] = tmdb.match_group(
                    list({nodes[k].film.key: nodes[k].film for k in group}.values()),
                    movies,
                    identifiers={json.loads(k)[1] for k in group if json.loads(k)[1]},
                    queries=[q for k in group for q in requests.get(nodes[k].film.key, [])],
                    path=path,
                    online=True,
                )
        # Independently validated source titles can discover candidates whose
        # TMDB titles use another language. They are not identity evidence:
        # every group is revalidated against the complete expanded inventory.
        source_titles = defaultdict(set)
        for group in groups:
            decision = tmdb.match_group(
                list({nodes[k].film.key: nodes[k].film for k in group}.values()),
                movies,
                identifiers={json.loads(k)[1] for k in group if json.loads(k)[1]},
                queries=[q for k in group for q in requests.get(nodes[k].film.key, [])],
                path=path,
            )
            if identifier := decision["tmdb_id"]:
                source_titles[identifier].update(decision["titles"])
        joined = defaultdict(list)
        for group in groups:
            group_films = list({nodes[k].film.key: nodes[k].film for k in group}.values())
            decision = tmdb.match_group(
                group_films,
                movies,
                identifiers={json.loads(k)[1] for k in group if json.loads(k)[1]},
                queries=[q for k in group for q in requests.get(nodes[k].film.key, [])],
                source_titles=source_titles,
                path=path,
            )
            decision["source_films"] = [f.to_dict() for f in group_films]
            if matches.get(group[0], {}).get("reason") == "lookup_unavailable":
                previous = previous_matches.get(group[0], {})
                if (
                    decision["tmdb_id"]
                    and previous.get("tmdb_id") == decision["tmdb_id"]
                    and previous.get("source_films") == decision["source_films"]
                    and previous.get("members") == group
                ):
                    decision["reason"] = "retained_during_outage"
                else:
                    decision["tmdb_id"] = None
                    decision["reason"] = "lookup_unavailable"
            matches[group[0]] = decision | {"members": group}
            identifier = decision["tmdb_id"]
            for key in group:
                nodes[key].tmdb_id = identifier
            joined[("tmdb", identifier) if identifier else ("source", group[0])].extend(group)
        groups = list(joined.values())
        owners = {key: i for i, group in enumerate(groups) for key in group}
        candidates = [c for c in candidates if owners[c["left"]] != owners[c["right"]]]
        if enrich:
            # Candidate discovery needs metadata, not thousands of unrelated posters.
            for identifier in sorted({n.tmdb_id for n in nodes.values() if n.tmdb_id}):
                tmdb.by_id(identifier, path=path)
        source.movies.update(movies)
        # Give the historically preferred TMDB work the clean URL on first import.
        groups.sort(
            key=lambda group: (min((nodes[k].tmdb_id for k in group if nodes[k].tmdb_id), default=float("inf")), group)
        )
        aliases = dict(conn.execute("SELECT slug, film_id FROM catalogue_slugs"))
        previous_snapshot = conn.execute("SELECT data FROM catalogue_snapshot WHERE id = 1").fetchone()
        previous_cinemas = json.loads(previous_snapshot[0]).get("cinemas", []) if previous_snapshot else []
        identities = {}
        resolved_ids = {}
        claimed = set()
        from parse import mark_dubbed, tmdb_languages

        enriched = [replace(s, tmdb_id=nodes[observation_key(s)].tmdb_id) for s in screenings]
        classified = mark_dubbed(enriched, films.values(), tmdb_languages(enriched, path=path))
        screenings = [
            replace(updated, tmdb_id=original.tmdb_id) for original, updated in zip(screenings, classified, strict=True)
        ]
        conn.execute("BEGIN IMMEDIATE")
        for group in groups:
            # Reevaluate evidence on every run, so corrected metadata or rules
            # can split a previous incorrect merge. One old identity can serve
            # only one of the corrected groups; its slug is never reassigned.
            existing = sorted({nodes[key].existing for key in group if nodes[key].existing} - claimed)
            real_id = next((nodes[key].tmdb_id for key in group if nodes[key].tmdb_id), None)
            if existing:
                identifier = existing[0]
                for losing in existing[1:]:
                    conn.execute("UPDATE catalogue_films SET merged_into = ? WHERE id = ?", (identifier, losing))
                    conn.execute("UPDATE catalogue_members SET film_id = ? WHERE film_id = ?", (identifier, losing))
                    conn.execute("UPDATE catalogue_slugs SET film_id = ? WHERE film_id = ?", (identifier, losing))
                    aliases = {slug: identifier if owner == losing else owner for slug, owner in aliases.items()}
            else:
                title = movies[real_id].title_sv if real_id in movies else nodes[group[0]].film.title
                base = build._slugify_sv(title)
                slug, suffix = base, 2
                while slug in aliases:
                    slug = f"{base}-{suffix}"
                    suffix += 1
                identifier = conn.execute(
                    "INSERT INTO catalogue_films (slug, tmdb_id) VALUES (?, ?)", (slug, real_id)
                ).lastrowid
                records[identifier] = {"slug": slug, "tmdb_id": real_id}
                aliases[slug] = identifier
                conn.execute("INSERT INTO catalogue_slugs VALUES (?, ?)", (slug, identifier))
            claimed.update(existing)
            claimed.add(identifier)
            conn.execute("UPDATE catalogue_films SET tmdb_id = ? WHERE id = ?", (real_id, identifier))
            resolved_ids[-identifier] = real_id
            for key in group:
                # Negative keys retain the renderer's existing internal-ID contract;
                # actual TMDB IDs are stored separately and never fabricated in feeds.
                identities[key] = -identifier
                data = nodes[key].to_dict()
                data["matches"] = [
                    {"key": other, "reason": _evidence(nodes[key], nodes[other], movies)[1]}
                    for other in group
                    if other != key
                ]
                conn.execute(
                    "INSERT OR REPLACE INTO catalogue_members VALUES (?, ?, ?)",
                    (key, identifier, json.dumps(data, ensure_ascii=False)),
                )

        # All database reads are complete; preparation here is pure, so the
        # registry, aliases, candidates and schedule commit in one transaction.
        prepared = build._load_data(
            Path("."),
            screenings=screenings,
            identities=identities,
            today=today,
            path=path,
            source=source,
            resolved_ids=resolved_ids,
        )
        # A catalogue page outlives its last showtime. Keep historical identities
        # and metadata, without reintroducing expired tickets into the schedule.
        stored_posters = poster_keys(path=path)
        for group in groups:
            key = identities[group[0]]
            if key in prepared.movies:
                continue
            members = sorted({nodes[k].film.key: nodes[k].film for k in group}.values(), key=lambda f: f.key)
            real_id = resolved_ids[key]
            metadata = movies.get(real_id) or Movie.from_dict({"tmdb_id": key, "title_sv": members[0].title})
            prepared.movies[key] = build._merge_films(replace(metadata, tmdb_id=key), members)
            prepared.tmdb_ids[key] = real_id
            for poster in [str(real_id), *(poster_key_for_film(f.key) for f in members)]:
                if poster in stored_posters:
                    prepared.poster_keys[key] = poster
                    break
        prepared.city_films = {(slot[0], identities[key]) for key, node in nodes.items() for slot in node.slots}
        prepared.cinema_slugs.update({(city, cinema): build._slugify_sv(cinema) for city, cinema in previous_cinemas})
        prepared.cinema_slugs.update(
            {(slot[0], slot[1]): build._slugify_sv(slot[1]) for node in nodes.values() for slot in node.slots}
        )
        prepared.film_slugs = {key: records[-key]["slug"] for key in prepared.movies}
        if bootstrap:
            import hashlib

            for screening in screenings:
                old_id = screening.tmdb_id
                if old_id is None:
                    identity = screening.film_key or f"{screening.source}:{title_key(screening.title)}"
                    old_id = -int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")
                old_slug = source.film_slugs.get(old_id)
                owner = -identities[observation_key(screening)]
                if old_slug and old_slug not in aliases:
                    conn.execute("INSERT INTO catalogue_slugs VALUES (?, ?)", (old_slug, owner))
                    aliases[old_slug] = owner
        prepared.film_aliases = {
            slug: records[owner]["slug"]
            for slug, owner in aliases.items()
            if -owner in prepared.movies and slug != records[owner]["slug"]
        }
        conn.execute("DELETE FROM catalogue_tmdb_matches")
        conn.executemany(
            "INSERT INTO catalogue_tmdb_matches VALUES (?, ?)",
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in matches.items()],
        )
        conn.execute("DELETE FROM reconciliation_candidates")
        for candidate in candidates:
            conn.execute(
                "INSERT OR REPLACE INTO reconciliation_candidates VALUES (?, ?, ?, ?)",
                (
                    candidate["left"],
                    candidate["right"],
                    candidate["reason"],
                    json.dumps(candidate["evidence"], ensure_ascii=False),
                ),
            )
        snapshot = {
            # Persist catalogue identities as film_id, never as fabricated TMDB IDs.
            "screenings": [
                s.to_dict() | {"film_id": -s.tmdb_id, "tmdb_id": prepared.tmdb_ids[s.tmdb_id]}
                for s in prepared.screenings
            ],
            "movies": {
                -key: movie.to_dict() | {"tmdb_id": prepared.tmdb_ids[key]} for key, movie in prepared.movies.items()
            },
            "films": {key: film.to_dict() for key, film in prepared.films.items()},
            "venues": [venue.to_dict() for venue in prepared.venues.values()],
            "poster_keys": {-key: value for key, value in prepared.poster_keys.items()},
            "tmdb_ids": {-key: value for key, value in prepared.tmdb_ids.items()},
            "film_slugs": {-key: value for key, value in prepared.film_slugs.items()},
            "film_aliases": prepared.film_aliases,
            "city_films": sorted((city, -key) for city, key in prepared.city_films),
            "cinemas": sorted(prepared.cinema_slugs),
        }
        conn.execute(
            "INSERT OR REPLACE INTO catalogue_snapshot VALUES (1, ?)", (json.dumps(snapshot, ensure_ascii=False),)
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return {
        "source_films": len(active),
        "films": len(prepared.movies),
        "source_screenings": len(screenings),
        "screenings": len(prepared.screenings),
        "candidates": len(candidates),
    }


def read_catalogue(out_dir: Path, *, path: Path = DB_FILE, today: date | None = None):
    """Read the last published schedule, never reconciling during static rendering."""
    from build import SiteData, _slugify_sv

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        try:
            row = conn.execute("SELECT data FROM catalogue_snapshot WHERE id = 1").fetchone()
        except sqlite3.OperationalError as error:
            raise RuntimeError("No reconciled catalogue. Run `uv run reconcile` before building.") from error
        if row is None:
            raise RuntimeError("No reconciled catalogue. Run `uv run reconcile` before building.")
        data = json.loads(row[0])
    finally:
        conn.close()
    sd = SiteData(out_dir=out_dir, db_path=path)
    if today is not None:
        sd.today = today
    # The renderer historically uses negative movie keys for non-TMDB identities.
    # Keep that detail at this boundary; stored film_id and tmdb_id remain distinct.
    sd.movies = {-int(key): Movie.from_dict(value | {"tmdb_id": -int(key)}) for key, value in data["movies"].items()}
    sd.films = {key: Film.from_dict(value) for key, value in data["films"].items()}
    sd.screenings = [
        Screening.from_dict(value | {"tmdb_id": -value["film_id"]})
        for value in data["screenings"]
        if value["date"] >= sd.today.isoformat()
    ]
    sd.venues = {(v.city, v.name): v for v in map(Venue.from_dict, data["venues"])}
    for name in ("poster_keys", "tmdb_ids", "film_slugs"):
        setattr(sd, name, {-int(key): value for key, value in data[name].items()})
    sd.film_aliases = data["film_aliases"]
    # Older snapshots can still retain their pages when read after expiry.
    sd.city_films = {(city, -key) for city, key in data.get("city_films", [])}
    sd.city_films.update((s["city"], -s["film_id"]) for s in data["screenings"])
    cinemas = {tuple(pair) for pair in data.get("cinemas", [])}
    cinemas.update((s["city"], s["cinema_name"]) for s in data["screenings"])
    for city, cinema in sorted(cinemas):
        sd.cities.setdefault(city, 0)
        sd.city_slugs[city] = _slugify_sv(city)
        sd.cinema_slugs[(city, cinema)] = _slugify_sv(cinema)
    for screening in sd.screenings:
        sd.cities[screening.city] = sd.cities.get(screening.city, 0) + 1
        sd.city_slugs[screening.city] = _slugify_sv(screening.city)
        sd.cinema_slugs[(screening.city, screening.cinema_name)] = _slugify_sv(screening.cinema_name)
    return sd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_FILE)
    parser.add_argument("--today", type=date.fromisoformat)
    parser.add_argument("--enrich", action="store_true", help="Resolve saved source queries with TMDB")
    args = parser.parse_args()
    print(json.dumps(reconcile(path=args.db, today=args.today, enrich=args.enrich), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
