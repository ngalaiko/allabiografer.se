"""TMDB movie lookup — async-safe, file-per-movie storage.

Usage::

    from parse.tmdb import lookup

    # Returns TMDB ID if found, None otherwise.
    tmdb_id = lookup("Super Mario Galaxy Filmen", movies_dir=Path("movies"))

Files written::

    movies/<tmdb_id>.json      — metadata (title, overview, genres, …)
    movies/<tmdb_id>.w500.jpg  — poster image (may be .png depending on source)
"""

import fcntl
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from store import MOVIES_DIR

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


def _clean_title(title: str) -> str:
    """Strip noise from cinema titles to improve TMDB search."""
    # Remove parenthesised suffixes like "(Sv. tal)", "(Sv. txt)"
    title = re.sub(r"\s*\([^)]*\)\s*$", "", title)
    # "Title - English Title" → try the first part
    # But keep titles that are just one part
    if " - " in title:
        parts = title.split(" - ", 1)
        # If the left part is very short it's probably a prefix, use right
        title = parts[0] if len(parts[0]) > 3 else parts[1]
    # Strip leading "director's " patterns like "Lee Cronin's "
    title = re.sub(r"^[\w']+'s\s+", "", title)
    # Remove "förfilm ..." (short film listed alongside)
    title = re.sub(r"\s+förfilm\s+.*$", "", title, flags=re.IGNORECASE)
    # Remove version tags like ", version: Meänkieli"
    title = re.sub(r",\s*version:.*$", "", title, flags=re.IGNORECASE)
    # Remove "eng tal" / "sv tal" suffixes
    title = re.sub(r"\s+(eng|sv\.?)\s+(tal|txt)\.?\s*$", "", title, flags=re.IGNORECASE)
    return title.strip()


def _download_poster(session: requests.Session, poster_path: str, dest: Path) -> bool:
    """Download poster image. Returns True on success."""
    url = urljoin(_IMG_BASE, f"{_POSTER_SIZE}{poster_path}")
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        log.warning("failed to download poster %s", url)
        return False

    # Determine extension from content-type
    ct = resp.headers.get("content-type", "")
    if "png" in ct:
        ext = ".png"
    elif "webp" in ct:
        ext = ".webp"
    else:
        ext = ".jpg"

    out = dest.with_suffix(f".{_POSTER_SIZE}{ext}")
    out.write_bytes(resp.content)
    return True


def lookup(
    title: str,
    *,
    movies_dir: Path = MOVIES_DIR,
    session: requests.Session | None = None,
    year: int | None = None,
) -> int | None:
    """Search TMDB for *title*, save metadata + poster. Returns TMDB ID or None.

    Skips the network call if ``<movies_dir>/<tmdb_id>.json`` already exists
    for a previously resolved title — uses a local title→id index for that.
    """
    movies_dir.mkdir(parents=True, exist_ok=True)
    own_session = session is None
    if own_session:
        session = requests.Session()

    clean = _clean_title(title)

    # ------ index: title → tmdb_id (avoids re-searching) ------
    # Use file locking so concurrent parsers don't corrupt _index.json.
    index_path = movies_dir / "_index.json"
    lock_path = movies_dir / "_index.lock"

    with open(lock_path, "w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            result = _lookup_locked(clean, title, session, year, movies_dir, index_path)
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)

    if own_session:
        session.close()

    return result


def _lookup_locked(
    clean: str,
    title: str,
    session: requests.Session,
    year: int | None,
    movies_dir: Path,
    index_path: Path,
) -> int | None:
    """Runs while holding the index lock."""
    index: dict[str, int | None] = {}
    if index_path.exists():
        index = json.loads(index_path.read_text("utf-8"))
    if clean in index:
        return index[clean]

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
        index[clean] = None
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), "utf-8")
        return None

    movie = results[0]
    tmdb_id: int = movie["id"]

    # ------ already fetched? ------
    meta_path = movies_dir / f"{tmdb_id}.json"
    if meta_path.exists():
        index[clean] = tmdb_id
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), "utf-8")
        return tmdb_id

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
        return None

    # Extract Swedish age rating and release date from release_dates
    age_rating = ""
    release_date_se = ""
    for country in details.get("release_dates", {}).get("results", []):
        if country.get("iso_3166_1") == "SE":
            for entry in country.get("release_dates", []):
                cert = entry.get("certification", "")
                if cert and not age_rating:
                    age_rating = cert
                # Prefer theatrical (type 3), then limited (2), then premiere (1)
                rd = entry.get("release_date", "")
                rtype = entry.get("type", 0)
                if (rd and rtype == 3) or (rd and rtype in (1, 2) and not release_date_se):
                    release_date_se = rd[:10]
            break

    meta = {
        "tmdb_id": tmdb_id,
        "title_sv": details.get("title", ""),
        "title_original": details.get("original_title", ""),
        "overview_sv": details.get("overview", ""),
        "genres": [g["name"] for g in details.get("genres", [])],
        "release_date": details.get("release_date", ""),
        "release_date_se": release_date_se,
        "runtime": details.get("runtime"),
        "poster_path": details.get("poster_path", ""),
        "vote_average": details.get("vote_average"),
        "age_rating": age_rating,
    }

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")

    # ------ poster ------
    if meta["poster_path"]:
        _download_poster(session, meta["poster_path"], movies_dir / str(tmdb_id))

    # ------ update index ------
    index[clean] = tmdb_id
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), "utf-8")

    log.info("TMDB %d: %s", tmdb_id, meta["title_sv"] or meta["title_original"])
    return tmdb_id
