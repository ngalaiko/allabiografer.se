"""filmstaden.se — cinema-api.com REST API, all cinemas in one pass."""

import logging
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from allabiografer import normalize as _version
from allabiografer.model import Film, Screening, title_key
from allabiografer.sources import _films

log = logging.getLogger(__name__)

_API = "https://services.cinema-api.com"
_SOURCE = "filmstaden_se"

# Poster URLs carry a width parameter; the catalog serves any width on demand.
_POSTER_WIDTH = 800


# Programme labels appended to film titles: "Goodfellas - Klassiker", "Fjord - med samtal på Victoria",
# "Paraplyerna i Cherbourg- Everdahl & Karlssons Filmklubb", "The Conjuring - Maraton".
_TITLE_SUFFIX = re.compile(r"\s*-\s+(klassiker|maraton|med samtal\b.*|[^-]*filmklubb)$", re.IGNORECASE)
# Catalogue junk trailing titles: "Seventeen World Tour NEW_".
_TITLE_JUNK = re.compile(r"\s*\bNEW_+$")
# Status notes in cinema names: "Filmstaden Söder (Tillfälligt stängd)".
_CINEMA_STATUS = re.compile(r"\s*\([^)]*\)$")

# Labels that override the version's subtitle language.
_SUBTITLE_ATTRIBUTES = {"English subtitles": "Engelska"}

# Programme labels in version titles: "Arkipelag - Q&A med Alex Schulman…", "Fjord - pensionärsbio".
# Other segments name formats or venues ("- IMAX", "- Drömland").
_VERSION_PROGRAMME = re.compile(r"q&a|besök|pensionärsbio|stickbio|smygpremiär|samtal|maraton", re.IGNORECASE)

# Genre labels that classify nothing.
_NOISE_GENRES = {"FLC"}
# Catalogue categories that name a genre.
_CATEGORY_GENRES = {"Barn och Familj": "Familj"}


def _title(raw: str) -> tuple[str, str]:
    """(film title, programme suffix) from an API title."""
    title = _TITLE_JUNK.sub("", " ".join(raw.split()))
    m = _TITLE_SUFFIX.search(title)
    return (title[: m.start()].strip(), m.group(1)) if m else (title, "")


def _version_programmes(title: str) -> tuple[str, ...]:
    """Programme labels among a version title's dash-separated segments."""
    return tuple(part for part in re.split(r"\s+-\s+", title.strip())[1:] if _VERSION_PROGRAMME.search(part))


def _unique(*labels: str) -> tuple[str, ...]:
    """Non-empty labels in order, whitespace collapsed, the first spelling of each regardless of case."""
    first: dict[str, str] = {}
    for label in (" ".join(raw.split()) for raw in labels):
        if label:
            first.setdefault(label.casefold(), label)
    return tuple(first.values())


def _screening(
    show: dict[str, Any], *, tmdb_id: int | None, cinema_name: str, city: str, film_key: str = ""
) -> Screening:
    """Map one API show onto a Screening."""
    dt = datetime.fromisoformat(show["time"])
    attrs = show.get("attributes") or []
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
        screen=(show.get("screen") or {}).get("title") or "",
        **_version.screening_facts(
            format=", ".join(attr_names),
            language=audio_text,
            subtitles=subtitle_text,
            audio_role_text=audio_role_text,
            source_texts=_version.title_suffixes(title),
            raw_attributes=_unique(
                *attr_names,
                programme,
                *_version_programmes(title),
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
    genres = [g["name"] for g in movie.get("genres") or [] if g.get("name") and g["name"] not in _NOISE_GENRES]
    for category in movie.get("categories") or []:
        genre = _CATEGORY_GENRES.get(category.get("displayName") or "")
        if genre and genre not in genres:
            genres.append(genre)
    return _films.make(
        _SOURCE,
        title,
        title_original="" if title_key(original) == title_key(title) else original,
        overview=_overview(detail),
        runtime=movie.get("length") or None,
        genres=genres,
        release_date=_release_date(movie.get("releaseDate"), detail.get("productionYear")),
        age_rating=(movie.get("rating") or {}).get("displayName") or "",
        poster_url=_poster_url(movie),
        url=f"https://www.filmstaden.se/film/{slug}/" if slug else "",
        original_languages=_original_languages(detail),
    )
