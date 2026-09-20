"""osbyborgen.se — Tickster Vue.js with vueData_sessions JSON in HTML."""

import html
import json
import re
from collections.abc import Iterator
from datetime import date, time

import requests

from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

_SOURCE = "osbyborgen_se"
_URL = "https://osbyborgen.se/"
_CINEMA = "Bio Borgen"
_CITY = "Osby"
_ADDRESS = "Västra Storgatan"

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "maj": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}

# Ratings the site uses for "not stated".
_NO_RATING = {"", "-", "ej angivet"}


def _parse_date(text: str) -> date | None:
    m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)", text.strip().lower())
    if not m:
        return None
    day, mon = int(m.group(1)), _MONTHS.get(m.group(2))
    return date(infer_year(mon), mon, day) if mon else None


def _parse_time(text: str) -> time | None:
    m = re.match(r"(\d{1,2}):(\d{2})", text.strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _sessions(page: str) -> list[dict]:
    """Session records from the vueData_sessions blob."""
    m = re.search(r'vueData_sessions\s*=\s*(\{.*?"sessions":\[.*?\]\})', page, re.DOTALL)
    if not m:
        raise ValueError("osbyborgen.se: no schedule found")
    return json.loads(m.group(1)).get("sessions", [])


def _detail(page: str) -> dict:
    """Film record from a film page's vueData_film blob."""
    m = re.search(r'vueData_film\s*=\s*(\{.*?"isProdApiMode":\s*\w+\})', page, re.DOTALL)
    return json.loads(m.group(1)).get("film", {}) if m else {}


def _text(raw: object) -> str:
    """Plain text from an HTML field."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(raw or ""))).split())


def _runtime(raw: object) -> int | None:
    """Minutes from a "1 tim 21" or "2:10" length."""
    text = str(raw or "").strip()
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if not nums:
        return None
    if len(nums) > 1 or "tim" in text or ":" in text:
        minutes = nums[0] * 60 + (nums[1] if len(nums) > 1 else 0)
    else:
        minutes = nums[0]
    return minutes or None


def _age_rating(raw: object) -> str:
    text = " ".join(str(raw or "").split())
    return "" if text.lower() in _NO_RATING else text


def _film_url(film_id: int | str) -> str:
    return f"{_URL}?pg=6&film={film_id}"


def _film(sess: dict, detail: dict) -> Film:
    """Film metadata from a session record and its film page."""
    genre = detail.get("f_genre") or sess.get("f_genre") or ""
    genres = [g for g in (" ".join(part.split()).capitalize() for part in genre.split(",")) if g]
    return _films.make(
        _SOURCE,
        " ".join(sess.get("f_title", "").split()),
        overview=_text(detail.get("f_synopsis", "")),
        runtime=_runtime(detail.get("f_run_time", "")),
        genres=genres,
        age_rating=_age_rating(detail.get("f_rating", "")),
        poster_url=detail.get("f_graphic_url") or sess.get("f_graphic_url") or "",
        url=_film_url(sess.get("f_id", "")),
    )


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    resp = session.get(_URL, timeout=12)
    resp.raise_for_status()

    films: dict[str, Film] = {}
    for sess in _sessions(resp.text):
        film_title = " ".join(sess.get("f_title", "").split())
        t = _parse_time(sess.get("f_time", ""))
        d = _parse_date(sess.get("f_date", ""))
        ticket_url = sess.get("f_href", "")
        if not film_title or not t or not d or not ticket_url:
            continue

        film = films.get(film_title)
        if film is None:
            detail = session.get(_film_url(sess.get("f_id", "")), timeout=12)
            film = _film(sess, _detail(detail.text) if detail.ok else {})
            films[film_title] = film
            yield _films.register(film, session=session)

        yield Screening(
            tmdb_id=_tmdb(film_title),
            title=film_title,
            film_key=film.key,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=_CINEMA,
            city=_CITY,
        )
