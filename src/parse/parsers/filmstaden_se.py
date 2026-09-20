"""filmstaden.se — cinema-api.com REST API, all cinemas in one pass."""

import logging
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import requests
from curl_cffi import requests as cffi_requests

from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue, film_key

log = logging.getLogger(__name__)

_API = "https://services.cinema-api.com"
_SOURCE = "filmstaden_se"

# Poster URLs carry a width parameter; the catalog serves any width on demand.
_POSTER_WIDTH = 800

# Placeholder the API uses for films the censors have not classified.
_UNRATED = "ej bestämd"

# The image CDN serves posters only to browser user agents.
_POSTER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _get(session: cffi_requests.Session, url: str, **kw: Any) -> Any:
    resp = session.get(url, impersonate="chrome", timeout=30, **kw)
    resp.raise_for_status()
    return resp.json()


def _screening(
    show: dict[str, Any], *, tmdb_id: int | None, cinema_name: str, city: str, film_key: str = ""
) -> Screening:
    """Map one API show onto a Screening."""
    dt = datetime.fromisoformat(show["time"])
    attrs = show.get("attributes", [])
    version = show.get("movieVersion") or {}
    return Screening(
        tmdb_id=tmdb_id,
        film_key=film_key,
        title=show["movie"]["title"],
        date=dt.date(),
        time=dt.time(),
        cinema_name=cinema_name,
        city=city,
        screen=show.get("screen", {}).get("title", ""),
        format=", ".join(a["displayName"] for a in attrs if a.get("displayName")),
        language=(version.get("audioLanguageInfo") or {}).get("displayName", ""),
        subtitles=(version.get("subtitlesLanguageInfo") or {}).get("displayName", ""),
        ticket_url=f"https://www.filmstaden.se/bokning/kop/{show.get('remoteEntityId', '')}/",
    )


def _poster_url(movie: dict[str, Any]) -> str:
    """Poster image resized to a display-friendly width."""
    url = next(
        (i.get("url", "") for i in movie.get("images") or [] if i.get("imageType") == "Poster"),
        movie.get("posterUrl") or "",
    )
    return re.sub(r"(?<=[?&])w=\d+", f"w={_POSTER_WIDTH}", url) if url else ""


def _release_date(raw: str | None) -> str:
    """ISO date from an API timestamp, empty for the 0001-01-01 placeholder."""
    day = (raw or "")[:10]
    return day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and not day.startswith("0001") else ""


def _age_rating(movie: dict[str, Any]) -> str:
    name = (movie.get("rating") or {}).get("displayName") or ""
    return "" if _UNRATED in name.casefold() else name


def _film(movie: dict[str, Any], detail: dict[str, Any] | None = None) -> Film:
    """Film metadata from a show's movie object, enriched with its detail payload."""
    detail = detail or {}
    original = detail.get("originalTitle") or ""
    slug = movie.get("slug") or ""
    return _films.make(
        _SOURCE,
        movie["title"],
        title_original="" if original == movie["title"] else original,
        overview=(detail.get("shortDescription") or "").strip(),
        runtime=movie.get("length") or None,
        genres=[g["name"] for g in movie.get("genres") or [] if g.get("name")],
        release_date=_release_date(movie.get("releaseDate")),
        age_rating=_age_rating(movie),
        poster_url=_poster_url(movie),
        url=f"https://www.filmstaden.se/film/{slug}/" if slug else "",
    )


def _detail(session: cffi_requests.Session, ncg_id: str) -> dict[str, Any]:
    """Movie detail payload — the only place synopsis and original title live."""
    # A missing synopsis must not stop the run.
    try:
        return _get(session, f"{_API}/movie/sv/{ncg_id}")
    except Exception as exc:
        log.warning("filmstaden: movie %s detail failed: %s", ncg_id, exc)
        return {}


def parse() -> Iterator[Screening | Venue | Film]:
    session = cffi_requests.Session()
    posters = requests.Session()
    posters.headers.update({"User-Agent": _POSTER_UA})
    cinemas = _get(session, f"{_API}/cinema/sv/1/1024")["items"]
    log.info("filmstaden: %d cinemas", len(cinemas))

    seen_films: set[str] = set()

    for cinema in cinemas:
        ncg_id = cinema["ncgId"]
        title = cinema["title"]
        addr = cinema.get("address", {})
        city = addr.get("city", {}).get("name", "Unknown")
        street = addr.get("streetAddress", "")

        yield Venue(name=title, city=city, address=street)

        page, shows = 1, []
        while True:
            data = _get(session, f"{_API}/show/sv/{page}/1024", params={"CinemaNcgId": ncg_id})
            items = data["items"]
            shows.extend(items)
            if len(shows) >= data.get("totalNbrOfItems", 0) or len(items) < 1024:
                break
            page += 1

        count = 0
        for show in shows:
            raw = show.get("time", "")
            movie = show.get("movie", {})
            film_title = movie.get("title", "")
            if not raw or not film_title:
                continue

            key = film_key(_SOURCE, film_title)
            if key not in seen_films:
                seen_films.add(key)
                detail = _detail(session, movie["ncgId"]) if movie.get("ncgId") else None
                yield _films.register(_film(movie, detail), session=posters)

            tmdb_id = _tmdb(film_title, runtime=movie.get("length"))
            yield _screening(show, tmdb_id=tmdb_id, cinema_name=title, city=city, film_key=key)
            count += 1

        log.info("  %s (%s): %d screenings", title, city, count)
