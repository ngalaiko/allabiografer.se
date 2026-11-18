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
import unicodedata
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from parse import _http
from parse._rating import age_rating as _age_rating
from store import (
    DB_FILE,
    Film,
    Movie,
    connect,
    has_poster,
    read_movie,
    title_key,
    tmdb_index_get,
    tmdb_index_set,
    write_movie,
    write_poster,
)
from store.film import shared_synopsis
from store.version import Language

log = logging.getLogger(__name__)

_API = "https://api.themoviedb.org/3"
_IMG_BASE = "https://image.tmdb.org/t/p/"
_API_KEY = "b692d29e51235ad793b851098f8edddf"
_POSTER_SIZE = "w500"

# Rate-limit: TMDB allows ~50 req/s, but be polite.
_MIN_INTERVAL = 0.05  # 20 req/s max
_last_request: float = 0.0
# Refresh mutable release metadata once per process, including failed attempts.
_refresh_attempts: set[tuple[Path, int]] = set()
_DIRECTOR_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS tmdb_director_aliases (tmdb_id INTEGER, name TEXT, PRIMARY KEY(tmdb_id,name))"
)


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
    title_key("Flaggan"): ("Flaggan", 2026),
    title_key("Främlingen"): ("Främlingen", 2025),
    title_key("Sense and Sensibility"): ("Sense and Sensibility", 2026),
    title_key("My Favorite Things"): ("My Favorite Things: The Rodgers & Hammerstein 80th Anniversary Concert", 2024),
    title_key("My Favourite Things"): ("My Favorite Things: The Rodgers & Hammerstein 80th Anniversary Concert", 2024),
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
    title = re.sub(r"^filmfeber:\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(
        r"(?:\s+\(live på bio\)|\s*:\s*bioupplevelsen|\s+cinema experience)$",
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

    Reuses compatible title-index entries, refreshing upcoming/recent releases
    once per process. Every store call is its own short transaction, so no db
    lock is held across network calls; concurrent lookups of the same title
    are harmless because the writes are upserts.
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
    if year is None and (hint := _TITLE_HINTS.get(title_key(clean))):
        clean, year = hint

    # ------ index: title → tmdb_id (avoids re-searching) ------
    cache_key = f"{title_key(clean)}|{year or ''}|{runtime or ''}"
    cached = tmdb_index_get(cache_key, path=path)
    stored = read_movie(cached, path=path) if cached is not None else None
    if stored is not None:
        # Ratings stored before normalisation are fixed on read.
        if stored.age_rating != _age_rating(stored.age_rating):
            write_movie(replace(stored, age_rating=_age_rating(stored.age_rating)), path=path)
        if _needs_refresh(stored, path):
            _fetch(cached, path, session)
            stored = read_movie(cached, path=path)
        if not runtime or not stored.runtime or abs(stored.runtime - runtime) <= 5:
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
            if stored is not None and _needs_refresh(stored, path):
                _fetch(candidate_id, path, session)
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
    stored = read_movie(tmdb_id, path=path)
    if (stored is None or _needs_refresh(stored, path)) and not _fetch(tmdb_id, path, session):
        return None
    stored = read_movie(tmdb_id, path=path)
    if runtime and stored.runtime and abs(stored.runtime - runtime) > 5:
        return None

    # ------ update index ------
    tmdb_index_set(cache_key, tmdb_id, path=path)

    return tmdb_id


def by_id(tmdb_id: int, *, path: Path = DB_FILE, session: requests.Session | None = None) -> int | None:
    """Store metadata + poster for a TMDB id a site states. Returns the id, or None when the fetch fails."""
    stored = read_movie(tmdb_id, path=path)
    if (
        stored is not None
        and not _needs_refresh(stored, path)
        and (not stored.poster_path or has_poster(tmdb_id, path=path))
    ):
        return tmdb_id
    own_session = session is None
    if own_session:
        session = _http.session()
    try:
        if stored is not None and not _needs_refresh(stored, path):
            if stored.poster_path and not has_poster(tmdb_id, path=path):
                _download_poster(session, stored.poster_path, tmdb_id, path)
            return tmdb_id
        return tmdb_id if _fetch(tmdb_id, path, session) or stored is not None else None
    finally:
        if own_session:
            session.close()


def _credit_key(text: str) -> str:
    """Fold Latin accents in credits without transliterating other scripts."""
    return "".join(
        "".join(c for c in unicodedata.normalize("NFD", letter) if not unicodedata.combining(c))
        if "LATIN" in unicodedata.name(letter, "")
        else letter
        for letter in title_key(text)
    )


def _director_key(name: str) -> str:
    # Alternate spellings of the same director, including the original credit.
    key = _credit_key(name)
    return "是枝裕和" if key in {"hirokazu koreeda", "hirokazu kore eda"} else key


def match_group(
    films: list[Film],
    movies: dict[int, Movie],
    *,
    identifiers: set[int],
    queries: list[dict],
    source_titles: dict[int, set[str]] | None = None,
    path: Path = DB_FILE,
    online: bool = False,
) -> dict:
    """Validate one source-only group against all candidates, never the first hit.

    Source facts remain independent of cached TMDB metadata. Offline runs use
    the same acceptance rules against the stored candidate inventory.
    """
    raw_titles = {t for f in films for t in (f.title, f.title_original) if t}
    raw_titles.update(q["title"] for q in queries if q.get("title"))
    titles = {title_key(_clean_title(re.sub(r"\s*\(\d{4}\)\s*$", "", t))) for t in raw_titles}
    years = {str(q["year"]) for q in queries if q.get("year")}
    years.update(m.group(1) for t in raw_titles if (m := re.search(r"\((\d{4})\)\s*$", t)))
    years.update(f.release_date for f in films if re.fullmatch(r"\d{4}", f.release_date))
    release_years = {f.release_date[:4] for f in films if f.release_date[:4].isdigit()}
    runtimes = {f.runtime for f in films if f.runtime}
    runtimes.update(q["runtime"] for q in queries if q.get("runtime"))
    director_claims = [{_director_key(d) for d in f.directors} for f in films if f.directors]
    director_claims.extend(
        {_director_key(credit)}
        for film in films
        for credit in re.findall(r"\b(?:regi|regissör|director)\s*:\s*([^\n.]+)", film.overview, re.IGNORECASE)
        if 1 < len(credit.split()) <= 6
    )
    credited_directors = set().union(*director_claims)
    director_aliases = defaultdict(set)
    aliases = defaultdict(set)
    alias_query = f"SELECT tmdb_id,title FROM tmdb_aliases WHERE title IN ({','.join('?' for _ in titles)})"
    with connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tmdb_aliases (tmdb_id INTEGER, title TEXT, PRIMARY KEY(tmdb_id,title))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS tmdb_alias_title ON tmdb_aliases(title)")
        conn.execute("CREATE TABLE IF NOT EXISTS tmdb_fetches (tmdb_id INTEGER PRIMARY KEY, status INTEGER)")
        conn.execute(_DIRECTOR_SCHEMA)
        for identifier, name in conn.execute("SELECT tmdb_id,name FROM tmdb_director_aliases WHERE name != ''"):
            director_aliases[identifier].add(_credit_key(name))
        fetched = dict(conn.execute("SELECT tmdb_id,status FROM tmdb_fetches"))
        missing = {identifier for identifier, status in fetched.items() if status == 404}
        for identifier, title in conn.execute(alias_query, list(titles)):
            aliases[identifier].add(title)
    for identifier, movie in movies.items():
        aliases[identifier].update((title_key(movie.title_sv), title_key(movie.title_original)))
        aliases[identifier].update((source_titles or {}).get(identifier, ()))
    candidates = set(identifiers)
    candidates.update(identifier for identifier, movie in movies.items() if titles & aliases[identifier])
    unavailable = False
    if online:
        failed = set()
        with _http.session() as session:
            for title in sorted(titles):
                page = 1
                while True:
                    try:
                        result = _get(session, f"{_API}/search/movie", language="sv-SE", query=title, page=str(page))
                    except requests.RequestException:
                        unavailable = True
                        break
                    candidates.update(
                        item["id"]
                        for item in result.get("results", [])
                        # Search also finds alternative titles absent from these
                        # localized fields. Validate aliases after fetching details.
                        if not years or not item.get("release_date") or item["release_date"][:4] in years
                    )
                    if page >= result.get("total_pages", 1):
                        break
                    page += 1
            for identifier in sorted(candidates):
                if (
                    identifier in missing
                    or identifier not in movies
                    or _needs_refresh(movies[identifier], path)
                    or identifier not in fetched
                    or (
                        identifier in identifiers
                        and not titles & aliases[identifier]
                        and (path.resolve(), identifier) not in _refresh_attempts
                    )
                ):
                    if _fetch(identifier, path, session, poster=False):
                        movies[identifier] = read_movie(identifier, path=path)
                        director_aliases.pop(identifier, None)
                    else:
                        failed.add(identifier)
            with connect(path) as conn:
                aliases.clear()
                for identifier, title in conn.execute(alias_query, list(titles)):
                    aliases[identifier].add(title)
                for identifier, names in (source_titles or {}).items():
                    aliases[identifier].update(names)
                missing = {row[0] for row in conn.execute("SELECT tmdb_id FROM tmdb_fetches WHERE status=404")}
            for identifier in sorted(candidates - missing):
                movie = movies.get(identifier)
                if (
                    movie
                    and movie.directors
                    and titles & (aliases[identifier] | {title_key(movie.title_sv), title_key(movie.title_original)})
                    and len(years) <= 1
                    and (not years or movie.release_date[:4] in years)
                    and any(
                        not claim & {_director_key(d) for d in (*movie.directors, *director_aliases[identifier])}
                        for claim in director_claims
                    )
                ):
                    try:
                        director_aliases[identifier] = _director_aliases(identifier, path, session)
                    except requests.RequestException:
                        failed.add(identifier)
            unavailable |= bool(failed - missing)

    decisions = []
    for identifier in sorted(candidates):
        movie = movies.get(identifier)
        reasons, support = [], []
        if identifier in missing:
            reasons.append("tmdb_not_found")
        elif movie is None:
            reasons.append("metadata_unavailable")
            unavailable = True
        else:
            if not titles & (aliases[identifier] | {title_key(movie.title_sv), title_key(movie.title_original)}):
                reasons.append("different_title")
            if len(years) > 1 or (years and movie.release_date[:4] not in years):
                reasons.append("year_conflict")
            elif movie.release_date[:4] in years | release_years:
                support.append("year")
            plot = any(shared_synopsis(f.overview, movie.overview_sv) for f in films)
            if plot:
                support.append("synopsis")
            if runtimes and movie.runtime:
                conflicting = {length for length in runtimes if abs(length - movie.runtime) > 5}
                documented_cuts = {
                    f.runtime
                    for f in films
                    if re.search(
                        r"director.s cut|bioversion|långa versionen|långversion|extended (?:cut|edition)",
                        f.overview,
                        re.IGNORECASE,
                    )
                }
                # Preserve Fågel Blå's published duration; a matching synopsis
                # from a cinema with the canonical runtime corroborates the work.
                reviewed_runtimes = (
                    {123}
                    if identifier == 1481789
                    and any(
                        f.source == "biofagelbla_se"
                        and f.url == "https://biofagelbla.se/movie/bloody-men/"
                        and f.runtime == 123
                        and any(
                            peer.runtime == movie.runtime and shared_synopsis(f.overview, peer.overview)
                            for peer in films
                        )
                        for f in films
                    )
                    else set()
                )
                if not conflicting:
                    support.append("runtime")
                elif (
                    not (
                        plot
                        and all(abs(length - movie.runtime) * 4 <= min(length, movie.runtime) for length in runtimes)
                    )
                    and not conflicting <= documented_cuts | reviewed_runtimes
                ):
                    reasons.append("runtime_conflict")
            movie_directors = {_credit_key(director) for director in movie.directors or []} | director_aliases[
                identifier
            ]
            director_keys = {_director_key(d) for d in movie_directors}
            if credited_directors & director_keys or any(
                re.search(
                    rf"(?<!inte )(?<!inte heller )\b(?:regi(?: av)?|regissor|"
                    rf"regissera[dt] av(?: den \w+ filmskaparen)?|directed by|director|"
                    rf"fran (?:\w+ ){{0,6}}regissoren) {re.escape(director)}\b"
                    rf"|\b{re.escape(director)} har regisserat (?:filmen|och skrivit manus)\b",
                    _credit_key(f.overview),
                )
                for f in films
                for director in movie_directors
            ):
                support.append("director")
            if movie.directors and any(not claim & director_keys for claim in director_claims):
                reasons.append("director_conflict")
            if not support:
                reasons.append("insufficient_evidence")
        decisions.append({"tmdb_id": identifier, "support": support, "rejected": reasons})
    accepted = [d["tmdb_id"] for d in decisions if not d["rejected"]]
    preferred = [d["tmdb_id"] for d in decisions if not d["rejected"] and {"director", "runtime"} <= set(d["support"])]
    choices = preferred or accepted
    identifier = choices[0] if len(choices) == 1 and not unavailable else None
    return {
        "tmdb_id": identifier,
        "reason": "accepted"
        if identifier
        else "lookup_unavailable"
        if unavailable
        else "ambiguous"
        if len(accepted) > 1
        else "unmatched",
        "titles": sorted(titles),
        "years": sorted(years),
        "runtimes": sorted(runtimes),
        "candidates": decisions,
    }


def _director_aliases(identifier: int, path: Path, session: requests.Session) -> set[str]:
    """Verified names for this movie's directors, never actor names or guessed transliterations."""
    with connect(path) as conn:
        conn.execute(_DIRECTOR_SCHEMA)
        cached = {
            _credit_key(row[0])
            for row in conn.execute("SELECT name FROM tmdb_director_aliases WHERE tmdb_id=?", (identifier,))
        }
    if cached:
        return cached - {""}
    credits = _get(session, f"{_API}/movie/{identifier}/credits", language="en-US")
    names = {""}  # A successful response with no directors is cached too.
    for person in credits.get("crew", []):
        if person.get("job") != "Director":
            continue
        names.update(_credit_key(person[k]) for k in ("name", "original_name") if person.get(k))
        if person.get("id"):
            details = _get(session, f"{_API}/person/{person['id']}", language="en-US")
            names.update(_credit_key(name) for name in [details.get("name"), *details.get("also_known_as", [])] if name)
    with connect(path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO tmdb_director_aliases VALUES (?,?)", [(identifier, name) for name in names]
        )
    return names - {""}


def _needs_refresh(movie: Movie, path: Path) -> bool:
    """Fill missing metadata, and refresh releases through 30 days after their latest premiere."""
    if (path.resolve(), movie.tmdb_id) in _refresh_attempts:
        return False
    cutoff = (datetime.now(ZoneInfo("Europe/Stockholm")) - timedelta(days=30)).date().isoformat()
    return (
        not movie.original_language
        or movie.spoken_languages is None
        or movie.directors is None
        or max(movie.release_date, movie.release_date_se) >= cutoff
    )


def _fetch(tmdb_id: int, path: Path, session: requests.Session, *, poster: bool = True) -> bool:
    """Fetch details for *tmdb_id*, store the movie and its poster.  False when the fetch fails."""
    _refresh_attempts.add((path.resolve(), tmdb_id))
    # ------ fetch full details ------
    try:
        details = _get(
            session,
            f"{_API}/movie/{tmdb_id}",
            language="sv-SE",
            append_to_response="release_dates,credits,alternative_titles,translations",
        )
    except requests.RequestException as error:
        if error.response is not None and error.response.status_code == 404:
            with connect(path) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS tmdb_fetches (tmdb_id INTEGER PRIMARY KEY, status INTEGER)")
                conn.execute("INSERT OR REPLACE INTO tmdb_fetches VALUES (?,404)", (tmdb_id,))
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
        runtime=details.get("runtime") or None,
        poster_path=details.get("poster_path") or "",
        vote_average=details.get("vote_average"),
        age_rating=age_rating,
        original_language=details.get("original_language") or "",
        spoken_languages=[s["iso_639_1"] for s in details.get("spoken_languages", []) if s.get("iso_639_1")],
        directors=[
            person["name"]
            for person in details.get("credits", {}).get("crew", [])
            if person.get("job") == "Director" and person.get("name")
        ],
    )
    write_movie(movie, path=path)
    with connect(path) as conn:
        conn.execute(_DIRECTOR_SCHEMA)
        conn.execute("DELETE FROM tmdb_director_aliases WHERE tmdb_id=?", (tmdb_id,))
        conn.execute("CREATE TABLE IF NOT EXISTS tmdb_fetches (tmdb_id INTEGER PRIMARY KEY, status INTEGER)")
        conn.execute("INSERT OR REPLACE INTO tmdb_fetches VALUES (?,200)", (tmdb_id,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tmdb_aliases (tmdb_id INTEGER, title TEXT, PRIMARY KEY(tmdb_id,title))"
        )
        conn.execute("DELETE FROM tmdb_aliases WHERE tmdb_id = ?", (tmdb_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO tmdb_aliases VALUES (?, ?)",
            [
                (tmdb_id, title_key(item["title"]))
                for item in (
                    *details.get("alternative_titles", {}).get("titles", []),
                    *(t.get("data", {}) for t in details.get("translations", {}).get("translations", [])),
                )
                if item.get("title")
            ],
        )

    # ------ poster ------
    if poster and movie.poster_path and not has_poster(tmdb_id, path=path):
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
