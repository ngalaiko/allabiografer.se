"""bio.se — JSON API, all cinemas in one pass."""

import html
import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time

import requests

from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "bio_se"
_SITE = "https://bio.se"
_API = f"{_SITE}/api"

# Ratings the API uses for "not stated".
_NO_RATING = {"", "-", "ej angivet"}


def _ticket_url(payment_link: str) -> str:
    """Build a ticket URL from the API's payment_link field."""
    if not payment_link:
        return ""
    if payment_link.startswith(("http://", "https://")):
        return payment_link
    return f"{_SITE}{payment_link}"


def _clean(text: str) -> str:
    """Decode HTML entities and collapse whitespace; API fields carry both."""
    return " ".join(html.unescape(text or "").split())


def _text(raw: str) -> str:
    """Plain text from a field whose markup arrives entity-escaped."""
    return _clean(re.sub(r"<[^>]+>", " ", html.unescape(raw or "")))


def _runtime(raw: str) -> int | None:
    """Minutes from the run_time field; zero and blanks mean unknown."""
    digits = _clean(raw)
    return int(digits) or None if digits.isdigit() else None


def _age_rating(raw: str) -> str:
    """Normalise the free-text rating; empty when the API states none."""
    text = _clean(raw)
    lowered = text.lower()
    if lowered in _NO_RATING:
        return ""
    if lowered.startswith(("bt", "barntill")):
        return "Barntillåten"
    m = re.fullmatch(r"(?:från\s*)?(\d+)\s*(?:\+|år)?", text, re.IGNORECASE)
    return f"Från {m.group(1)} år" if m else text


def _film(movie: dict) -> Film:
    """Film metadata from an API movie record."""
    genres = [g for g in (_clean(part) for part in (movie.get("genre") or "").split(",")) if g]
    return _films.make(
        _SOURCE,
        _clean(movie.get("title", "")),
        overview=_text(movie.get("synopsis", "")),
        runtime=_runtime(movie.get("run_time", "")),
        genres=genres,
        age_rating=_age_rating(movie.get("rating", "")),
        poster_url=_clean(movie.get("poster_url", "")),
        url=f"{_SITE}/movie/{movie['id']}" if movie.get("id") else "",
    )


def _venue(cinema: dict) -> Venue | None:
    """Venue for a cinema record, or None when the record carries no location."""
    name = _clean(cinema.get("title", ""))
    city = _clean(cinema.get("city", ""))
    address = _clean(cinema.get("street_address", ""))
    if not city and not address:
        return None
    return Venue(name=name, city=city or name.split()[0], address=address)


def _showtimes(payload: dict) -> Iterator[tuple[Film, date, time, str, str, str, str, str]]:
    """Yield (film, date, time, ticket_url, screen, format, language, subtitles) per session."""
    for entry in payload["movies"]:
        film = _film(entry.get("movie", {}))
        if not film.title:
            continue
        for sess in entry.get("sessions", []):
            raw = sess.get("show_date_time", "")
            if not raw:
                continue
            url = _ticket_url(sess.get("payment_link", ""))
            if not url:
                continue
            when = datetime.fromisoformat(raw)
            yield (
                film,
                when.date(),
                when.time(),
                url,
                _clean(sess.get("screen_name", "")),
                _clean(sess.get("format", "")),
                _clean(sess.get("language", "")),
                _clean(sess.get("text", "")),
            )


def parse() -> Iterator[Screening | Venue | Film]:
    seen: set[str] = set()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; bio-parser/1.0)", "Accept": "application/json"})

    resp = session.get(f"{_API}/cinemas", timeout=30)
    resp.raise_for_status()
    cinemas = resp.json()["cinemas"]
    log.info("bio.se: %d cinemas", len(cinemas))

    for cinema in cinemas:
        venue = _venue(cinema)
        if venue is None:
            log.info("  skipping %s: no city or address", cinema.get("title", ""))
            continue

        yield venue

        resp = session.post(f"{_API}/cinemas/films", json={"cinemaId": cinema["id"]}, timeout=15)
        resp.raise_for_status()

        count = 0
        for film, d, t, url, screen, fmt, language, subtitles in _showtimes(resp.json()):
            if film.key not in seen:
                seen.add(film.key)
                yield _films.register(film)
            yield Screening(
                tmdb_id=_tmdb(film.title),
                title=film.title,
                film_key=film.key,
                date=d,
                time=t,
                cinema_name=venue.name,
                city=venue.city,
                language=language,
                subtitles=subtitles,
                format=fmt,
                screen=screen,
                ticket_url=url,
            )
            count += 1

        if count:
            log.info("  %s (%s): %d screenings", venue.name, venue.city, count)
