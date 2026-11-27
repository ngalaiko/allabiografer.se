"""Fill gaps in merged films from TMDB.

Only films missing a poster, description or director are looked up. A film's TMDB
entry is the one its sources state (`sameAs` TMDB or IMDb links), else the single
search result whose title, year, director and runtime do not contradict the film.
TMDB values fill missing properties only; what cinemas state is kept.

A DownloadAction captures the responses, and the source posters checked, in a Dataset; merging
replays that capture alone. A filled film links the responses and posters that decided it.
"""

import json
import os
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from .graph import media_type
from .movie_fields import normalise
from .movie_matching import _close, _facts, _people, _relation, references, title_keys, work_title
from .posters import portrait, stored_downloads

if TYPE_CHECKING:
    from .graph import Graph

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


class Answers:
    """TMDB responses and source posters by URL: asked live and stored, or replayed from a capture."""

    def __init__(self, graph: Graph, session=None, found: dict[str, Path] | None = None):
        self.graph = graph
        self.session = session
        self.found = dict(found or {})
        # Everything answered, in order: the capture's contents.
        self.used: list[Path] = []

    def json(self, path: str, params: dict) -> tuple[dict, Path]:
        key = url(path, params)
        if key not in self.found:
            if self.session is None:
                raise KeyError(f"Not captured: {key}")
            headers = {"Authorization": f"Bearer {token()}", "Accept": "application/json"}
            response = self.session.get(key, headers=headers, timeout=30)
            # A missing film is an answer too; anything else is a failure.
            if response.status_code != 404:
                response.raise_for_status()
            self.found[key] = self.graph.put_bytes(response.content, "application/json", name=path.strip("/"), url=key)
        self.used.append(self.found[key])
        return json.loads(self.graph.content(self.graph.read(self.found[key]))), self.found[key]

    def image(self, address: str) -> Path | None:
        """The stored image downloaded from `address`; None when it cannot be had."""
        if address not in self.found and self.session is not None:
            try:
                response = self.session.get(address, timeout=30)
                response.raise_for_status()
            except Exception:
                return None
            media = media_type(address, response.headers.get("Content-Type", ""))
            if not media.startswith("image/"):
                return None
            self.found[address] = self.graph.put_bytes(response.content, media, name=Path(address).name, url=address)
        if address not in self.found:
            return None
        self.used.append(self.found[address])
        return self.found[address]


def recording(graph: Graph, session) -> Answers:
    """Answers asked live; posters downloaded before are reused."""
    return Answers(graph, session, stored_downloads(graph))


def replaying(graph: Graph, capture: Path) -> Answers:
    """Answers from a capture Dataset only."""
    paths = [graph.resolve(capture, reference) for reference in graph.read(capture)["distribution"]]
    graph.prefetch(paths)
    found = {}
    for path in paths:
        found[graph.read(path)["isBasedOn"]] = path
    graph.prefetch_content([graph.read(path) for path in paths])
    return Answers(graph, found=found)


def _usable_poster(graph: Graph, image, answers: Answers, sources: list[Path]) -> bool:
    """Whether an image is a poster: not a still, a banner or a placeholder."""
    if isinstance(image, dict):
        return portrait(graph, graph.read(graph.resolve(graph.path("Dataset", "_"), image)))
    if not isinstance(image, str) or not image.startswith(("http://", "https://")):
        return False
    stored = answers.image(image)
    if stored is None:
        return False
    sources.append(stored)
    return portrait(graph, graph.read(stored))


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
    # Each result under every title it was found by: Swedish, English and original.
    seen, titles = {}, defaultdict(set)
    for query in dict.fromkeys(filter(None, (work_title(film.get("name") or ""), film.get("alternateName")))):
        for language in ("sv-SE", "en-US"):
            params = {"query": query, "language": language, "include_adult": "false"}
            for result in fetch("/search/movie", params).get("results") or []:
                seen.setdefault(result["id"], result)
                titles[result["id"]] |= title_keys(
                    {"name": result.get("title"), "alternateName": result.get("original_title")}
                )
    # As in merging: one title is one work unless what is stated contradicts it.
    namesakes = [result for tmdb_id, result in seen.items() if titles[tmdb_id] & keys]
    listing = _facts(film)
    # As in merging: one title is one work, split where stated facts contradict.
    consistent, confirmed = [], []
    for result in namesakes:
        detail = _detail(fetch, result["id"])
        if "id" not in detail:
            continue
        candidate = _facts(tmdb_movie(detail))
        relation = _relation(listing, candidate)
        runtimes = listing["runtime"], candidate["runtime"]
        # A matching director or plot outweighs a runtime: listings count intervals and extras.
        if relation == "different" or (relation != "same" and all(runtimes) and not _close(*runtimes)):
            continue
        consistent.append(result["id"])
        # Remakes and stage recordings share a title; among namesakes, a fact must agree. A listing's
        # language confirms but never rules out: cinemas state the screening's, which may be a dub.
        if (
            relation == "same"
            or (listing["year"] and candidate["year"])
            or (all(runtimes) and _exact(*runtimes))
            or (candidate["year"] and detail.get("original_language") in (film.get("inLanguage") or []))
        ):
            confirmed.append(result["id"])
    if len(consistent) == 1 and len(namesakes) == 1:
        return consistent[0]
    # Entries without a year are drafts and duplicates; they never outweigh a confirmed film.
    return confirmed[0] if len(confirmed) == 1 else None


def _exact(a: int, b: int) -> bool:
    """Runtimes that single out one cut: listings round by a minute."""
    return abs(a - b) <= 1


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


def enrich_parts(graph: Graph, parts: list[dict], today: date, answers: Answers) -> tuple[list[dict], int]:
    """`parts` with the films that need it filled from TMDB, and how many were.

    Each film checked links the responses and downloaded posters that decided it.
    """
    # Past films keep their pages' history; only films with screenings are looked up.
    showing = {
        part["workPresented"]["@id"]
        for part in parts
        if part["@type"] == "ScreeningEvent" and date.fromisoformat(part["startDate"][:10]) >= today
    }
    enriched, count = [], 0
    for part in parts:
        if part["@type"] == "Movie" and part["@id"] in showing:
            sources: list[Path] = []

            def fetch(path: str, params: dict, sources: list[Path] = sources) -> dict:
                found, source = answers.json(path, params)
                sources.append(source)
                return found

            checked = part
            if part.get("image") and not _usable_poster(graph, part["image"], answers, sources):
                checked = {key: value for key, value in part.items() if key != "image"}
            if needs(checked):
                tmdb_id = _identify(fetch, checked)
                detail = _detail(fetch, tmdb_id) if tmdb_id is not None else {}
                if "id" in detail:
                    filled = enrich_film(checked, tmdb_movie(detail))
                    if filled != part:
                        part, count = filled, count + 1
            if sources:
                links = [graph.ref(path) for path in dict.fromkeys(sources)]
                part = part | {"isBasedOn": [*part["isBasedOn"], *links]}
        enriched.append(part)
    return enriched, count
