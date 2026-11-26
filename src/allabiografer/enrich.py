"""Fill gaps in merged films from TMDB.

Only films missing a poster, description or director are looked up. A film's TMDB
entry is the one its sources state (`sameAs` TMDB or IMDb links), else the single
search result whose title, year, director and runtime do not contradict the film.
TMDB values fill missing properties only; what cinemas state is kept.

A DownloadAction captures the responses as DataDownloads; the enrich CreateAction replays
them, so its result follows from stored inputs alone.
"""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from .graph import Graph
from .movie_fields import normalise
from .movie_matching import _close, _people, fold, references, title_keys, work_title
from .posters import poster, stored_downloads

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/original"
TOKEN = Path.home() / ".config" / "allabiografer" / "tmdb-token"
# A film lacking any of these is looked up.
CRITICAL = ("image", "description", "director")
# Filled from TMDB when missing.
FILLED = ("image", "description", "director", "actor", "genre", "duration", "datePublished", "alternateName")

Fetch = Callable[[str, dict], dict]


def url(path: str, params: dict) -> str:
    """The request URL, with parameters in a stable order: the key of a stored response."""
    return f"{API}{path}?{urlencode(sorted(params.items()))}" if params else f"{API}{path}"


def token() -> str:
    """The API read access token: TMDB_ACCESS_TOKEN, else ~/.config/allabiografer/tmdb-token."""
    if found := os.environ.get("TMDB_ACCESS_TOKEN", "").strip():
        return found
    if TOKEN.is_file():
        return TOKEN.read_text(encoding="utf-8").strip()
    raise RuntimeError(f"No TMDB token: set TMDB_ACCESS_TOKEN or write {TOKEN}")


def needs(film: dict) -> bool:
    return any(not film.get(field) for field in CRITICAL)


def _without_unusable_poster(graph: Graph, path: Path, film: dict, session, downloaded: dict) -> dict:
    """The film without an image that is no poster: a still, a banner or a placeholder."""
    if film.get("image") and poster(graph, path, film["image"], session, downloaded) is None:
        return {key: value for key, value in film.items() if key != "image"}
    return film


def _year(film: dict) -> int | None:
    found = re.match(r"(?:19|20)\d\d", film.get("datePublished") or "")
    return int(found[0]) if found else None


def _minutes(film: dict) -> int | None:
    found = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", film.get("duration") or "")
    return (int(found[1] or 0) * 60 + int(found[2] or 0)) or None if found else None


def _surnames(film: dict) -> set[str]:
    return {name.split()[-1] for name in _people(film, "director")}


def _detail(fetch: Fetch, tmdb_id: int) -> dict:
    return fetch(
        f"/movie/{tmdb_id}",
        {
            "language": "sv-SE",
            "append_to_response": "credits,images,release_dates",
            "include_image_language": "sv,null,en",
        },
    )


def _identify(fetch: Fetch, film: dict) -> int | None:
    """The film's TMDB ID: stated, via a stated IMDb ID, or the one consistent search result."""
    stated = references(film)
    if ids := sorted(int(ref[5:]) for ref in stated if ref.startswith("tmdb:")):
        return ids[0] if len(ids) == 1 else None
    if imdb := sorted(ref[5:] for ref in stated if ref.startswith("imdb:")):
        found = fetch(f"/find/{imdb[0]}", {"external_source": "imdb_id"}).get("movie_results") or []
        return found[0]["id"] if len(found) == 1 else None
    keys = title_keys(film)
    year, minutes, surnames = _year(film), _minutes(film), _surnames(film)
    seen = {}
    for query in dict.fromkeys(filter(None, (work_title(film.get("name") or ""), film.get("alternateName")))):
        params = {"query": query, "language": "sv-SE", "include_adult": "false"}
        for result in fetch("/search/movie", params).get("results") or []:
            seen.setdefault(result["id"], result)
    namesakes = [
        result
        for result in seen.values()
        if title_keys({"name": result.get("title"), "alternateName": result.get("original_title")}) & keys
    ]
    # Remakes, adaptations and stage recordings share titles: with namesakes, a year or a
    # director must confirm the choice; a unique title needs only a consistent runtime.
    accepted = []
    for result in namesakes:
        released = re.match(r"\d{4}", result.get("release_date") or "")
        if not released or (year and abs(int(released[0]) - year) > 1):
            continue
        detail = _detail(fetch, result["id"])
        if "id" not in detail:
            continue
        directors = {fold(c["name"]).split()[-1] for c in detail["credits"]["crew"] if c["job"] == "Director"}
        if surnames and directors and not surnames & directors:
            continue
        if minutes and detail.get("runtime") and not _close(minutes, detail["runtime"]):
            continue
        strong = bool(year) or bool(surnames & directors)
        timed = bool(minutes and detail.get("runtime"))
        if strong or (len(namesakes) == 1 and timed):
            accepted.append(result["id"])
    return accepted[0] if len(accepted) == 1 else None


def tmdb_movie(detail: dict) -> dict:
    """A normalised Movie from a TMDB detail response."""
    posters = (detail.get("images") or {}).get("posters") or []
    swedish = next((p["file_path"] for p in posters if p.get("iso_639_1") == "sv"), None)
    poster = swedish or detail.get("poster_path")
    crew = (detail.get("credits") or {}).get("crew") or []
    cast = (detail.get("credits") or {}).get("cast") or []
    swedish_rating = next(
        (
            release["certification"]
            for country in (detail.get("release_dates") or {}).get("results") or []
            if country["iso_3166_1"] == "SE"
            for release in country["release_dates"]
            if release.get("certification")
        ),
        "",
    )
    return normalise(
        {
            "name": detail.get("title"),
            "alternateName": detail.get("original_title"),
            "sameAs": [f"https://www.themoviedb.org/movie/{detail['id']}"]
            + ([f"https://www.imdb.com/title/{detail['imdb_id']}"] if detail.get("imdb_id") else []),
            "description": detail.get("overview"),
            "duration": detail.get("runtime"),
            "datePublished": detail.get("release_date"),
            "genre": [genre["name"] for genre in detail.get("genres") or []],
            # Swedish certifications: "Btl", "7", "11", "15".
            "contentRating": swedish_rating,
            "inLanguage": [detail.get("original_language")],
            "image": f"{IMAGES}{poster}" if poster else "",
            "director": [c["name"] for c in crew if c.get("job") == "Director"],
            "actor": [c["name"] for c in cast[:10]],
        }
    )


def enrich_film(film: dict, found: dict) -> dict:
    """The film with missing properties filled from TMDB, and TMDB among its sources."""
    filled = dict(film)
    for field in FILLED:
        if not film.get(field) and found.get(field):
            filled[field] = found[field]
    links = film.get("sameAs") or []
    filled["sameAs"] = sorted({*(links if isinstance(links, list) else [links]), *found["sameAs"]})
    return filled


def recording(graph: Graph, session, downloads: list[Path]) -> Fetch:
    """A fetch that stores every response as a DataDownload; repeated requests are asked once."""
    headers = {"Authorization": f"Bearer {token()}", "Accept": "application/json"}
    asked: dict[str, Path] = {}

    def fetch(path: str, params: dict) -> dict:
        key = url(path, params)
        if key not in asked:
            response = session.get(key, headers=headers, timeout=30)
            # A missing film is an answer too; anything else is a failure.
            if response.status_code != 404:
                response.raise_for_status()
            asked[key] = graph.put_bytes(response.content, "application/json", name=path.strip("/"), url=key)
            downloads.append(asked[key])
        return json.loads(graph.content(graph.read(asked[key])))

    return fetch


def replaying(graph: Graph, capture: Path) -> Fetch:
    """A fetch answered from a capture Dataset's DataDownloads only."""
    stored = {}
    for reference in graph.read(capture)["distribution"]:
        download = graph.read(graph.resolve(capture, reference))
        stored[download["isBasedOn"]] = download

    def fetch(path: str, params: dict) -> dict:
        return json.loads(graph.content(stored[url(path, params)]))

    return fetch


def enrich_dataset(graph: Graph, merged: Path, fetch: Fetch, session=None) -> tuple[Path, int]:
    """A copy of `merged` whose films that need it are filled from TMDB, and how many were.

    `session` downloads source poster URLs to check them; without one, only stored images are checked.
    """
    downloaded = stored_downloads(graph)
    dataset = graph.read(merged)
    entities = {graph.resolve(merged, reference): None for reference in dataset["hasPart"]}
    for path in entities:
        entities[path] = graph.read(path)
    # Past films keep their pages' history; only films with screenings are looked up.
    showing = {
        graph.resolve(path, entity["workPresented"])
        for path, entity in entities.items()
        if entity["@type"] == "ScreeningEvent"
    }
    parts, replaced, count = [], {}, 0
    for path, entity in entities.items():
        checked = (
            _without_unusable_poster(graph, path, entity, session, downloaded)
            if entity["@type"] == "Movie" and path in showing
            else entity
        )
        if entity["@type"] == "Movie" and path in showing and needs(checked):
            entity = checked
            tmdb_id = _identify(fetch, entity)
            detail = _detail(fetch, tmdb_id) if tmdb_id is not None else {}
            if "id" in detail:
                found = tmdb_movie(detail)
                fields = {k: v for k, v in enrich_film(entity, found).items() if k not in ("@context", "@id", "@type")}
                new = graph.put("Movie", fields)
                if new != path:
                    replaced[path] = new
                    count += 1
                path = new
        parts.append(path)
    # Screenings point at films; repoint those whose film changed.
    final = []
    for path in parts:
        entity = graph.read(path)
        if entity["@type"] == "ScreeningEvent":
            work = graph.resolve(path, entity["workPresented"])
            if work in replaced:
                fields = {k: v for k, v in entity.items() if k not in ("@context", "@id", "@type")}
                path = graph.put("ScreeningEvent", fields | {"workPresented": graph.ref(replaced[work])})
        final.append(path)
    fields = {k: v for k, v in dataset.items() if k not in ("@context", "@id", "@type", "hasPart")}
    return (
        graph.put("Dataset", fields | {"hasPart": [graph.ref(path) for path in sorted(set(final), key=str)]}),
        count,
    )
