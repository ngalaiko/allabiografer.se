"""soderkopingsbio.se — BioSverige program list, rendered client-side via Playwright."""

import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parse.parsers import _films
from parse.parsers._browser import page as browser_page
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "soderkopingsbio_se"
_URL = "https://soderkopingsbio.se/program"
_MOVIE_API = "https://soderkopingsbio.se/api/movies/slug/"
_MOVIE_PAGE = "https://soderkopingsbio.se/filmer/"
_CINEMA = "Söderköpings Bio"
_CITY = "Söderköping"
_ADDRESS = "Ringvägen 45"

# The CDN fits the image inside the box it is given; posters are portrait.
_POSTER_BOX = "?resize=600x900"


_LANGUAGES = {"sv": "Svenska", "eng": "Engelska"}

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
        name = _LANGUAGES.get(code.lower(), "")
        if not name:
            continue
        if kind.lower() == "tal":
            language = name
        else:
            subtitles = name

    return _TAG.sub("", raw).strip(), language, subtitles


def _showtimes(html: str) -> Iterator[tuple[str, date, time, str, str, str, str]]:
    """Yield (title, date, time, ticket_url, screen, language, subtitles)."""
    soup = BeautifulSoup(html, "html.parser")

    for row in soup.select(".program-list__row"):
        stamp = row.select_one("time[datetime]")
        title_el = row.select_one("h3.program__title")
        ticket = row.select_one(".program__actions a.btn-primary")
        if not stamp or not title_el or not ticket:
            continue

        try:
            dt = datetime.fromisoformat(stamp["datetime"])
        except ValueError:
            continue

        title, language, subtitles = _parse_title(title_el.get_text(strip=True))
        if not title:
            continue

        meta = [li.get_text(strip=True) for li in row.select("ul.program__meta li")]
        screen = next((m for m in meta if m.startswith("Sal")), "")

        yield title, dt.date(), dt.time(), urljoin(_URL, ticket.get("href", "")), screen, language, subtitles


def _film_slugs(html: str) -> dict[str, str]:
    """Map each title to the movie slug its "Läs mer" link ends in."""
    soup = BeautifulSoup(html, "html.parser")
    slugs: dict[str, str] = {}
    for row in soup.select(".program-list__row"):
        link = row.select_one("h3.program__title a[href]")
        if not link:
            continue
        title, _, _ = _parse_title(link.get_text(strip=True))
        slug = link["href"].rsplit("/", 1)[-1]
        if title and slug:
            slugs.setdefault(title, slug)
    return slugs


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
        "age_rating": _age_rating(data.get("rating") or ""),
        "title_original": original,
        "release_date": (data.get("releaseDate") or "")[:10],
    }


def _age_rating(text: str) -> str:
    """'Barntillåten' and '11 år' in the site's wording; 'Ej granskad' is no rating."""
    if text.casefold().startswith("barntillåten"):
        return "BTL"
    m = re.match(r"(\d+)\s*år", text)
    return m.group(1) if m else ""


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    with browser_page() as page:
        page.goto(_URL, wait_until="networkidle", timeout=30000)
        html = page.content()

    session = requests.Session()

    films: dict[str, Film] = {}
    for title, slug in _film_slugs(html).items():
        details = _details(session, _MOVIE_API + slug)
        film = _films.make(_SOURCE, title, url=_MOVIE_PAGE + slug, **details)
        films[title] = _films.register(film, session=session)
        yield films[title]

    for title, d, t, ticket_url, screen, language, subtitles in _showtimes(html):
        film = films.get(title)
        yield Screening(
            tmdb_id=_tmdb(title),
            title=title,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=_CINEMA,
            city=_CITY,
            screen=screen,
            language=language,
            subtitles=subtitles,
            film_key=film.key if film else "",
        )


def _details(session: requests.Session, url: str) -> dict:
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return _film_details(resp.json())
    except (requests.RequestException, ValueError) as exc:
        log.warning("soderkopingsbio.se: movie %s failed: %s", url, exc)
        return {}
