"""TMDB movie lookup — metadata and the title index live in the db, posters in files.

Usage::

    from parse.tmdb import lookup

    # Returns TMDB ID if found, None otherwise.
    tmdb_id = lookup("Super Mario Galaxy Filmen", path=Path("data/allabiografer.db"))

Written through :mod:`store`::

    write_movie      — metadata (title, overview, genres, …)
    write_poster     — w500 poster image, a file in ``data/posters/``
    tmdb_index_set   — title key → tmdb id, to skip repeat searches
"""

import logging
import re
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urljoin

import requests

from parse import _http
from parse._rating import age_rating as _age_rating
from store import (
    DB_FILE,
    Movie,
    has_poster,
    read_movie,
    title_key,
    tmdb_index_get,
    tmdb_index_set,
    write_movie,
    write_poster,
)
from store.version import Language

log = logging.getLogger(__name__)

_API = "https://api.themoviedb.org/3"
_IMG_BASE = "https://image.tmdb.org/t/p/"
_API_KEY = "b692d29e51235ad793b851098f8edddf"
_POSTER_SIZE = "w500"

# Rate-limit: TMDB allows ~50 req/s, but be polite.
_MIN_INTERVAL = 0.05  # 20 req/s max
_last_request: float = 0.0


def _get(session: requests.Session, url: str, **params: str) -> dict:
    """GET with rate-limiting."""
    global _last_request
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _last_request)
    if wait > 0:
        time.sleep(wait)
    resp = session.get(url, params={"api_key": _API_KEY, **params}, timeout=15)
    _last_request = time.monotonic()
    resp.raise_for_status()
    return resp.json()


# Source titles that otherwise resolve to unrelated films or older adaptations.
_TITLE_HINTS = {
    "Flaggan": ("Flaggan", 2026),
    "Främlingen": ("Främlingen", 2025),
    "Sense and Sensibility": ("Sense and Sensibility", 2026),
    "My Favorite Things": ("My Favorite Things: The Rodgers & Hammerstein 80th Anniversary Concert", 2024),
}


def _clean_title(title: str) -> str:
    """Remove presentation labels without discarding subtitles or sequel names."""
    title = re.sub(
        r"^(?:(?:extravisning(?:\s*\(\d+\))?|premiär|höstlovsfilm|påsklovsfilm|favorit i repris)"
        r"[!:]?\s+)+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s*\((?:sv\.?|eng)\s*(?:tal|txt|text)\)\s*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+förfilm\s+.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r",\s*version:.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+(eng|sv\.?)\s+(tal|txt)\.?\s*$", "", title, flags=re.IGNORECASE)
    return title.strip()


def _content_type(header: str) -> str:
    """Normalise a response content-type to a supported poster type."""
    if "png" in header:
        return "image/png"
    if "webp" in header:
        return "image/webp"
    return "image/jpeg"


def _download_poster(session: requests.Session, poster_path: str, tmdb_id: int, path: Path) -> bool:
    """Download poster image and store it. Returns True on success."""
    url = urljoin(_IMG_BASE, f"{_POSTER_SIZE}{poster_path}")
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        log.warning("failed to download poster %s", url)
        return False

    write_poster(tmdb_id, resp.content, _content_type(resp.headers.get("content-type", "")), path=path)
    return True


def lookup(
    title: str,
    *,
    path: Path = DB_FILE,
    session: requests.Session | None = None,
    year: int | None = None,
    runtime: int | None = None,
) -> int | None:
    """Search TMDB for *title*, store metadata + poster. Returns TMDB ID or None.

    Skips the network call when the title index already resolves to a stored
    movie.  Every store call is its own short transaction, so no db lock is
    held across network calls; concurrent lookups of the same title are
    harmless because the writes are upserts.
    """
    own_session = session is None
    if own_session:
        session = _http.session()
    try:
        return _lookup(title, path, session, year, runtime)
    finally:
        if own_session:
            session.close()


def _lookup(
    title: str,
    path: Path,
    session: requests.Session,
    year: int | None,
    runtime: int | None,
) -> int | None:
    clean = _clean_title(title)
    if year is None and clean in _TITLE_HINTS:
        clean, year = _TITLE_HINTS[clean]

    # ------ index: title → tmdb_id (avoids re-searching) ------
    cache_key = f"{title_key(clean)}|{year or ''}|{runtime or ''}"
    cached = tmdb_index_get(cache_key, path=path)
    stored = read_movie(cached, path=path) if cached is not None else None
    if stored is not None:
        # Movies are fetched once; ratings stored before normalisation are fixed on read.
        if stored.age_rating != _age_rating(stored.age_rating):
            write_movie(replace(stored, age_rating=_age_rating(stored.age_rating)), path=path)
        if not stored.original_language:
            _fetch(cached, path, session)
        return cached

    # ------ search TMDB ------
    try:
        params: dict[str, str] = {"language": "sv-SE", "query": clean}
        if year:
            params["year"] = str(year)
        data = _get(session, f"{_API}/search/movie", **params)
    except requests.RequestException:
        log.warning("TMDB search failed for %r", clean)
        return None

    results = data.get("results", [])
    if not results:
        log.debug("no TMDB results for %r (cleaned from %r)", clean, title)
        return None

    candidates = {
        result["id"]: result
        for result in results
        if title_key(clean) in {title_key(result.get("title", "")), title_key(result.get("original_title", ""))}
        and (year is None or result.get("release_date", "").startswith(str(year)))
    }
    if runtime and candidates:
        compatible = {}
        for candidate_id, candidate in candidates.items():
            stored = read_movie(candidate_id, path=path)
            length = stored.runtime if stored else None
            if not length:
                try:
                    length = _get(session, f"{_API}/movie/{candidate_id}", language="sv-SE").get("runtime")
                except requests.RequestException:
                    return None
            if (length and abs(length - runtime) <= 5) or (not length and len(candidates) == 1):
                compatible[candidate_id] = candidate
        candidates = compatible
    if len(candidates) != 1:
        log.info("ambiguous or inexact TMDB match for %r; keeping source title", title)
        return None
    tmdb_id: int = next(iter(candidates.values()))["id"]
    if not _fetch(tmdb_id, path, session):
        return None

    # ------ update index ------
    tmdb_index_set(cache_key, tmdb_id, path=path)

    return tmdb_id


def by_id(tmdb_id: int, *, path: Path = DB_FILE, session: requests.Session | None = None) -> int | None:
    """Store metadata + poster for a TMDB id a site states. Returns the id, or None when the fetch fails."""
    stored = read_movie(tmdb_id, path=path)
    if stored is not None and stored.original_language:
        return tmdb_id
    own_session = session is None
    if own_session:
        session = _http.session()
    try:
        return tmdb_id if _fetch(tmdb_id, path, session) or stored is not None else None
    finally:
        if own_session:
            session.close()


def _fetch(tmdb_id: int, path: Path, session: requests.Session) -> bool:
    """Fetch details for *tmdb_id*, store the movie and its poster.  False when the fetch fails."""
    # ------ fetch full details ------
    try:
        details = _get(
            session,
            f"{_API}/movie/{tmdb_id}",
            language="sv-SE",
            append_to_response="release_dates",
        )
    except requests.RequestException:
        log.warning("TMDB details fetch failed for id=%d", tmdb_id)
        return False

    # Extract Swedish age rating and release date from release_dates
    age_rating = ""
    release_date_se = ""
    for country in details.get("release_dates", {}).get("results", []):
        if country.get("iso_3166_1") == "SE":
            for entry in country.get("release_dates", []):
                cert = entry.get("certification", "")
                if cert and not age_rating:
                    age_rating = _age_rating(cert)
                # Prefer theatrical (type 3), then limited (2), then premiere (1)
                rd = entry.get("release_date", "")
                rtype = entry.get("type", 0)
                if (rd and rtype == 3) or (rd and rtype in (1, 2) and not release_date_se):
                    release_date_se = rd[:10]
            break

    movie = Movie(
        tmdb_id=tmdb_id,
        title_sv=details.get("title", ""),
        title_original=details.get("original_title", ""),
        overview_sv=details.get("overview", ""),
        genres=[g["name"] for g in details.get("genres", [])],
        release_date=details.get("release_date", ""),
        release_date_se=release_date_se,
        runtime=details.get("runtime"),
        poster_path=details.get("poster_path") or "",
        vote_average=details.get("vote_average"),
        age_rating=age_rating,
        original_language=details.get("original_language") or "",
    )
    write_movie(movie, path=path)

    # ------ poster ------
    if movie.poster_path and not has_poster(tmdb_id, path=path):
        _download_poster(session, movie.poster_path, tmdb_id, path)

    log.info("TMDB %d: %s", tmdb_id, movie.title_sv or movie.title_original)
    return True


# TMDB original_language codes (ISO 639-1; "cn" is TMDB's Cantonese).
_LANGUAGES = {
    "sv": Language.SWEDISH,
    "en": Language.ENGLISH,
    "fr": Language.FRENCH,
    "de": Language.GERMAN,
    "it": Language.ITALIAN,
    "es": Language.SPANISH,
    "pt": Language.PORTUGUESE,
    "ja": Language.JAPANESE,
    "ko": Language.KOREAN,
    "zh": Language.CHINESE,
    "cn": Language.CANTONESE,
    "fi": Language.FINNISH,
    "no": Language.NORWEGIAN,
    "nb": Language.NORWEGIAN,
    "nn": Language.NORWEGIAN,
    "da": Language.DANISH,
    "is": Language.ICELANDIC,
    "nl": Language.DUTCH,
    "pl": Language.POLISH,
    "ru": Language.RUSSIAN,
    "uk": Language.UKRAINIAN,
    "cs": Language.CZECH,
    "hu": Language.HUNGARIAN,
    "ro": Language.ROMANIAN,
    "el": Language.GREEK,
    "tr": Language.TURKISH,
    "ar": Language.ARABIC,
    "fa": Language.PERSIAN,
    "ku": Language.KURDISH,
    "he": Language.HEBREW,
    "hi": Language.HINDI,
    "kn": Language.KANNADA,
    "ta": Language.TAMIL,
    "te": Language.TELUGU,
    "th": Language.THAI,
    "vi": Language.VIETNAMESE,
    "ka": Language.GEORGIAN,
    "ca": Language.CATALAN,
    "kk": Language.KAZAKH,
    "az": Language.AZERBAIJANI,
    "sr": Language.SERBIAN,
    "hr": Language.CROATIAN,
    "bs": Language.BOSNIAN,
    "et": Language.ESTONIAN,
    "lv": Language.LATVIAN,
    "lt": Language.LITHUANIAN,
    "so": Language.SOMALI,
}


def languages(code: str) -> frozenset[Language]:
    """Languages for a TMDB original_language code; empty when unknown."""
    language = _LANGUAGES.get(code)
    return frozenset({language}) if language else frozenset()
