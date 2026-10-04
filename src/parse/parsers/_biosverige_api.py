"""BioSverige (Videvox Cinecore) schedule API shared by its cinema sites."""

import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import requests

from parse import _version
from parse.parsers import _tickster
from parse.parsers._tmdb_cache import lookup as _tmdb

log = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Stockholm")

# The CDN fits the image inside the box it is given; posters are portrait.
_POSTER_BOX = "?resize=600x900"

# "Tony (Sv.Txt) (Eng.Tal)", "Bortglömda ön (Sv.Txt) (Sv. Tal)"
_TAG = re.compile(r"\(\s*(\w+)\s*\.\s*(Txt|Tal)\s*\)", re.IGNORECASE)
_PARENS = re.compile(r"\([^)]*\)?")
# Tickster cuts titles at 50 characters, mid-word or mid-tag.
_LIMIT = 50
_CUT = 45


def schedule(session: requests.Session, site: str) -> list[dict]:
    """Upcoming showings at *site*; empty when the API fails."""
    # Without the range parameters the API returns only today's showings.
    params = {"StartDate": datetime.now(_TZ).date().isoformat(), "Limit": 500, "Months": 12, "Days": 365}
    try:
        resp = session.get(f"{site}/api/eventschedules", params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("biosverige: %s failed: %s", site, exc)
        return []
    if not isinstance(rows, list):
        log.warning("biosverige: %s answered %.200r", site, rows)
        return []
    return rows


def parse_title(raw: str) -> tuple[str, str, str]:
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


def showtimes(items: list[dict]) -> Iterator[tuple[str, date, time, str, str, str, dict, str]]:
    """Yield (title, date, time, screen, language, subtitles, movie, booking_url) per schedule row."""
    for item in items:
        if item.get("deleted"):
            continue
        try:
            dt = datetime.fromisoformat(item.get("startDate") or "")
        except ValueError:
            continue

        title, language, subtitles = parse_title(item.get("eventName") or "")
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


def film_details(data: dict) -> dict:
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


def tmdb_id(title: str, movie: dict) -> int | None:
    """TMDB id by title and runtime, then title alone, then original title and runtime."""
    runtime = movie.get("duration") or None
    original = movie.get("originalName") or ""
    return (
        _tmdb(title, runtime=runtime)
        or _tmdb(title)
        or (_tmdb(original, runtime=runtime) if original and original != title else None)
    )


def _cut(ticket_title: str) -> bool:
    """*ticket_title* may have lost trailing tags to Tickster's title limit."""
    if len(ticket_title) >= _LIMIT:
        return True
    return len(ticket_title) >= _CUT and not ticket_title.endswith(")")


def ticket_version(ticket_title: str, language: str, subtitles: str) -> tuple[str, str]:
    """(language, subtitles), preferring the Tickster title's tags over the schedule's.

    Tickster tags subtitled showings "(Sv. txt)" or "(Text: Svenska)"; one tagged only
    "(Sv. tal)" is unsubtitled, unless the title is cut and the subtitle tag lost.
    """
    _, spoken, subs = _tickster.version(ticket_title)
    if not spoken and not subs:
        return language, subtitles
    if not subs and _cut(ticket_title):
        return spoken or language, subtitles
    return spoken or language, subs or _version.NO_SUBTITLES


def ticket_labels(title: str, ticket_title: str) -> tuple[str, ...]:
    """Tickster programme tags: "(Dagbio)", or words trailing the title: "Spa Weekend STICKBIO"."""
    labels = _tickster.labels(ticket_title)
    if _cut(ticket_title):
        return labels
    rest = " ".join(_PARENS.sub(" ", _tickster.version(ticket_title)[0]).split())
    if not rest.casefold().startswith(title.casefold()) or rest[len(title) : len(title) + 1].isalnum():
        return labels
    extra = rest[len(title) :].strip(" -–:")
    return (*labels, extra) if extra else labels


def showing(
    programme: _tickster.Programme, title: str, day: date, start: time, language: str, subtitles: str
) -> tuple[_tickster.Event | None, str, str, tuple[str, ...]]:
    """(event, language, subtitles, labels) for a showing, with Tickster's tags when it lists it."""
    event = programme.find(title, day, start)
    if event is None:
        return None, language, subtitles, ()
    return event, *ticket_version(event.title, language, subtitles), ticket_labels(title, event.title)
