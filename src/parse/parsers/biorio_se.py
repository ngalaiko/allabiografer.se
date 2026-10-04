"""biorio.se — the site's public showtimes and movie JSON API."""

import logging
import re
from collections.abc import Iterator
from datetime import date, time
from urllib.parse import urlencode

import requests

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import by_id as _tmdb_by_id
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "biorio_se"
_SITE = "https://www.biorio.se"
_API = "https://api.biorio.se/api/public/site"
# The default page holds 50 showtimes; the whole programme is a few hundred at most.
_SHOWTIMES_URL = f"{_API}/showtimes?limit=1000"
_CINEMA = "Bio Rio"
_CITY = "Stockholm"
_ADDRESS = "Hornstulls strand 3"

# Posters go through the site's Next.js image proxy, scaled to this width.  It answers
# JPEG unless the request's Accept header lists AVIF or WebP, but passes through unscaled
# an original it cannot decode: many AVIF posters, an 8268x11812 PNG.  The JPEG
# rendition the API names as ogImageUrl scales.
_POSTER_WIDTH = "640"

# Programmes of several films: "Dune: Part One + Two", "Sagan om ringen-maraton".
_MULTI_FILM = re.compile(r"\s\+\s|maraton|marathon|double feature", re.IGNORECASE)
# Showtime statuses the box office will not sell.
_CANCELLED = re.compile(r"cancel", re.IGNORECASE)

# "13:15", "13:15:00".
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::\d{2})?")

# Placeholders the API writes for an unstated language.
_UNSTATED = {"", "-", "n/a", "tba", "tbc", "ej angivet"}


def _label(text: str | None) -> str:
    text = (text or "").strip()
    return "" if text.casefold() in _UNSTATED else text


def _poster_url(src: str) -> str:
    if not src:
        return ""
    return f"{_SITE}/_next/image?" + urlencode({"url": src, "w": _POSTER_WIDTH, "q": "85"})


def _film(movie: dict) -> Film:
    language = _label(movie.get("language"))
    # A dubbed track names the screening language, not the original.
    dubbed = re.search(r"dubb", language, re.IGNORECASE)
    return _films.make(
        _SOURCE,
        movie["title"],
        url=f"{_SITE}/sv/filmer/{movie['slug']}",
        poster_url=_poster_url(movie.get("ogImageUrl") or movie.get("posterPath") or ""),
        overview=(movie.get("synopsis") or "").strip(),
        runtime=movie.get("duration") or None,
        genres=list(movie.get("genres") or []),
        release_date=_release_date(movie),
        original_languages=frozenset() if dubbed else _version.languages(language),
    )


def _release_date(movie: dict) -> str:
    """releaseDate where it falls in releaseYear; it is otherwise a Swedish premiere or booking date."""
    year = str(movie.get("releaseYear") or "")
    full = movie.get("releaseDate") or ""
    return full if year and full[:4] == year else year


def _show_time(text: object) -> time | None:
    """Time from "13:15" or "13:15:00"."""
    m = _TIME.fullmatch(text.strip()) if isinstance(text, str) else None
    try:
        return time(int(m.group(1)), int(m.group(2))) if m else None
    except ValueError:
        return None


def _show_date(text: object) -> date | None:
    try:
        return date.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        return None


def _valid(show: dict) -> bool:
    """Whether a showtime carries what a screening needs; warns when it does not."""
    movie = show.get("movie")
    if (
        isinstance(movie, dict)
        and movie.get("title")
        and movie.get("slug")
        and show.get("movieId") is not None
        and _show_time(show.get("time"))
        and _show_date(show.get("date"))
    ):
        return True
    log.warning("biorio.se: skipping malformed showtime %s", show.get("id"))
    return False


def _screening(show: dict, *, tmdb_id: int | None, film_key: str) -> Screening:
    fmt = " ".join(label for flag, label in (("is3D", "3D"), ("isImax", "IMAX")) if show.get(flag))
    return Screening(
        tmdb_id=tmdb_id,
        title=show["movie"]["title"].strip(),
        date=_show_date(show["date"]),
        time=_show_time(show["time"]),
        ticket_url=f"{_SITE}/sv/boka/{show['id']}",
        cinema_name=_CINEMA,
        city=_CITY,
        screen=(show.get("screen") or {}).get("name", ""),
        **_version.screening_facts(
            format=fmt,
            language=_label(show.get("audio")),
            subtitles=_label(show.get("subtitles")),
            raw_attributes=tuple(show.get("tags") or ()),
        ),
        film_key=film_key,
    )


def _tmdb_id(movie: dict) -> int | None:
    """The site's own TMDB id where it resolves, else a title lookup; none for a multi-film programme."""
    if _MULTI_FILM.search(movie["title"]):
        return None
    raw = str(movie.get("tmdbId") or "")
    if raw.isdigit() and (tmdb_id := _tmdb_by_id(int(raw))) is not None:
        return tmdb_id
    return _tmdb(movie["title"].strip())


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = _http.session()

    # Members-only shows are not sold to the public.
    shows = [
        s
        for s in _get_json(session, _SHOWTIMES_URL)["showtimes"]
        if not s.get("membersOnly") and not _CANCELLED.search(s.get("status") or "") and _valid(s)
    ]

    films: dict[int, tuple[Film, int | None]] = {}
    for show in shows:
        movie_id = show["movieId"]
        if movie_id not in films:
            movie = show["movie"] | _details(session, show["movie"]["slug"])
            film = _films.register(_film(movie), session=session)
            films[movie_id] = (film, _tmdb_id(movie))
            yield film

    for show in shows:
        film, tmdb_id = films[show["movieId"]]
        yield _screening(show, tmdb_id=tmdb_id, film_key=film.key)

    log.info("biorio.se: %d screenings, %d films", len(shows), len(films))


def _get_json(session: requests.Session, url: str) -> dict:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _details(session: requests.Session, slug: str) -> dict:
    """Release date and TMDB id, which only the movie endpoint carries."""
    try:
        return _get_json(session, f"{_API}/movies/{slug}").get("movie") or {}
    except requests.RequestException as exc:
        log.warning("biorio.se: movie %s failed: %s", slug, exc)
        return {}
