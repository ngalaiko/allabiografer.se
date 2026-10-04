"""BioSverige (Videvox Cinecore) cinema sites — per-site schedule API."""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import requests

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "biosverige_se"
_TZ = ZoneInfo("Europe/Stockholm")

# The CDN fits the image inside the box it is given; posters are portrait.
_POSTER_BOX = "?resize=600x900"

# "Tony (Sv.Txt) (Eng.Tal)", "Bortglömda ön (Sv.Txt) (Sv. Tal)"
_TAG = re.compile(r"\(\s*(\w+)\s*\.\s*(Txt|Tal)\s*\)", re.IGNORECASE)


@dataclass(frozen=True)
class _Site:
    url: str
    name: str
    city: str
    address: str
    # The site's "@booking" setting: where its buy buttons lead.
    tickets: str


# Söderköping has its own parser; Vårgårda Rialto and Robertsfors are on bio.se.
_SITES = (
    _Site(
        "https://filipstad.biosverige.se",
        "Bio Monitor",
        "Filipstad",
        "Viktoriagatan 8",
        "https://secure.tickster.com/sv/y4vknkelzhvmpp6/",
    ),
    _Site(
        "https://jarpen.biosverige.se",
        "Järpen Bion",
        "Järpen",
        "Strandvägen 22",
        "https://www.tickster.com/se/sv/events/by/t93wpddl1nc93uz/jarpen-bion",
    ),
    _Site(
        "https://gislaved.biosverige.se",
        "Folkets Hus Gislaved",
        "Gislaved",
        "Danska vägen 6 A",
        "https://boka.folketshusgislaved.se/gislaved/resource/movies",
    ),
    _Site(
        "https://casablancabio.se",
        "Bio Casablanca",
        "Karlsborg",
        "Strandvägen 15",
        "https://secure.tickster.com/sv/eaukgpvmklav5gg",
    ),
    _Site(
        "https://mariannelundsbio.se",
        "Mariannelunds Bio",
        "Mariannelund",
        "Östra Storgatan 6",
        "https://secure.tickster.com/sv/fjnrhjm4dltbtfl",
    ),
)


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
    genre = data.get("genre") or ""

    return {
        "poster_url": f"{poster}{_POSTER_BOX}" if poster else "",
        "overview": (data.get("description") or "").strip(),
        "runtime": data.get("duration") or None,
        "genres": [g.strip() for g in genre.split(",") if g.strip()],
        "age_rating": data.get("rating") or "",
        "title_original": data.get("originalName") or "",
        "release_date": (data.get("releaseDate") or "")[:10],
    }


def _schedule(session: requests.Session, site: _Site) -> list[dict]:
    """The site's upcoming showings; empty when the API fails."""
    # Without the range parameters the API returns only today's showings.
    params = {"StartDate": datetime.now(_TZ).date().isoformat(), "Limit": 500, "Months": 12, "Days": 365}
    try:
        resp = session.get(f"{site.url}/api/eventschedules", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("biosverige: %s failed: %s", site.url, exc)
        return []


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()
    films: dict[str, Film] = {}

    for site in _SITES:
        yield Venue(name=site.name, city=site.city, address=site.address)

        for title, d, t, screen, language, subtitles, movie, booking_url in _showtimes(_schedule(session, site)):
            film = films.get(title)
            if film is None:
                slug = movie.get("slug") or ""
                film = _films.make(
                    _SOURCE,
                    title,
                    url=f"{site.url}/filmer/{slug}" if slug else "",
                    **(_film_details(movie) if movie else {}),
                )
                film = films[title] = _films.register(film, session=session)
                yield film

            yield Screening(
                tmdb_id=_tmdb(title),
                title=title,
                date=d,
                time=t,
                ticket_url=booking_url or site.tickets,
                cinema_name=site.name,
                city=site.city,
                screen=screen,
                **_version.screening_facts(language=language, subtitles=subtitles),
                film_key=film.key,
            )
