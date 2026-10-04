"""osbyborgen.se — Tickster Vue.js with vueData_sessions JSON in HTML."""

import html
import json
import re
from collections.abc import Iterator
from datetime import date, time

from parse import _http, _version
from parse._util import infer_year
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

_SOURCE = "osbyborgen_se"
_URL = "https://osbyborgen.se/"
_CINEMA = "Bio Borgen"
_CITY = "Osby"
_ADDRESS = "Västra Storgatan"

# Tickster event types: 1 "Filmer", 2 "Evenemang" (live shows).
_LIVE_EVENT = 2
# "dagbio<br>på spanska" — spoken language.
_LABEL_LANGUAGE = re.compile(r"\bpå\s+([^\W\d_]+)", re.IGNORECASE)
# "Ny tid kl 14.00" — a schedule change, already reflected in the session time.
_SCHEDULE_NOTE = re.compile(r"^ny tid\b", re.IGNORECASE)
# Distributor contact paragraphs that follow the synopsis.
_CONTACT = re.compile(r"pressansvarig|distributionsansvarig|pressbilder|\S+@\S+\.\w+|\b0\d{1,3}-\d", re.IGNORECASE)
# The site's catch-all category.
_NOT_A_GENRE = {"film"}

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
    """Film session records from the vueData_sessions blob; live events are left out."""
    m = re.search(r'vueData_sessions\s*=\s*(\{.*?"sessions":\[.*?\]\})', page, re.DOTALL)
    if not m:
        raise ValueError("osbyborgen.se: no schedule found")
    return [s for s in json.loads(m.group(1)).get("sessions", []) if s.get("f_event_type_id") != _LIVE_EVENT]


def _detail(page: str) -> dict:
    """Film record from a film page's vueData_film blob."""
    m = re.search(r'vueData_film\s*=\s*(\{.*?"isProdApiMode":\s*\w+\})', page, re.DOTALL)
    return json.loads(m.group(1)).get("film", {}) if m else {}


def _text(raw: object) -> str:
    """Plain text from an HTML field."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(raw or ""))).split())


def _overview(raw: object) -> str:
    """Synopsis paragraphs, separated by blank lines, up to the distributor contacts."""
    paragraphs: list[str] = []
    for part in re.split(r"</p\s*>|<p\b[^>]*>", str(raw or ""), flags=re.IGNORECASE):
        text = _text(part)
        if _CONTACT.search(text):
            break
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _genre(raw: str) -> str:
    """ "Spanskt drama" is a drama; the nationality is not a genre."""
    words = raw.split()
    if len(words) > 1 and _version.languages(words[0]):
        words = words[1:]
    genre = " ".join(words).capitalize()
    return "" if genre.lower() in _NOT_A_GENRE else genre


def _runtime(raw: object) -> int | None:
    """Minutes from a "1 tim 21", "2 h inkl p", "105 min" or "2:10" length."""
    text = str(raw or "").strip().lower()
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if not nums:
        return None
    if len(nums) > 1 or re.search(r"\d\s*(?:tim|h\b)", text) or ":" in text:
        minutes = nums[0] * 60 + (nums[1] if len(nums) > 1 else 0)
    else:
        minutes = nums[0]
    return minutes or None


def _label_facts(raw: object, film_label: object = "") -> dict[str, object]:
    """Screening version fields from a session label: "på svenska", "dagbio<br>på spanska".

    The film page's label supplies the language when the session's holds none.
    """
    label = _text(raw)
    m = _LABEL_LANGUAGE.search(label) or _LABEL_LANGUAGE.search(_text(film_label))
    return _version.screening_facts(
        language=_version.language(m.group(1)) if m else "",
        raw_attributes=(label,) if label and not _SCHEDULE_NOTE.match(label) else (),
    )


def _film_url(film_id: int | str) -> str:
    return f"{_URL}?pg=6&film={film_id}"


def _film(sess: dict, detail: dict) -> Film:
    """Film metadata from a session record and its film page."""
    genre = detail.get("f_genre") or sess.get("f_genre") or ""
    genres = [g for g in (_genre(part) for part in genre.split(",")) if g]
    return _films.make(
        _SOURCE,
        " ".join(sess.get("f_title", "").split()),
        overview=_overview(detail.get("f_synopsis", "")),
        runtime=_runtime(detail.get("f_run_time", "")),
        genres=genres,
        age_rating=str(detail.get("f_rating") or ""),
        poster_url=detail.get("f_graphic_url") or sess.get("f_graphic_url") or "",
        url=_film_url(sess.get("f_id", "")),
    )


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = _http.session("Mozilla/5.0")
    resp = session.get(_URL, timeout=12)
    resp.raise_for_status()

    films: dict[str, Film] = {}
    labels: dict[str, str] = {}
    for sess in _sessions(resp.text):
        film_title = " ".join(sess.get("f_title", "").split())
        t = _parse_time(sess.get("f_time", ""))
        d = _parse_date(sess.get("f_date", ""))
        ticket_url = sess.get("f_href", "")
        if not film_title or not t or not d or not ticket_url:
            continue

        film = films.get(film_title)
        if film is None:
            resp = session.get(_film_url(sess.get("f_id", "")), timeout=12)
            detail = _detail(resp.text) if resp.ok else {}
            film = _film(sess, detail)
            films[film_title] = film
            labels[film_title] = detail.get("f_label") or ""
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
            **_label_facts(sess.get("f_label"), labels[film_title]),
        )
