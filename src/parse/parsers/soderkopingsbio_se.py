"""soderkopingsbio.se — BioSverige schedule API; tickets per showing on Tickster."""

import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from parse import _http, _version
from parse.parsers import _films, _tickster
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "soderkopingsbio_se"
_SCHEDULE = "https://soderkopingsbio.se/api/eventschedules"
_MOVIE_PAGE = "https://soderkopingsbio.se/filmer/"
_TICKSTER = "https://www.tickster.com/se/sv/events/by/f1rd9l09v0b7xdv/soderkopings-bio"
# The Tickster "PROGRAM" event the site links every showing to.
_TICKETS = "https://secure.tickster.com/d8fnyrrcl72fv8p"
_CINEMA = "Söderköpings Bio"
_CITY = "Söderköping"
_ADDRESS = "Ringvägen 45 A"
_TZ = ZoneInfo("Europe/Stockholm")

# The CDN fits the image inside the box it is given; posters are portrait.
_POSTER_BOX = "?resize=600x900"

# "Tony (Sv.Txt) (Eng.Tal)", "Superhunden Charlie (Sv.Txt) (Sv. Tal)"
_TAG = re.compile(r"\(\s*(\w+)\s*\.\s*(Txt|Tal)\s*\)", re.IGNORECASE)


def _parse_title(raw: str) -> tuple[str, str, str]:
    """Split a raw title into (title, language, subtitles).

    Audio and subtitle language ride along in trailing ``(Sv.Txt) (Eng.Tal)``
    tags; unknown language codes are dropped rather than guessed.
    """
    language = ""
    subtitles = ""
    for code, kind in _TAG.findall(raw):
        if not _version.languages(code):
            continue
        if kind.lower() == "tal":
            language = _version.language(code)
        else:
            subtitles = _version.subtitles(code)

    return _TAG.sub("", raw).strip(), language, subtitles


def _showtimes(items: list[dict]) -> Iterator[tuple[str, date, time, str, str, str, dict, str]]:
    """Yield (title, date, time, screen, language, subtitles, movie, booking_url) per schedule row."""
    for item in items:
        try:
            dt = datetime.fromisoformat(item.get("startDate") or "")
        except ValueError:
            continue

        title, language, subtitles = _parse_title(item.get("eventName") or "")
        if not title:
            continue

        yield (
            title,
            dt.date(),
            dt.time(),
            item.get("venueName") or "",
            language,
            subtitles,
            item.get("movie") or {},
            item.get("bookingUrl") or "",
        )


def _film_details(data: dict) -> dict:
    """Poster, synopsis, runtime, age rating, original title and premiere date."""
    poster = data.get("poster") or ""
    duration = data.get("duration") or 0
    original = data.get("originalName") or ""
    genre = data.get("genre") or ""

    return {
        "poster_url": f"{poster}{_POSTER_BOX}" if poster else "",
        "overview": (data.get("description") or "").strip(),
        "runtime": duration or None,
        "genres": [g.strip() for g in genre.split(",") if g.strip()],
        "age_rating": data.get("rating") or "",
        "title_original": original,
        "release_date": (data.get("releaseDate") or "")[:10],
    }


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    session = _http.session()
    # Without the range parameters the API returns only today's showings.
    params = {"StartDate": datetime.now(_TZ).date().isoformat(), "Limit": 500, "Months": 12, "Days": 365}
    resp = session.get(_SCHEDULE, params=params, timeout=30)
    resp.raise_for_status()
    showtimes = list(_showtimes(resp.json()))

    programme = _tickster.Programme.fetch(_TICKSTER, session)

    films: dict[str, Film] = {}
    for title, d, t, screen, language, subtitles, movie, booking_url in showtimes:
        film = films.get(title)
        if film is None:
            slug = movie.get("slug") or ""
            film = _films.make(
                _SOURCE, title, url=_MOVIE_PAGE + slug if slug else "", **(_film_details(movie) if movie else {})
            )
            film = films[title] = _films.register(film, session=session)
            yield film

        event = programme.find(title, d, t)
        yield Screening(
            tmdb_id=_tmdb(title),
            title=title,
            date=d,
            time=t,
            ticket_url=booking_url or (event.url if event else _TICKETS),
            cinema_name=_CINEMA,
            city=_CITY,
            screen=screen,
            **_version.screening_facts(language=language, subtitles=subtitles),
            film_key=film.key,
        )
