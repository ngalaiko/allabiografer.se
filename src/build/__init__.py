"""Build the static site from screening + movie data.

Usage::

    uv run build <output-dir>

Outputs to the given directory with this URL structure:

    /                                    - city A-O index
    /premiarer/                          - upcoming premieres
    /filmer/                             - all films currently showing
    /stad/{slug}/                        - programme for a city
    /stad/{slug}/{cinema-slug}/          - programme for a cinema
    /stad/{slug}/film/{film-slug}/       - film filtered to a city
    /film/{slug}/                        - programme for a film (nationwide)
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, UnidentifiedImageError

from build.festivals import build_festivals
from store import (
    DB_FILE,
    Film,
    Movie,
    Screening,
    Venue,
    poster_key_for_film,
    poster_keys,
    poster_path,
    read_all_films,
    read_movies,
    read_screenings,
    read_venues,
    title_key,
)
from store.version import (
    AudioKind,
    Dimension,
    Language,
    ProjectionMedium,
    speech_label,
    subtitles_label,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SWEDEN_TZ = ZoneInfo("Europe/Stockholm")
TEMPLATE_DIR = Path(__file__).parent / "templates"

# Canonical origin — see etc/nginx (www → apex redirect).
BASE_URL = "https://allabiografer.se"
SITE_NAME = "Alla biografer i Sverige"
SITE_DESCRIPTION = (
    "Hitta vad som går på bio i hela Sverige — speltider, kommande premiärer "
    "och alla biografer, stad för stad. Samlad bioguide för alla svenska biografer."
)
# Cap structured-data events per film page to keep page weight sane.
MAX_JSONLD_EVENTS = 100
SCHEDULE_DAYS = 14
TIME_ROW_HEIGHT = 22.5
TIME_LINK_HEIGHT = 20
TIME_VERTICAL_PADDING = 6.25


# Residensstäder — capital of each Swedish län.
LARGE_CITIES: set[str] = {
    "Stockholm",  # Stockholms län
    "Uppsala",  # Uppsala län
    "Nyköping",  # Södermanlands län
    "Linköping",  # Östergötlands län
    "Jönköping",  # Jönköpings län
    "Växjö",  # Kronobergs län
    "Kalmar",  # Kalmar län
    "Visby",  # Gotlands län
    "Karlskrona",  # Blekinge län
    "Malmö",  # Skåne län
    "Halmstad",  # Hallands län
    "Göteborg",  # Västra Götalands län
    "Karlstad",  # Värmlands län
    "Örebro",  # Örebro län
    "Västerås",  # Västmanlands län
    "Falun",  # Dalarnas län
    "Gävle",  # Gävleborgs län
    "Härnösand",  # Västernorrlands län
    "Östersund",  # Jämtlands län
    "Umeå",  # Västerbottens län
    "Luleå",  # Norrbottens län
}

SWEDISH_LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ")

DAY_ABBREVS = ["Mån", "Tis", "Ons", "Tors", "Fre", "Lör", "Sön"]
MONTH_ABBREVS = [
    "",
    "jan.",
    "feb.",
    "mars",
    "apr.",
    "maj",
    "juni",
    "juli",
    "aug.",
    "sep.",
    "okt.",
    "nov.",
    "dec.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """URL-safe slug via ASCII transliteration."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text)


def _slugify_sv(text: str) -> str:
    """Slug that preserves å ä ö for nice Swedish URLs."""
    text = text.lower().strip()
    text = re.sub(r"[^\wåäö\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text or "unnamed"


def _format_day(d: date) -> str:
    """e.g. 'Tis. 31 mars' or 'Ons. 1 apr.'"""
    dow = DAY_ABBREVS[d.weekday()]
    month = MONTH_ABBREVS[d.month]
    return f"{dow}. {d.day} {month}"


def _swedish_sort_key(name: str) -> tuple[int, str]:
    first = name[0].upper() if name else ""
    order = {c: i for i, c in enumerate(SWEDISH_LETTERS)}
    idx = order.get(first, 999)
    return (idx, name.lower())


# ---------------------------------------------------------------------------
# Time positioning inside day cells
# ---------------------------------------------------------------------------


def _compute_time_positions(times: list[tuple[time, str]]) -> list[dict]:
    """Return list of dicts {label, url, left, top, past} for template."""
    if not times:
        return []

    sorted_times = sorted(times, key=lambda t: (t[0].hour, t[0].minute))

    cell_w = 200
    pad = 5

    placed: list[dict] = []
    row_rights: list[float] = []
    row_heights: list[float] = []

    for entry in sorted_times:
        t, url = entry
        width = 45
        minutes = t.hour * 60 + t.minute
        frac = max(0, (minutes - 360)) / 1080
        left = pad + frac * (cell_w - width - 2 * pad)
        left = max(pad, min(left, cell_w - width - pad))

        is_placed = False
        for row_idx, right in enumerate(row_rights):
            if left >= right:
                row_rights[row_idx] = left + width
                row_heights[row_idx] = max(row_heights[row_idx], TIME_ROW_HEIGHT)
                placed.append({"label": t.strftime("%H:%M"), "url": url, "left": round(left, 1), "row": row_idx})
                is_placed = True
                break
        if not is_placed:
            row_idx = len(row_rights)
            row_rights.append(left + width)
            row_heights.append(TIME_ROW_HEIGHT)
            placed.append({"label": t.strftime("%H:%M"), "url": url, "left": round(left, 1), "row": row_idx})

    for item in placed:
        row = item.pop("row")
        item["top"] = round(TIME_VERTICAL_PADDING + sum(row_heights[:row]), 2)
    return placed


def _cell_min_height(positions: list[dict]) -> float:
    if not positions:
        return 0
    return max(p["top"] for p in positions) + TIME_LINK_HEIGHT + TIME_VERTICAL_PADDING


# ---------------------------------------------------------------------------
# Site data
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class SiteData:
    out_dir: Path = field(default_factory=lambda: Path("build"))
    screenings: list[Screening] = field(default_factory=list)
    movies: dict[int, Movie] = field(default_factory=dict)
    poster_keys: dict[int, str] = field(default_factory=dict)  # movie id → poster key
    poster_urls: dict[str, str] = field(default_factory=dict)
    broken_posters: set[str] = field(default_factory=set)  # poster keys Pillow could not decode
    cities: dict[str, int] = field(default_factory=dict)
    today: date = field(default_factory=lambda: datetime.now(tz=SWEDEN_TZ).date())
    days: list[date] = field(default_factory=list)
    venues: dict[tuple[str, str], Venue] = field(default_factory=dict)  # (city, name) → Venue
    city_slugs: dict[str, str] = field(default_factory=dict)
    cinema_slugs: dict[tuple[str, str], str] = field(default_factory=dict)
    film_slugs: dict[str, str] = field(default_factory=dict)
    sitemap_urls: list[str] = field(default_factory=list)


def _first(films: list[Film], attr: str):
    """First non-empty value of an attribute across films."""
    for film in films:
        value = getattr(film, attr)
        if value:
            return value
    return None


def _merge_films(movie: Movie, films: list[Film]) -> Movie:
    """Fill empty movie fields from the cinema sites' own metadata."""
    if not films:
        return movie
    return replace(
        movie,
        title_original=movie.title_original or _first(films, "title_original") or "",
        overview_sv=movie.overview_sv or _first(films, "overview") or "",
        runtime=movie.runtime or _first(films, "runtime"),
        genres=movie.genres or list(_first(films, "genres") or []),
        age_rating=movie.age_rating or _first(films, "age_rating") or "",
        release_date=movie.release_date or _first(films, "release_date") or "",
    )


def _aggregate_movies(sd: SiteData) -> dict[int, int]:
    """Combine same-title movies and screenings under one build-time identity."""
    by_title: dict[str, list[Movie]] = defaultdict(list)
    for movie in sd.movies.values():
        key = title_key(movie.title_sv or movie.title_original)
        if key:
            by_title[key].append(movie)

    aliases: dict[int, int] = {}
    for movies in by_title.values():
        # Prefer TMDB metadata, with a stable ID tie-breaker.
        movies.sort(key=lambda movie: (movie.tmdb_id < 0, movie.tmdb_id))
        canonical, *duplicates = movies
        values = canonical.to_dict()
        for movie in duplicates:
            aliases[movie.tmdb_id] = canonical.tmdb_id
            for name, value in movie.to_dict().items():
                if name != "tmdb_id" and not values[name]:
                    values[name] = value
            poster = sd.poster_keys.pop(movie.tmdb_id, None)
            if poster:
                sd.poster_keys.setdefault(canonical.tmdb_id, poster)
            del sd.movies[movie.tmdb_id]
        sd.movies[canonical.tmdb_id] = Movie.from_dict(values)

    sd.screenings = [replace(s, tmdb_id=aliases[s.tmdb_id]) if s.tmdb_id in aliases else s for s in sd.screenings]
    return aliases


def _load_data(out_dir: Path) -> SiteData:
    sd = SiteData(out_dir=out_dir)
    sd.today = datetime.now(tz=SWEDEN_TZ).date()

    print("Reading screenings…")
    all_screenings = read_screenings(path=DB_FILE)
    upcoming = [s for s in all_screenings if s.date >= sd.today]

    # The same film is described by several chains; pool them by normalised
    # title so a gap in one source is filled from another.
    all_films = read_all_films(path=DB_FILE)
    films_by_key = {f.key: f for f in all_films}
    films_by_title: dict[str, list[Film]] = defaultdict(list)
    for f in sorted(all_films, key=lambda f: f.source):
        films_by_title[f.key.partition(":")[2]].append(f)

    source_counts: dict[str, int] = defaultdict(int)
    for screening in upcoming:
        source = screening.film_key.partition(":")[0] if screening.film_key else screening.source
        source_counts[source] += 1

    def _film_rank(film: Film) -> tuple[int, str]:
        return (-source_counts[film.source], film.source)

    def _candidates(film: Film | None, title: str) -> list[Film]:
        """Same-title films ranked by their source's upcoming showing count."""
        key = film.key.partition(":")[2] if film else (title_key(title) if title else "")
        pool = [film] if film else []
        pool.extend(f for f in films_by_title.get(key, []) if film is None or f.key != film.key)
        return sorted(pool, key=_film_rank)

    # Site metadata backing each movie.
    films_of: dict[int, list[Film]] = {}
    sd.screenings = []
    for screening in upcoming:
        film = films_by_key.get(screening.film_key) if screening.film_key else None
        if screening.tmdb_id is None:
            # Negative identifiers exist only inside the build, never in TMDB or storage.
            title = screening.title
            if not title:
                raise ValueError("Screening has neither a title nor TMDB metadata")
            identifier = -int.from_bytes(hashlib.sha256(title.casefold().encode()).digest()[:8], "big")
            candidates = _candidates(film, title)
            if identifier not in sd.movies:
                base = Movie.from_dict(
                    {"tmdb_id": identifier, "title_sv": candidates[0].title if candidates else title}
                )
                sd.movies[identifier] = base
            screening = replace(screening, tmdb_id=identifier)
        else:
            candidates = _candidates(film, "")
        if candidates:
            films_of.setdefault(screening.tmdb_id, []).extend(candidates)
        sd.screenings.append(screening)
    print(f"  {len(sd.screenings)} screenings ({len(all_screenings) - len(sd.screenings)} past, skipped)")

    # Days are computed per-page from screening dates; keep a global
    # reference only for today.
    sd.days = []

    tmdb_ids: set[int] = set()
    for s in sd.screenings:
        tmdb_ids.add(s.tmdb_id)
        sd.cities[s.city] = sd.cities.get(s.city, 0) + 1

    print("Reading movie metadata…")
    # Synthetic ids are negative and absent from storage; they also exceed SQLite's integer range.
    sd.movies.update(read_movies({i for i in tmdb_ids if i > 0}, path=DB_FILE))

    stored = poster_keys(path=DB_FILE)
    for movie_id in tmdb_ids:
        if movie_id > 0 and str(movie_id) in stored:
            sd.poster_keys[movie_id] = str(movie_id)

    aliases = _aggregate_movies(sd)
    pooled_films: dict[int, dict[str, Film]] = defaultdict(dict)
    for movie_id, candidates in films_of.items():
        canonical_id = aliases.get(movie_id, movie_id)
        pooled_films[canonical_id].update((film.key, film) for film in candidates)
    for movie_id, movie in sd.movies.items():
        pool = pooled_films[movie_id]
        pool.update((film.key, film) for film in _candidates(None, movie.title_sv))
        candidates = sorted(pool.values(), key=_film_rank)
        sd.movies[movie_id] = _merge_films(movie, candidates)
        if movie_id not in sd.poster_keys:
            for film in candidates:
                film_poster = poster_key_for_film(film.key)
                if film_poster in stored:
                    sd.poster_keys[movie_id] = film_poster
                    break
    print(f"  {len(sd.movies)} movies, {len(sd.poster_keys)} posters")

    print("Reading venues…")
    for v in read_venues(path=DB_FILE):
        sd.venues[(v.city, v.name)] = v
    print(f"  {len(sd.venues)} venues")

    # Pre-compute slugs
    for city in sd.cities:
        sd.city_slugs[city] = _slugify_sv(city)
    for s in sd.screenings:
        key = (s.city, s.cinema_name)
        if key not in sd.cinema_slugs:
            sd.cinema_slugs[key] = _slugify_sv(s.cinema_name)
    for m in sd.movies.values():
        if m.title_sv and m.title_sv not in sd.film_slugs:
            sd.film_slugs[m.title_sv] = _slugify_sv(m.title_sv)

    return sd


# ---------------------------------------------------------------------------
# Poster processing
# ---------------------------------------------------------------------------

# Display size in CSS pixels; @2x for retina.
POSTER_CSS_W = 125
POSTER_CSS_H = 177
POSTER_W = POSTER_CSS_W * 2  # 250
POSTER_H = POSTER_CSS_H * 2  # 354
POSTER_QUALITY = 80
POSTER_WIDTHS = (104, 125, 250, 500)


def _process_poster(src: Path, dest: Path) -> None:
    """Crop and encode responsive WebP posters."""
    with Image.open(src) as img:
        img = img.convert("RGB")
        # Crop to target aspect ratio (centre crop) then resize
        src_ratio = img.width / img.height
        tgt_ratio = POSTER_W / POSTER_H
        if src_ratio > tgt_ratio:
            # Source is wider — crop sides
            new_w = int(img.height * tgt_ratio)
            offset = (img.width - new_w) // 2
            img = img.crop((offset, 0, offset + new_w, img.height))
        elif src_ratio < tgt_ratio:
            # Source is taller — crop top/bottom
            new_h = int(img.width / tgt_ratio)
            offset = (img.height - new_h) // 2
            img = img.crop((0, offset, img.width, offset + new_h))
        for width in POSTER_WIDTHS:
            height = round(width * POSTER_H / POSTER_W)
            output = dest if width == POSTER_W else dest.with_stem(f"{dest.stem}-{width}")
            img.resize((width, height), Image.LANCZOS).save(output, "WEBP", quality=POSTER_QUALITY)


def _poster_url(sd: SiteData, movie_id: int) -> str | None:
    key = sd.poster_keys.get(movie_id)
    if key is None or key in sd.broken_posters:
        return None
    if key in sd.poster_urls:
        return sd.poster_urls[key]
    src = poster_path(key, path=DB_FILE)
    if src is None:
        return None
    settings = f"{POSTER_WIDTHS}:{POSTER_H}:{POSTER_QUALITY}".encode()
    version = hashlib.sha256(src.read_bytes() + settings).hexdigest()[:12]
    # The site serves posters from one flat directory.
    name = f"{key.replace('/', '-')}-{version}"
    dest = sd.out_dir / "posters" / f"{name}.webp"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            _process_poster(src, dest)
        except (UnidentifiedImageError, OSError) as exc:
            sd.broken_posters.add(key)
            dest.unlink(missing_ok=True)
            print(f"  poster {key}: {exc}")
            return None
    sd.poster_urls[key] = f"/posters/{name}.webp"
    return sd.poster_urls[key]


# ---------------------------------------------------------------------------
# SEO: canonical URLs, sitemap, structured data
# ---------------------------------------------------------------------------


def _sitemap_priority(url: str) -> str:
    """Assign priority based on URL depth/type."""
    path = url[len(BASE_URL) :]
    if path in ("/", ""):
        return "1.0"
    if path in ("/premiarer/", "/filmer/"):
        return "0.9"
    # Nationwide film pages and large-city pages
    if path.startswith("/film/"):
        return "0.8"
    # City index pages — large cities get higher priority
    if path.startswith("/stad/") and path.count("/") == 3:
        city_slug = path.split("/")[2]
        large_city_slugs = {_slugify_sv(c) for c in LARGE_CITIES}
        return "0.8" if city_slug in large_city_slugs else "0.7"
    # Individual cinema pages
    if path.startswith("/stad/") and path.count("/") == 4:
        return "0.6"
    # City-filtered film pages
    if "/film/" in path:
        return "0.5"
    # Genre pages
    if "/genre/" in path:
        return "0.4"
    return "0.6"


def _register(sd: SiteData, out_path: Path) -> str:
    """Compute the canonical URL for a page and record it for the sitemap."""
    rel = out_path.relative_to(sd.out_dir)
    if rel.name == "index.html":
        parent = rel.parent
        url = f"{BASE_URL}/" if str(parent) == "." else f"{BASE_URL}/{parent.as_posix()}/"
    else:
        url = f"{BASE_URL}/{rel.as_posix()}"
    sd.sitemap_urls.append(url)
    return url


def _abs(url: str | None) -> str | None:
    """Make a site-relative URL absolute for og:image / structured data."""
    if not url:
        return None
    return url if url.startswith("http") else f"{BASE_URL}{url}"


def _jsonld(data: object) -> str:
    """Serialise a JSON-LD payload safely for an inline <script> tag."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _breadcrumb_node(items: list[tuple[str, str | None]]) -> dict:
    """A schema.org BreadcrumbList from (name, absolute-url|None) pairs."""
    elements = []
    for i, (name, url) in enumerate(items, start=1):
        el: dict = {"@type": "ListItem", "position": i, "name": name}
        if url:
            el["item"] = url
        elements.append(el)
    return {"@type": "BreadcrumbList", "itemListElement": elements}


def _website_jsonld() -> str:
    return _jsonld(
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": f"{BASE_URL}/",
            "inLanguage": "sv-SE",
            "description": SITE_DESCRIPTION,
        }
    )


def _film_jsonld(sd: SiteData, movie: Movie, screenings: list[Screening], canonical: str) -> str:
    """Movie + ScreeningEvent graph for a film programme page."""
    title = movie.title_sv or movie.title_original or f"Film {movie.tmdb_id}"
    movie_node: dict = {
        "@type": "Movie",
        "@id": f"{canonical}#movie",
        "name": title,
        "url": canonical,
        "inLanguage": "sv",
    }
    if movie.title_original and movie.title_original != title:
        movie_node["alternateName"] = movie.title_original
    poster = _abs(_poster_url(sd, movie.tmdb_id))
    if poster:
        movie_node["image"] = poster
    if movie.overview_sv:
        movie_node["description"] = movie.overview_sv
    if movie.genres:
        movie_node["genre"] = movie.genres
    if movie.release_date:
        movie_node["datePublished"] = movie.release_date
    if movie.runtime:
        movie_node["duration"] = f"PT{movie.runtime}M"
    if movie.age_rating:
        movie_node["contentRating"] = movie.age_rating

    graph: list[dict] = [movie_node]
    ordered = sorted(_schedule_screenings(sd, screenings), key=lambda s: (s.date, s.time))[:MAX_JSONLD_EVENTS]
    for s in ordered:
        start = datetime.combine(s.date, s.time, tzinfo=SWEDEN_TZ).isoformat()
        address: dict = {"@type": "PostalAddress", "addressLocality": s.city, "addressCountry": "SE"}
        venue = sd.venues.get((s.city, s.cinema_name))
        if venue and venue.address:
            address["streetAddress"] = venue.address
        event: dict = {
            "@type": "ScreeningEvent",
            "name": f"{title} – {s.cinema_name}, {s.city}",
            "startDate": start,
            **(
                {
                    "endDate": (
                        datetime.combine(s.date, s.time, tzinfo=SWEDEN_TZ) + timedelta(minutes=movie.runtime)
                    ).isoformat()
                }
                if movie.runtime
                else {}
            ),
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": {"@type": "MovieTheater", "name": s.cinema_name, "address": address},
            "workPresented": {"@id": f"{canonical}#movie"},
        }
        if s.ticket_url:
            event["offers"] = {
                "@type": "Offer",
                "url": s.ticket_url,
                "availability": "https://schema.org/InStock",
            }
        graph.append(event)

    graph.append(_breadcrumb_node([(SITE_NAME, f"{BASE_URL}/"), (title, canonical)]))
    return _jsonld({"@context": "https://schema.org", "@graph": graph})


def _cinema_jsonld(sd: SiteData, city: str, cinema_name: str, canonical: str) -> str:
    """MovieTheater node + breadcrumb for a cinema programme page."""
    address: dict = {"@type": "PostalAddress", "addressLocality": city, "addressCountry": "SE"}
    venue = sd.venues.get((city, cinema_name))
    if venue and venue.address:
        address["streetAddress"] = venue.address
    theater = {
        "@type": "MovieTheater",
        "name": cinema_name,
        "url": canonical,
        "address": address,
        "areaServed": city,
    }
    city_slug = sd.city_slugs.get(city, _slugify_sv(city))
    crumb = _breadcrumb_node(
        [(SITE_NAME, f"{BASE_URL}/"), (city, f"{BASE_URL}/stad/{city_slug}/"), (cinema_name, canonical)]
    )
    return _jsonld({"@context": "https://schema.org", "@graph": [theater, crumb]})


def _collection_jsonld(name: str, canonical: str, crumbs: list[tuple[str, str | None]]) -> str:
    """CollectionPage + breadcrumb for city / genre listing pages."""
    page = {
        "@type": "CollectionPage",
        "name": name,
        "url": canonical,
        "inLanguage": "sv-SE",
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": f"{BASE_URL}/"},
    }
    return _jsonld({"@context": "https://schema.org", "@graph": [page, _breadcrumb_node(crumbs)]})


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["style_version"] = hashlib.sha256(Path("static/i/style.css").read_bytes()).hexdigest()[:12]
    env.globals["synopsis_version"] = hashlib.sha256(Path("static/i/synopsis.js").read_bytes()).hexdigest()[:12]
    env.globals["links_version"] = hashlib.sha256(Path("static/i/links.js").read_bytes()).hexdigest()[:12]
    env.globals["showtimes_version"] = hashlib.sha256(Path("static/i/showtimes.js").read_bytes()).hexdigest()[:12]
    env.globals["font_versions"] = {
        weight: hashlib.sha256(Path(f"static/i/FiraSans-{weight}.woff2").read_bytes()).hexdigest()[:12]
        for weight in ("Regular", "SemiBold")
    }
    env.globals["posthog_token"] = os.environ.get("POSTHOG_PROJECT_TOKEN", "").strip()
    env.globals["posthog_host"] = os.environ.get("POSTHOG_HOST", "/salong").strip()
    return env


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _build_index(env: Environment, sd: SiteData) -> None:
    print("Building /")

    groups: list[tuple[str, list[dict]]] = []
    cities_by_letter: dict[str, list[str]] = defaultdict(list)
    for city in sorted(sd.cities.keys(), key=_swedish_sort_key):
        first = city[0].upper()
        cities_by_letter[first].append(city)

    for letter in SWEDISH_LETTERS:
        city_names = cities_by_letter.get(letter, [])
        if not city_names:
            continue
        city_dicts = [
            {
                "name": c,
                "slug": sd.city_slugs[c],
                "large": c in LARGE_CITIES,
            }
            for c in city_names
        ]
        groups.append((letter, city_dicts))

    out = sd.out_dir / "index.html"
    canonical = _register(sd, out)
    tmpl = env.get_template("index.html")
    html = tmpl.render(
        title="Alla biografer i Sverige – vad går på bio just nu?",
        description=SITE_DESCRIPTION,
        canonical=canonical,
        jsonld=_website_jsonld(),
        active="index",
        groups=groups,
    )
    out.write_text(html, encoding="utf-8")


def _build_premiarer(env: Environment, sd: SiteData) -> None:
    print("Building /premiarer/")

    # Premiere date: prefer Swedish release date from TMDB, fall back to
    # earliest screening date.
    first_screening: dict[int, date] = {}
    for s in sd.screenings:
        if s.tmdb_id not in first_screening or s.date < first_screening[s.tmdb_id]:
            first_screening[s.tmdb_id] = s.date

    def _premiere_date(tmdb_id: int) -> date | None:
        movie = sd.movies.get(tmdb_id)
        if movie and movie.release_date_se:
            try:
                return date.fromisoformat(movie.release_date_se)
            except ValueError:
                pass
        return first_screening.get(tmdb_id)

    # Only films whose premiere is in the future
    future: dict[date, list[Movie]] = defaultdict(list)
    for tmdb_id in first_screening:
        premiere = _premiere_date(tmdb_id)
        if not premiere or premiere <= sd.today:
            continue
        movie = sd.movies.get(tmdb_id)
        if movie:
            future[premiere].append(movie)

    date_groups = []
    for d in sorted(future.keys()):
        films = []
        for m in sorted(future[d], key=lambda x: x.title_sv.lower()):
            film_slug = sd.film_slugs.get(m.title_sv, _slugify_sv(m.title_sv))
            films.append(
                {
                    "title": m.title_sv,
                    "poster_url": _poster_url(sd, m.tmdb_id),
                    "url": f"/film/{film_slug}/",
                }
            )
        date_groups.append({"label": _format_day(d), "films": films})

    out = sd.out_dir / "premiarer" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    canonical = _register(sd, out)
    description = (
        "Kommande biopremiärer i Sverige. Se vilka filmer som har premiär framöver "
        "och var de visas — sorterat efter premiärdatum."
    )
    tmpl = env.get_template("premiarer.html")
    html = tmpl.render(
        title="Kommande biopremiärer i Sverige",
        description=description,
        canonical=canonical,
        jsonld=_collection_jsonld(
            "Kommande biopremiärer i Sverige",
            canonical,
            [(SITE_NAME, f"{BASE_URL}/"), ("Kommande premiärer", canonical)],
        ),
        active="premiarer",
        date_groups=date_groups,
    )
    out.write_text(html, encoding="utf-8")


def _build_filmer(env: Environment, sd: SiteData) -> None:
    print("Building /filmer/")

    screening_ids = {s.tmdb_id for s in sd.screenings}
    movies = [m for m in sd.movies.values() if m.tmdb_id in screening_ids]
    movies.sort(key=lambda m: m.title_sv.lower())

    films = [
        {
            "title": m.title_sv,
            "poster_url": _poster_url(sd, m.tmdb_id),
            "url": f"/film/{sd.film_slugs.get(m.title_sv, _slugify_sv(m.title_sv))}/",
        }
        for m in movies
    ]

    out = sd.out_dir / "filmer" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    canonical = _register(sd, out)
    description = (
        f"Alla {len(films)} filmer som visas på bio i Sverige just nu, i bokstavsordning. "
        "Klicka på en film för speltider och biografer."
    )
    tmpl = env.get_template("filmer.html")
    html = tmpl.render(
        title="Alla filmer som visas på bio i Sverige",
        description=description,
        canonical=canonical,
        jsonld=_collection_jsonld(
            "Alla filmer som visas på bio i Sverige",
            canonical,
            [(SITE_NAME, f"{BASE_URL}/"), ("Alla filmer", canonical)],
        ),
        active="filmer",
        films=films,
    )
    out.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Programme page data preparation
# ---------------------------------------------------------------------------


def _schedule_screenings(sd: SiteData, screenings: list[Screening]) -> list[Screening]:
    end = sd.today + timedelta(days=SCHEDULE_DAYS)
    return [s for s in screenings if sd.today <= s.date < end]


def _compute_days(screenings: list[Screening]) -> list[date]:
    """Return sorted list of dates that have at least one screening."""
    dates = {s.date for s in screenings}
    return sorted(dates)


def _variant_profile(screening: Screening) -> tuple:
    """Return only facts that define a user-facing screening variant."""
    version = screening.version
    presentation = screening.presentation
    audio = version.audio
    subtitle_languages = version.subtitles.languages
    return (
        audio.kind if audio.kind != AudioKind.UNKNOWN else None,
        frozenset(audio.languages) or None,
        frozenset(subtitle_languages) if subtitle_languages is not None else None,
        version.edition,
        frozenset(presentation.experiences),
        presentation.dimension if presentation.dimension != Dimension.UNKNOWN else None,
        presentation.medium,
        frozenset(presentation.projection),
        frozenset(presentation.sound),
        frozenset(presentation.auditorium),
        frozenset(screening.accessibility.features),
    )


def _profiles_compatible(left: tuple, right: tuple) -> bool:
    """Match unknown facts by axis; 3D and film projection are material variants."""
    for index, (a, b) in enumerate(zip(left, right, strict=True)):
        if index == 1 and a is not None and b is not None:
            if not a.intersection(b):
                return False
            continue
        # Unknown medium may join digital. Film formats (35/70 mm) stay distinct.
        if index == 6 and {a, b} == {ProjectionMedium.UNKNOWN, ProjectionMedium.DIGITAL}:
            continue
        # Missing dimension may join 2D, but 3D remains distinct in every
        # presentation system and projection medium.
        if index == 5 and (a is None) != (b is None):
            known = b if a is None else a
            if known == Dimension.THREE_D:
                return False
        if a is not None and b is not None and a != b:
            return False
    return True


def _merge_profiles(left: tuple, right: tuple) -> tuple:
    merged = []
    for index, (a, b) in enumerate(zip(left, right, strict=True)):
        if index == 1 and a is not None and b is not None:
            merged.append(a.union(b))
            continue
        if index == 6 and {a, b} == {ProjectionMedium.UNKNOWN, ProjectionMedium.DIGITAL}:
            merged.append(ProjectionMedium.DIGITAL)
        else:
            merged.append(a if a is not None else b)
    return tuple(merged)


def _profile_sort_key(profile: tuple) -> str:
    def value(item):
        if isinstance(item, (set, frozenset)):
            return sorted(part.value for part in item)
        return item.value if hasattr(item, "value") else item

    return json.dumps([value(item) for item in profile], ensure_ascii=False, sort_keys=True)


def _maximal_compatible_sets(profiles: list[tuple]) -> list[frozenset[int]]:
    """Enumerate maximal pairwise-compatible sets of distinct profiles."""
    neighbors = {
        i: {j for j, other in enumerate(profiles) if i != j and _profiles_compatible(profile, other)}
        for i, profile in enumerate(profiles)
    }
    maximal: list[frozenset[int]] = []

    def visit(current: set[int], candidates: set[int], excluded: set[int]) -> None:
        if not candidates and not excluded:
            maximal.append(frozenset(current))
            return
        pivot_pool = candidates | excluded
        pivot = max(pivot_pool, key=lambda item: len(candidates & neighbors[item])) if pivot_pool else None
        for node in sorted(candidates - (neighbors[pivot] if pivot is not None else set())):
            visit(current | {node}, candidates & neighbors[node], excluded & neighbors[node])
            candidates.remove(node)
            excluded.add(node)

    visit(set(), set(range(len(profiles))), set())
    return maximal


def _group_variant_profiles(screenings: list[Screening]) -> list[tuple[list[Screening], tuple]]:
    """Group profiles shared by one maximal compatibility set only."""
    by_film: dict[int | None, list[Screening]] = defaultdict(list)
    for screening in screenings:
        by_film[screening.tmdb_id].append(screening)

    result = []
    for film_id in sorted(by_film, key=lambda value: -1 if value is None else value):
        profile_members: dict[tuple, list[Screening]] = defaultdict(list)
        for screening in by_film[film_id]:
            profile_members[_variant_profile(screening)].append(screening)
        profiles = sorted(profile_members, key=_profile_sort_key)
        maximal_sets = _maximal_compatible_sets(profiles)
        memberships: dict[int, list[frozenset[int]]] = defaultdict(list)
        for group in maximal_sets:
            for index in group:
                memberships[index].append(group)

        assigned: dict[frozenset[int], list[int]] = defaultdict(list)
        ambiguous = []
        for index in range(len(profiles)):
            if len(memberships[index]) == 1:
                assigned[memberships[index][0]].append(index)
            else:
                ambiguous.append(index)

        for member_indices in assigned.values():
            merged = profiles[member_indices[0]]
            for index in member_indices[1:]:
                merged = _merge_profiles(merged, profiles[index])
            members = [s for index in member_indices for s in profile_members[profiles[index]]]
            result.append((members, merged))
        result.extend((profile_members[profiles[index]], profiles[index]) for index in ambiguous)
    return result


def _audio_label(profile: tuple) -> str:
    kind, languages = profile[0], profile[1]
    speech = speech_label(sorted(language.value for language in languages or ()))
    if kind == AudioKind.DUBBED:
        return speech or "Dubbad version"
    if kind == AudioKind.ORIGINAL:
        return "Originalversion"
    if kind == AudioKind.SILENT:
        return "Stum version"
    return speech


def _subtitle_label(languages: frozenset[Language] | None) -> str:
    if languages is None:
        return ""
    if not languages:
        return "Ej textad"
    return subtitles_label(sorted(language.value for language in languages))


def _profile_component_label(index: int, profile: tuple) -> str:
    value = profile[index]
    if index == 0:
        return _audio_label(profile)
    if index == 1:
        return speech_label(sorted(language.value for language in profile[1] or ())) or _audio_label(profile)
    if index == 2:
        return _subtitle_label(value)
    if index == 3:
        return value or "Edition okänd"
    if index == 4:
        return ", ".join(sorted(system.value for system in value)) if value else ""
    if index == 5:
        return value.value if value else "Dimension okänd"
    if index == 6:
        if value in (ProjectionMedium.UNKNOWN, ProjectionMedium.DIGITAL):
            return ""
        return value.value if value else "Projektion okänd"
    if index in (7, 8, 9, 10):
        return ", ".join(sorted(attribute.value for attribute in value))
    return ""


def _variants(screenings: list[Screening]) -> dict[Screening, tuple[str, str]]:
    """Return a stable group key and a clear label for each screening."""
    groups = _group_variant_profiles(screenings)
    by_film: dict[int | None, list[tuple[list[Screening], tuple]]] = defaultdict(list)
    for members, profile in groups:
        by_film[members[0].tmdb_id].append((members, profile))

    result: dict[int, tuple[str, str]] = {}
    for film_groups in by_film.values():
        profiles = [profile for _, profile in film_groups]
        split_axes = set()
        if len({profile[0] for profile in profiles}) > 1:
            split_axes.add(0)
        if len({profile[1] for profile in profiles}) > 1:
            split_axes.add(1)
        if len({profile[2] for profile in profiles}) > 1:
            split_axes.add(2)
        if len({profile[3] for profile in profiles}) > 1:
            split_axes.add(3)
        if len({profile[4] for profile in profiles}) > 1 or any(profile[4] for profile in profiles):
            split_axes.add(4)
        known_dimensions = {profile[5] for profile in profiles if profile[5] is not None}
        if len(known_dimensions) > 1 or any(profile[5] == Dimension.THREE_D for profile in profiles):
            split_axes.add(5)
        if any(profile[6] in (ProjectionMedium.MM_35, ProjectionMedium.MM_70) for profile in profiles):
            split_axes.add(6)
        for index in (7, 8, 9, 10):
            if any(profile[index] for profile in profiles):
                split_axes.add(index)
        for members, profile in film_groups:
            labels = []
            for index in sorted(split_axes):
                value = profile[index]
                if value is None:
                    if index != 5 or len(known_dimensions) > 1:
                        text = _profile_component_label(index, profile)
                        if text:
                            labels.append(text)
                else:
                    text = _profile_component_label(index, profile)
                    if text:
                        labels.append(text)
            label = " · ".join(dict.fromkeys(labels))
            identity = hashlib.sha256(_profile_sort_key(profile).encode()).hexdigest()[:12]
            for screening in members:
                result[id(screening)] = (identity, label)
    return result


def _prepare_programme_blocks(
    sd: SiteData,
    screenings: list[Screening],
    days: list[date],
    *,
    city: str | None = None,
) -> list[dict]:
    """Prepare template-ready block dicts for a programme page."""

    now = datetime.now(tz=SWEDEN_TZ)
    day_set = set(days)
    filtered = [s for s in screenings if s.date in day_set]
    variants = _variants(filtered)

    # (movie, variant) → (city, cinema) → day → [(time, url)]
    movie_cinemas: dict[tuple[int, str, str], dict[tuple[str, str], dict[int, list[tuple[time, str]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # Ranking score: each screening contributes more the sooner it is, so films
    # playing a lot in the near columns float to the top rather than films that
    # are blank for weeks and then burst with screenings far in the future.
    movie_score: dict[tuple[int, str, str], float] = defaultdict(float)
    movie_earliest: dict[tuple[int, str, str], tuple[date, time]] = {}
    block_profiles: dict[tuple[int, str, str], tuple] = {}
    for s in filtered:
        try:
            day_idx = days.index(s.date)
        except ValueError:
            continue
        block_key = (s.tmdb_id, *variants[id(s)])
        profile = _variant_profile(s)
        block_profiles[block_key] = (
            _merge_profiles(block_profiles[block_key], profile) if block_key in block_profiles else profile
        )
        movie_cinemas[block_key][(s.city, s.cinema_name)][day_idx].append((s.time, s.ticket_url))
        movie_score[block_key] += 1.0 / (1 + day_idx)
        key = (s.date, s.time)
        if block_key not in movie_earliest or key < movie_earliest[block_key]:
            movie_earliest[block_key] = key

    # Films rank by all their variants together; variants of one film stay adjacent.
    film_score: dict[int, float] = defaultdict(float)
    film_earliest: dict[int, tuple[date, time]] = {}
    for (tmdb_id, *_), score in movie_score.items():
        film_score[tmdb_id] += score
    for (tmdb_id, *_), earliest in movie_earliest.items():
        film_earliest[tmdb_id] = min(earliest, film_earliest.get(tmdb_id, earliest))

    def _rank(bk: tuple[int, str, str]) -> tuple:
        tmdb_id, identity, label = bk
        return (-film_score[tmdb_id], film_earliest[tmdb_id], tmdb_id, bool(label), label.casefold(), identity)

    blocks = []
    label_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for block_key in movie_cinemas:
        label_counts[block_key[0]][block_key[2]] += 1
    for block_key in sorted(movie_cinemas, key=_rank):
        tmdb_id, _, variant = block_key
        movie = sd.movies.get(tmdb_id)
        film_title = movie.title_sv if movie else f"Film {tmdb_id}"
        film_slug = sd.film_slugs.get(film_title, _slugify_sv(film_title))

        # Movie info line
        mi_parts: list[str] = []
        if movie:
            for g in movie.genres:
                if city:
                    city_slug = sd.city_slugs.get(city, _slugify_sv(city))
                    genre_slug = _slugify_sv(g)
                    mi_parts.append(f'<a href="/stad/{city_slug}/genre/{genre_slug}/">{g}</a>')
                else:
                    mi_parts.append(g)
            year = movie.release_date[:4] if movie.release_date else ""
            if year:
                mi_parts.append(year)
            if movie.runtime:
                h, m = divmod(movie.runtime, 60)
                mi_parts.append(f"{h} tim. {m} min." if h else f"{m} min.")
            if movie.age_rating:
                mi_parts.append(movie.age_rating)
        profile = block_profiles[block_key]
        if profile[1]:
            mi_parts.append(speech_label(sorted(language.value for language in profile[1])))
        if profile[2] is not None:
            mi_parts.append(
                subtitles_label(sorted(language.value for language in profile[2])) if profile[2] else "Ej textad"
            )
        desc = ""
        full_desc = ""
        if movie and movie.overview_sv:
            full_desc = movie.overview_sv
            desc = full_desc[:200] + "…" if len(full_desc) > 200 else full_desc

        cinema_map = movie_cinemas[block_key]
        cinema_rows = []
        for cinema_city, cinema_name in sorted(cinema_map):
            day_times = cinema_map[(cinema_city, cinema_name)]

            cells = []
            max_h = 55.0
            for day_idx in range(len(days)):
                raw = day_times.get(day_idx, [])
                positions = _compute_time_positions(raw)
                # Mark past times
                for p in positions:
                    dt = datetime.combine(days[day_idx], time(*map(int, p["label"].split(":"))), tzinfo=SWEDEN_TZ)
                    p["past"] = dt < now
                    p["start"] = dt.isoformat()
                h = _cell_min_height(positions)
                if h > max_h:
                    max_h = h
                cells.append({"times": positions})

            cc = city or cinema_city
            city_slug = sd.city_slugs.get(cc, _slugify_sv(cc))
            cinema_slug = sd.cinema_slugs.get((cc, cinema_name), _slugify_sv(cinema_name))
            cinema_url = f"/stad/{city_slug}/{cinema_slug}/"

            # Look up venue address
            venue = sd.venues.get((cinema_city, cinema_name))
            address = venue.address if venue else ""

            # On film pages (no single city), provide city info separately
            cinema_city_name = None
            cinema_city_url = None
            if not city:
                cinema_city_name = cinema_city
                cinema_city_url = f"/stad/{city_slug}/"

            cinema_rows.append(
                {
                    "name": cinema_name,
                    "url": cinema_url,
                    "address": address,
                    "city_name": cinema_city_name,
                    "city_url": cinema_city_url,
                    "min_height": max_h,
                    "cells": cells,
                }
            )

        if city:
            city_slug = sd.city_slugs.get(city, _slugify_sv(city))
            film_url = f"/stad/{city_slug}/film/{film_slug}/"
        else:
            film_url = f"/film/{film_slug}/"

        blocks.append(
            {
                "poster_url": _poster_url(sd, tmdb_id),
                "film_id": "-".join(
                    [
                        film_slug,
                        _slugify_sv(variant) if variant else "",
                        block_key[1] if label_counts[tmdb_id][variant] > 1 else "",
                    ]
                ).strip("-"),
                "film_title": film_title,
                "variant": variant,
                "film_url": film_url,
                "mi": " • ".join(mi_parts) if mi_parts else "",
                "desc": desc,
                "full_desc": full_desc,
                "cinemas": cinema_rows,
            }
        )

    return blocks


def _write_programme(
    env: Environment,
    sd: SiteData,
    screenings: list[Screening],
    *,
    title: str,
    breadcrumbs: str,
    out_path: Path,
    canonical: str,
    city: str | None = None,
    description: str | None = None,
    jsonld: str | None = None,
    og_image: str | None = None,
    og_type: str | None = None,
    clear_filter_url: str | None = None,
) -> None:
    screenings = _schedule_screenings(sd, screenings)
    page_days = _compute_days(screenings)
    blocks = _prepare_programme_blocks(sd, screenings, page_days, city=city)
    days = [{"label": _format_day(d), "date": d.isoformat()} for d in page_days]

    tmpl = env.get_template("program.html")
    html = tmpl.render(
        title=title,
        description=description,
        canonical=canonical,
        jsonld=jsonld,
        og_image=og_image,
        og_type=og_type,
        breadcrumbs=breadcrumbs,
        clear_filter_url=clear_filter_url,
        days=days,
        num_days=max(1, len(page_days)),
        blocks=blocks,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def _build_programme_pages(env: Environment, sd: SiteData) -> None:
    print("Building programme pages…")

    by_city: dict[str, list[Screening]] = defaultdict(list)
    by_city_cinema: dict[tuple[str, str], list[Screening]] = defaultdict(list)
    by_film: dict[str, list[Screening]] = defaultdict(list)
    by_city_genre: dict[tuple[str, str], list[Screening]] = defaultdict(list)
    by_city_film: dict[tuple[str, str], list[Screening]] = defaultdict(list)

    for s in sd.screenings:
        by_city[s.city].append(s)
        by_city_cinema[(s.city, s.cinema_name)].append(s)
        movie = sd.movies.get(s.tmdb_id)
        if movie and movie.title_sv:
            by_film[movie.title_sv].append(s)
            by_city_film[(s.city, movie.title_sv)].append(s)
            for genre in movie.genres:
                by_city_genre[(s.city, genre)].append(s)

    # /stad/{slug}/
    for city_name, city_screenings in sorted(by_city.items()):
        slug = sd.city_slugs[city_name]
        print(f"  /stad/{slug}/")
        out_path = sd.out_dir / "stad" / slug / "index.html"
        canonical = _register(sd, out_path)
        n_films = len({s.tmdb_id for s in _schedule_screenings(sd, city_screenings)})
        title = f"På bio i {city_name} – speltider och biografer"
        _write_programme(
            env,
            sd,
            city_screenings,
            title=title,
            description=(
                f"Vad går på bio i {city_name}? Se speltider för {n_films} filmer på alla "
                f"biografer i {city_name} — uppdaterat dagligen."
            ),
            canonical=canonical,
            jsonld=_collection_jsonld(
                f"På bio i {city_name}",
                canonical,
                [(SITE_NAME, f"{BASE_URL}/"), (city_name, canonical)],
            ),
            breadcrumbs=f" / {city_name}",
            out_path=out_path,
            city=city_name,
        )

    # /stad/{slug}/{cinema-slug}/
    for (city_name, cinema_name), cinema_screenings in sorted(by_city_cinema.items()):
        city_slug = sd.city_slugs[city_name]
        cinema_slug = sd.cinema_slugs[(city_name, cinema_name)]
        out_path = sd.out_dir / "stad" / city_slug / cinema_slug / "index.html"
        canonical = _register(sd, out_path)
        _write_programme(
            env,
            sd,
            cinema_screenings,
            title=f"{cinema_name} i {city_name} – program och speltider",
            description=(
                f"Program och speltider för {cinema_name} i {city_name}. Se vilka filmer som visas och köp biljetter."
            ),
            canonical=canonical,
            jsonld=_cinema_jsonld(sd, city_name, cinema_name, canonical),
            breadcrumbs=f' / <a href="/stad/{city_slug}/">{city_name}</a> / {cinema_name}',
            clear_filter_url=f"/stad/{city_slug}/",
            out_path=out_path,
            city=city_name,
        )

    # /stad/{slug}/genre/{genre-slug}/
    for (city_name, genre), genre_screenings in sorted(by_city_genre.items()):
        city_slug = sd.city_slugs[city_name]
        genre_slug = _slugify_sv(genre)
        out_path = sd.out_dir / "stad" / city_slug / "genre" / genre_slug / "index.html"
        canonical = _register(sd, out_path)
        _write_programme(
            env,
            sd,
            genre_screenings,
            title=f"{genre} på bio i {city_name} – speltider",
            description=f"{genre}-filmer som visas på bio i {city_name} just nu, med speltider och biografer.",
            canonical=canonical,
            jsonld=_collection_jsonld(
                f"{genre} på bio i {city_name}",
                canonical,
                [
                    (SITE_NAME, f"{BASE_URL}/"),
                    (city_name, f"{BASE_URL}/stad/{city_slug}/"),
                    (genre, canonical),
                ],
            ),
            breadcrumbs=f' / <a href="/stad/{city_slug}/">{city_name}</a> / {genre}',
            clear_filter_url=f"/stad/{city_slug}/",
            out_path=out_path,
            city=city_name,
        )

    # /stad/{slug}/film/{film-slug}/
    for (city_name, film_title), city_film_screenings in sorted(by_city_film.items()):
        city_slug = sd.city_slugs[city_name]
        film_slug = sd.film_slugs.get(film_title, _slugify_sv(film_title))
        out_path = sd.out_dir / "stad" / city_slug / "film" / film_slug / "index.html"
        canonical = _register(sd, out_path)
        movie = next((sd.movies.get(s.tmdb_id) for s in city_film_screenings if sd.movies.get(s.tmdb_id)), None)
        if movie and movie.overview_sv:
            description = movie.overview_sv[:155].rstrip()
            if len(movie.overview_sv) > 155:
                description += "…"
        else:
            n_cinemas = len({s.cinema_name for s in _schedule_screenings(sd, city_film_screenings)})
            description = (
                f"Speltider för {film_title} på biografer i {city_name} — "
                f"visas på {n_cinemas} {'biograf' if n_cinemas == 1 else 'biografer'}."
            )
        jsonld = _film_jsonld(sd, movie, city_film_screenings, canonical) if movie else None
        og_image = _abs(_poster_url(sd, movie.tmdb_id)) if movie else None
        _write_programme(
            env,
            sd,
            city_film_screenings,
            title=f"{film_title} i {city_name} – speltider på bio",
            description=description,
            canonical=canonical,
            jsonld=jsonld,
            og_image=og_image,
            og_type="video.movie",
            breadcrumbs=f' / <a href="/stad/{city_slug}/">{city_name}</a> / {film_title}',
            clear_filter_url=f"/stad/{city_slug}/",
            out_path=out_path,
            city=city_name,
        )

    # /film/{slug}/
    for film_title, film_screenings in sorted(by_film.items()):
        slug = sd.film_slugs[film_title]
        out_path = sd.out_dir / "film" / slug / "index.html"
        canonical = _register(sd, out_path)
        movie = next((sd.movies.get(s.tmdb_id) for s in film_screenings if sd.movies.get(s.tmdb_id)), None)
        n_cities = len({s.city for s in _schedule_screenings(sd, film_screenings)})
        if movie and movie.overview_sv:
            description = movie.overview_sv[:155].rstrip()
            if len(movie.overview_sv) > 155:
                description += "…"
        else:
            description = (
                f"Speltider för {film_title} på biografer i hela Sverige — "
                f"visas i {n_cities} {'stad' if n_cities == 1 else 'städer'}."
            )
        jsonld = _film_jsonld(sd, movie, film_screenings, canonical) if movie else None
        og_image = _abs(_poster_url(sd, movie.tmdb_id)) if movie else None
        _write_programme(
            env,
            sd,
            film_screenings,
            title=f"{film_title} – speltider på bio i Sverige",
            description=description,
            canonical=canonical,
            jsonld=jsonld,
            og_image=og_image,
            og_type="video.movie",
            breadcrumbs=f" / {film_title}",
            clear_filter_url="/",
            out_path=out_path,
        )


# ---------------------------------------------------------------------------
# Copy static assets
# ---------------------------------------------------------------------------


def _write_robots(out_dir: Path) -> None:
    """robots.txt — allow everyone, explicitly welcome AI crawlers, link sitemap."""
    print("Writing robots.txt")
    # Crawlers commonly used by search engines and LLM assistants. Listed
    # explicitly so there is no ambiguity that indexing is welcome.
    agents = [
        "*",
        "Googlebot",
        "Bingbot",
        "GPTBot",
        "OAI-SearchBot",
        "ChatGPT-User",
        "ClaudeBot",
        "Claude-Web",
        "anthropic-ai",
        "PerplexityBot",
        "Google-Extended",
        "Applebot",
        "Applebot-Extended",
    ]
    lines = []
    for agent in agents:
        lines.append(f"User-agent: {agent}")
        lines.append("Allow: /")
        lines.append("")
    lines.append(f"Sitemap: {BASE_URL}/sitemap.xml")
    lines.append("")
    (out_dir / "robots.txt").write_text("\n".join(lines), encoding="utf-8")


def _write_sitemap(sd: SiteData) -> None:
    """sitemap.xml listing every generated page, newest-relevant first."""
    print(f"Writing sitemap.xml ({len(sd.sitemap_urls)} urls)")
    lastmod = sd.today.isoformat()
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    for url in sd.sitemap_urls:
        if url in seen:
            continue
        seen.add(url)
        priority = _sitemap_priority(url)
        parts.append("<url>")
        parts.append(f"<loc>{url}</loc>")
        parts.append(f"<lastmod>{lastmod}</lastmod>")
        parts.append("<changefreq>daily</changefreq>")
        parts.append(f"<priority>{priority}</priority>")
        parts.append("</url>")
    parts.append("</urlset>")
    parts.append("")
    (sd.out_dir / "sitemap.xml").write_text("\n".join(parts), encoding="utf-8")


def _copy_static(out_dir: Path) -> None:
    print("Copying static assets…")
    src = Path("static") / "i"
    if src.exists():
        dest = out_dir / "i"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static site.")
    parser.add_argument("output", type=Path, help="Output directory")
    args = parser.parse_args()

    out_dir: Path = args.output
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    _copy_static(out_dir)
    sd = _load_data(out_dir)
    env = _make_env()

    _build_index(env, sd)
    _build_premiarer(env, sd)
    _build_filmer(env, sd)
    _build_programme_pages(env, sd)
    build_festivals(env, sd, _register, DB_FILE)

    _write_robots(out_dir)
    _write_sitemap(sd)

    print(f"\nDone. Output in {out_dir}/")
