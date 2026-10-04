"""filmstaden.se — cinema-api.com REST API, all cinemas in one pass."""

import logging
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue, film_key

log = logging.getLogger(__name__)

_API = "https://services.cinema-api.com"
_SOURCE = "filmstaden_se"

# Poster URLs carry a width parameter; the catalog serves any width on demand.
_POSTER_WIDTH = 800

# The image CDN serves posters only to browser user agents.
_POSTER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# Programme labels appended to film titles: "Goodfellas - Klassiker", "Fjord - med samtal på Victoria",
# "Paraplyerna i Cherbourg- Everdahl & Karlssons Filmklubb".
_TITLE_SUFFIX = re.compile(r"\s*-\s+(klassiker|med samtal\b.*|[^-]*filmklubb)$", re.IGNORECASE)

# Labels that override the version's subtitle language.
_SUBTITLE_ATTRIBUTES = {"English subtitles": "Engelska"}


def _title(raw: str) -> tuple[str, str]:
    """(film title, programme suffix) from an API title."""
    title = raw.strip()
    m = _TITLE_SUFFIX.search(title)
    return (title[: m.start()].strip(), m.group(1)) if m else (title, "")


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
    version_attrs = version.get("attributes") or []
    attr_names = tuple(
        dict.fromkeys(a.get("displayName") or "" for a in (*attrs, *version_attrs) if a.get("displayName"))
    )
    audio_languages = version.get("audioLanguages") or []
    audio_info = version.get("audioLanguageInfo") or {}
    audio_text = (
        ", ".join(item.get("displayName") or item.get("alias") or "" for item in audio_languages).strip(", ")
        or audio_info.get("displayName")
        or audio_info.get("alias", "")
    )
    audio_role_text = ", ".join(item.get("description") or "" for item in audio_languages)
    audio_role_text = audio_role_text or audio_info.get("description", "")
    subtitles = version.get("subtitlesLanguageInfo") or {}
    subtitle_text = next(
        (_SUBTITLE_ATTRIBUTES[name] for name in attr_names if name in _SUBTITLE_ATTRIBUTES),
        subtitles.get("displayName") or subtitles.get("alias") or subtitles.get("description", ""),
    )
    title = version.get("title") or ""
    film_title, programme = _title(show["movie"]["title"])
    return Screening(
        tmdb_id=tmdb_id,
        film_key=film_key,
        title=film_title,
        date=dt.date(),
        time=dt.time(),
        cinema_name=cinema_name,
        city=city,
        screen=show.get("screen", {}).get("title", ""),
        **_version.screening_facts(
            format=", ".join(attr_names),
            language=audio_text,
            subtitles=subtitle_text,
            audio_role_text=audio_role_text,
            source_texts=_version.title_suffixes(title),
            raw_attributes=(
                *attr_names,
                programme,
                *(item.get("description") or "" for item in audio_languages),
                *(item.get("displayName") or "" for item in audio_languages),
                audio_info.get("description", ""),
                subtitles.get("description", ""),
                subtitles.get("displayName", "") or subtitles.get("alias", ""),
            ),
        ),
        ticket_url=f"https://www.filmstaden.se/bokning/kop/{show.get('remoteEntityId', '')}/",
    )


def _poster_url(movie: dict[str, Any]) -> str:
    """Poster image resized to a display-friendly width."""
    url = next(
        (i.get("url", "") for i in movie.get("images") or [] if i.get("imageType") == "Poster"),
        movie.get("posterUrl") or "",
    )
    return re.sub(r"(?<=[?&])w=\d+", f"w={_POSTER_WIDTH}", url) if url else ""


def _release_date(raw: str | None, production_year: int | None = None) -> str:
    """ISO date from an API timestamp, empty for the 0001-01-01 placeholder.

    Re-releases of older films carry the production year instead.
    """
    day = (raw or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day.startswith("0001"):
        day = ""
    if production_year and (not day or int(day[:4]) - production_year > 2):
        return str(production_year)
    return day


def _overview(detail: dict[str, Any]) -> str:
    """Long description as plain text, else the short one."""
    long = BeautifulSoup(detail.get("longDescription") or "", "html.parser").get_text(" ")
    return " ".join(long.split()) or (detail.get("shortDescription") or "").strip()


def _original_languages(detail: dict[str, Any]) -> frozenset:
    """Original languages from the detail's language list, else its single language code."""
    names = [
        item.get("displayName") or (item.get("alias") or "").split("-")[0]
        for item in detail.get("originalLanguages") or []
    ]
    names = names or [(detail.get("originalLanguage") or "").split("-")[0]]
    return _version.languages(", ".join(n for n in names if n))


def _film(movie: dict[str, Any], detail: dict[str, Any] | None = None) -> Film:
    """Film metadata from a show's movie object, enriched with its detail payload."""
    detail = detail or {}
    title, _ = _title(movie["title"])
    original, _ = _title(detail.get("originalTitle") or "")
    slug = movie.get("slug") or ""
    return _films.make(
        _SOURCE,
        title,
        title_original="" if original == title else original,
        overview=_overview(detail),
        runtime=movie.get("length") or None,
        genres=[g["name"] for g in movie.get("genres") or [] if g.get("name")],
        release_date=_release_date(movie.get("releaseDate"), detail.get("productionYear")),
        age_rating=(movie.get("rating") or {}).get("displayName") or "",
        poster_url=_poster_url(movie),
        url=f"https://www.filmstaden.se/film/{slug}/" if slug else "",
        original_languages=_original_languages(detail),
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
    posters = _http.session(_POSTER_UA)
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
            film_title, _ = _title(movie.get("title", ""))
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
