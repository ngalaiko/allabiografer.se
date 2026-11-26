"""Render the merged schedule as the allabiografer.se static site.

`render.py` fills the page data from the merged Dataset.

    /                                    - city A-Ö index
    /stad/{slug}/                        - programme for a city
    /stad/{slug}/{cinema-slug}/          - programme for a cinema
    /stad/{slug}/film/{film-slug}/       - film filtered to a city
    /film/{slug}/                        - programme for a film (nationwide)
"""

import hashlib
import html
import io
import json
import os
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from html import escape
from itertools import combinations
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, UnidentifiedImageError

from allabiografer.model import Film, Screening, Venue, title_key
from allabiografer.model.movie import Movie
from allabiografer.model.version import (
    Accessibility,
    AudioKind,
    AudioVersion,
    ContentVersion,
    Dimension,
    Language,
    Presentation,
    PresentationSystem,
    ProjectionMedium,
    SubtitleVersion,
    speech_label,
    subtitles_label,
)

from .markdown import link, page_link, write_page, write_programme
from .og import write_card

_FORMAT_SYSTEMS = frozenset(
    {
        PresentationSystem.IMAX,
        PresentationSystem.DOLBY_CINEMA,
        PresentationSystem.FOUR_DX,
        PresentationSystem.SCREENX,
        PresentationSystem.D_BOX,
        PresentationSystem.ISENSE,
        PresentationSystem.INFINITY_VISION,
    }
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SWEDEN_TZ = ZoneInfo("Europe/Stockholm")
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static" / "i"

# Canonical origin.
BASE_URL = "https://allabiografer.se"
SITE_NAME = "Alla biografer i Sverige"
SITE_DESCRIPTION = (
    "Hitta vad som går på bio i hela Sverige — speltider, kommande premiärer "
    "och alla biografer, stad för stad. Samlad bioguide för alla svenska biografer."
)
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


def city_programme_url(city: str) -> str:
    return f"{BASE_URL}/stad/{_slugify_sv(city)}/"


def film_anchor(title: str) -> str:
    """Stable fragment shared by city programmes and newsletter links."""
    return "film-" + title_key(title).replace(" ", "-")


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
    films: dict[str, Film] = field(default_factory=dict)
    # movie id → stored original poster (an ImageObject or DataDownload entity)
    posters: dict[int, dict] = field(default_factory=dict)
    poster_urls: dict[int, str | None] = field(default_factory=dict)
    graph: object = None
    cities: dict[str, int] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=SWEDEN_TZ))
    today: date = field(default_factory=lambda: datetime.now(tz=SWEDEN_TZ).date())
    venues: dict[tuple[str, str], Venue] = field(default_factory=dict)  # (city, name) → Venue
    city_slugs: dict[str, str] = field(default_factory=dict)
    cinema_slugs: dict[tuple[str, str], str] = field(default_factory=dict)
    film_slugs: dict[int, str] = field(default_factory=dict)
    # Build-time movie keys are catalogue identities, not necessarily TMDB IDs.
    tmdb_ids: dict[int, int | None] = field(default_factory=dict)
    film_aliases: dict[str, str] = field(default_factory=dict)
    # (city, former cinema slug) → current cinema slug.
    cinema_aliases: dict[tuple[str, str], str] = field(default_factory=dict)
    city_films: set[tuple[str, int]] = field(default_factory=set)
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


def _screening_runtime(sd: SiteData, screening: Screening) -> int | None:
    """The cinema's listed duration; missing source data stays unknown."""
    if screening.runtime is not None:
        return screening.runtime
    film = sd.films.get(screening.film_key)
    movie = sd.movies.get(screening.tmdb_id)
    return (film.runtime if film else movie.runtime if movie else None) or None


def _deduplicate_screenings(sd: SiteData) -> list[Screening]:
    """Combine compatible observations of one show across sources, never within a source."""
    slots: dict[tuple, list[Screening]] = defaultdict(list)
    for s in sd.screenings:
        slots[(s.city, s.cinema_name, s.tmdb_id, s.date, s.time)].append(s)
    runtime_slots = []
    for slot in slots.values():
        by_runtime = defaultdict(list)
        for s in slot:
            by_runtime[_screening_runtime(sd, s)].append(s)
        known = set(by_runtime) - {None}
        # A missing duration is compatible with one known cut, not a bridge
        # between competing cuts. The selected source's runtime stays intact.
        if len(known) == 1:
            by_runtime[next(iter(known))].extend(by_runtime.pop(None, []))
        runtime_slots.extend(by_runtime.values())
    result = []
    for slot in runtime_slots:
        if len(slot) == 1:
            result.extend(slot)
            continue
        for members, profile in _group_variant_profiles(slot):
            sources = {s.source for s in members}
            halls = {s.screen for s in members if s.screen}
            # Multiple halls or observations from one source are not a proven duplicate.
            if "" in sources or len(sources) != len(members) or len(halls) > 1:
                result.extend(members)
                continue
            # Prefer a booking link over bio.se's general cinema-page fallback.
            primary = min(
                members,
                key=lambda s: (
                    not s.ticket_url,
                    s.ticket_url.startswith("https://bio.se/biografer/"),
                    s.source,
                    s.ticket_url,
                ),
            )
            result.append(
                replace(
                    primary,
                    screen=next(iter(halls), ""),
                    version=ContentVersion(
                        audio=AudioVersion(profile[0] or AudioKind.UNKNOWN, profile[1] or frozenset()),
                        subtitles=SubtitleVersion(profile[2]),
                        edition=profile[3],
                    ),
                    presentation=Presentation(
                        experiences=profile[4],
                        dimension=profile[5] or Dimension.UNKNOWN,
                        medium=profile[6],
                        projection=profile[7],
                        sound=profile[8],
                        auditorium=profile[9],
                    ),
                    accessibility=Accessibility(profile[10]),
                    raw_attributes=tuple(sorted({a for s in members for a in s.raw_attributes})),
                )
            )
    return result


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


def _poster_variants(data: bytes) -> dict[int, bytes]:
    """Crop to the poster ratio and encode the responsive WebP widths."""
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        src_ratio = img.width / img.height
        tgt_ratio = POSTER_W / POSTER_H
        if src_ratio > tgt_ratio:
            new_w = int(img.height * tgt_ratio)
            offset = (img.width - new_w) // 2
            img = img.crop((offset, 0, offset + new_w, img.height))
        elif src_ratio < tgt_ratio:
            new_h = int(img.width / tgt_ratio)
            offset = (img.height - new_h) // 2
            img = img.crop((0, offset, img.width, offset + new_h))
        variants = {}
        for width in POSTER_WIDTHS:
            buffer = io.BytesIO()
            img.resize((width, round(width * POSTER_H / POSTER_W)), Image.LANCZOS).save(
                buffer, "WEBP", quality=POSTER_QUALITY
            )
            variants[width] = buffer.getvalue()
        return variants


def _poster_bytes(sd: SiteData, movie_id: int) -> bytes | None:
    source = sd.posters.get(movie_id)
    try:
        return sd.graph.content(source) if source is not None else None
    except (OSError, ValueError):
        return None


def _poster_url(sd: SiteData, movie_id: int) -> str | None:
    """`/posters/<name>.webp`, linked to resized posters kept in the asset store."""
    if movie_id in sd.poster_urls:
        return sd.poster_urls[movie_id]
    source = sd.posters.get(movie_id)
    url = None
    if source is not None:
        try:
            variants = _poster_variants(sd.graph.content(source))
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            print(f"  poster {source['name']}: {exc}")
            variants = None
        if variants:
            name = source["sha256"][:16]
            for width, data in variants.items():
                stored = sd.graph.read(
                    sd.graph.put_bytes(
                        data, "image/webp", name=f"{name}-{width}.webp", url=source["contentUrl"], compress=False
                    )
                )
                filename = f"{name}.webp" if width == POSTER_W else f"{name}-{width}.webp"
                link = sd.out_dir / "posters" / filename
                link.parent.mkdir(parents=True, exist_ok=True)
                link.unlink(missing_ok=True)
                link.symlink_to(Path("..", "..", "assets", stored["sha256"]))
            url = f"/posters/{name}.webp"
    sd.poster_urls[movie_id] = url
    return url


# ---------------------------------------------------------------------------
# SEO: canonical URLs, sitemap, structured data
# ---------------------------------------------------------------------------


def _sitemap_priority(url: str) -> str:
    """Assign priority based on URL depth/type."""
    path = url[len(BASE_URL) :]
    if path in ("/", ""):
        return "1.0"
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


def _write_schedule_feeds(out: Path, nodes: list[dict], events: list[dict], generated_at: datetime) -> None:
    """Export the complete schedule as JSON-LD."""
    graph = {"@context": "https://schema.org", "@graph": [*nodes, *events]}
    out.with_suffix(".jsonld").write_text(_jsonld(graph) + "\n", encoding="utf-8")


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


def _movie_node(sd: SiteData, movie_id: int, screenings: list[Screening], canonical: str) -> dict:
    movie = sd.movies.get(movie_id)
    slug = sd.film_slugs.get(movie_id)
    url = f"{BASE_URL}/film/{slug}/" if slug else None
    title = (movie.title_sv or movie.title_original if movie else "") or f"Film {movie_id}"
    movie_node: dict = {
        "@type": "Movie",
        "@id": f"{url}#movie" if url else f"{canonical}#movie-{movie_id}",
        "name": title,
    }
    if url:
        movie_node["url"] = url
    if movie is None:
        return movie_node
    languages = movie.spoken_languages if movie.spoken_languages is not None else [movie.original_language]
    languages = [code for code in languages if code and code != "xx"]
    if languages:
        movie_node["inLanguage"] = languages
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
    runtimes = {_screening_runtime(sd, s) for s in screenings} if screenings else {movie.runtime}
    if len(runtimes) == 1 and (runtime := next(iter(runtimes))):
        movie_node["duration"] = f"PT{runtime}M"
    if movie.age_rating:
        movie_node["contentRating"] = movie.age_rating
    return movie_node


def _screening_node(
    sd: SiteData, movie: dict, *, city: str, cinema: str, start: str, end: str, ticket_url: str
) -> dict:
    address = {"@type": "PostalAddress", "addressLocality": city, "addressCountry": "SE"}
    venue = sd.venues.get((city, cinema))
    if venue and venue.address:
        address["streetAddress"] = venue.address
    return {
        "@type": "ScreeningEvent",
        "name": f"{movie['name']} – {cinema}, {city}",
        "startDate": start,
        **({"endDate": end} if end else {}),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"@type": "MovieTheater", "name": cinema, "address": address},
        "workPresented": {"@id": movie["@id"]},
        **({"offers": {"@type": "Offer", "url": ticket_url}} if ticket_url else {}),
    }


def _programme_nodes(
    sd: SiteData, screenings: list[Screening], movie_id: int | None, canonical: str
) -> tuple[list[dict], list[dict]]:
    by_movie = defaultdict(list)
    for s in screenings:
        by_movie[s.tmdb_id].append(s)
    if movie_id is not None:
        by_movie.setdefault(movie_id, [])
    movies = {id_: _movie_node(sd, id_, shows, canonical) for id_, shows in by_movie.items()}
    events = []
    for s in sorted(screenings, key=lambda s: (s.date, s.time)):
        start = datetime.combine(s.date, s.time, tzinfo=SWEDEN_TZ)
        runtime = _screening_runtime(sd, s)
        event = _screening_node(
            sd,
            movies[s.tmdb_id],
            city=s.city,
            cinema=s.cinema_name,
            start=start.isoformat(),
            end=(start + timedelta(minutes=runtime)).isoformat() if runtime else "",
            ticket_url=s.ticket_url,
        )
        p = s.presentation
        formats = sorted(p.experiences & _FORMAT_SYSTEMS)
        if p.dimension != Dimension.UNKNOWN:
            formats.append(p.dimension)
        if p.medium != ProjectionMedium.UNKNOWN:
            formats.append(p.medium)
        formats.extend(sorted(p.projection))
        if formats:
            event["videoFormat"] = " ".join(formats)
        details = [s.screen] if s.screen else []
        details.extend(sorted(p.sound | p.auditorium))
        if details:
            event["description"] = ", ".join(details)
        if s.version.audio.languages and s.version.audio.kind != AudioKind.SILENT:
            event["inLanguage"] = sorted(language.tag for language in s.version.audio.languages)
        if s.version.subtitles.languages:
            event["subtitleLanguage"] = sorted(language.tag for language in s.version.subtitles.languages)
        events.append(event)
    return list(movies.values()), events


def _cinema_nodes(sd: SiteData, city: str, cinema_name: str, canonical: str) -> list[dict]:
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
    return [theater, crumb]


def _collection_nodes(name: str, canonical: str, crumbs: list[tuple[str, str | None]]) -> list[dict]:
    """CollectionPage + breadcrumb for city / genre listing pages."""
    page = {
        "@type": "CollectionPage",
        "name": name,
        "url": canonical,
        "inLanguage": "sv-SE",
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": f"{BASE_URL}/"},
    }
    return [page, _breadcrumb_node(crumbs)]


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
    env.globals["style_version"] = hashlib.sha256((STATIC_DIR / "style.css").read_bytes()).hexdigest()[:12]
    env.globals["synopsis_version"] = hashlib.sha256((STATIC_DIR / "synopsis.js").read_bytes()).hexdigest()[:12]
    env.globals["links_version"] = hashlib.sha256((STATIC_DIR / "links.js").read_bytes()).hexdigest()[:12]
    env.globals["showtimes_version"] = hashlib.sha256((STATIC_DIR / "showtimes.js").read_bytes()).hexdigest()[:12]
    env.globals["newsletter_version"] = hashlib.sha256((STATIC_DIR / "newsletter.js").read_bytes()).hexdigest()[:12]
    env.globals["newsletter_preferences_version"] = hashlib.sha256(
        (STATIC_DIR / "newsletter-preferences.js").read_bytes()
    ).hexdigest()[:12]
    env.globals["font_versions"] = {
        weight: hashlib.sha256((STATIC_DIR / f"FiraSans-{weight}.woff2").read_bytes()).hexdigest()[:12]
        for weight in ("Regular", "SemiBold")
    }
    env.globals["posthog_token"] = os.environ.get("POSTHOG_PROJECT_TOKEN", "").strip()
    env.globals["posthog_host"] = os.environ.get("POSTHOG_HOST", "/salong").strip()
    return env


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _build_newsletter_preferences(env: Environment, out_dir: Path) -> None:
    # Private utility page: deliberately not registered in the public sitemap.
    out_path = out_dir / "nyhetsbrev" / "installningar" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        env.get_template("newsletter-preferences.html").render(og_image=_abs(write_card(out_dir))),
        encoding="utf-8",
    )
    write_page(
        out_path,
        "Inställningar för nyhetsbrevet",
        ["Öppna länken från nyhetsbrevet i en webbläsare med JavaScript för att ändra dina inställningar."],
    )


def _write_newsletter_cities(sd: SiteData) -> None:
    # Public signup allowlist, independent of newsletter subscription state.
    mapping = {city: "newsletter-city-" + _slugify(city) for city in sorted(sd.cities)}
    out_path = sd.out_dir / "i" / "newsletter-cities.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(mapping, ensure_ascii=False) + "\n", encoding="utf-8")


def _build_index(env: Environment, sd: SiteData, festivals: list[dict]) -> None:
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
        og_image=_abs(write_card(sd.out_dir)),
        jsonld=_website_jsonld(),
        active="index",
        groups=groups,
        festivals=festivals,
    )
    out.write_text(html, encoding="utf-8")
    lines = [SITE_DESCRIPTION]
    if festivals:
        lines.append("## Filmfestivaler")
        lines.append("\n".join(f"- {page_link(f['name'] + ' ' + str(f['year']), f['path'])}" for f in festivals))
    for letter, cities in groups:
        lines.append(f"## {letter}")
        lines.append("\n".join(f"- {page_link(c['name'], '/stad/' + c['slug'] + '/')}" for c in cities))
    write_page(out, "Alla biografer i Sverige – vad går på bio just nu?", lines)


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
        version.edition if version.edition != "Inspelad repris" else None,
        presentation.experiences & _FORMAT_SYSTEMS,
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
        speech_languages = {profile[1] for profile in profiles}
        if any(a is None or b is None or a.isdisjoint(b) for a, b in combinations(speech_languages, 2)):
            split_axes.add(1)
        if len({profile[2] for profile in profiles}) > 1:
            split_axes.add(2)
        if any(profile[3] for profile in profiles):
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
                if index == 5 and profile[index] is None and len(known_dimensions) <= 1:
                    continue
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
    movie_id: int | None = None,
) -> list[dict]:
    """Prepare template-ready block dicts for a programme page."""

    now = datetime.now(tz=SWEDEN_TZ)
    day_indices = {day: index for index, day in enumerate(days)}
    filtered = [s for s in screenings if s.date in day_indices]
    variants = _variants(filtered)

    runtimes: dict[tuple[int, str, str], set[int]] = defaultdict(set)
    for s in filtered:
        if runtime := _screening_runtime(sd, s):
            runtimes[(s.tmdb_id, *variants[id(s)])].add(runtime)
    runtime_groups = {}
    for variant, lengths in runtimes.items():
        # Unknown durations share the shortest known block for this variant;
        # they neither bridge known cuts nor acquire a duration in the feed.
        runtime_groups[(*variant, None)] = min(lengths)
        representative = None
        for runtime in sorted(lengths):
            # Bound the whole group's span, not just adjacent differences.
            if representative is None or runtime - representative > 5:
                representative = runtime
            runtime_groups[(*variant, runtime)] = representative

    # (movie, variant, runtime) → (city, cinema) → day → [(time, url)]
    movie_cinemas: dict[tuple[int, str, str, int | None], dict[tuple[str, str], dict[int, list[tuple[time, str]]]]] = (
        defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )
    # Ranking score: each screening contributes more the sooner it is, so films
    # playing a lot in the near columns float to the top rather than films that
    # are blank for weeks and then burst with screenings far in the future.
    movie_score: dict[tuple[int, str, str, int | None], float] = defaultdict(float)
    movie_earliest: dict[tuple[int, str, str, int | None], tuple[date, time]] = {}
    block_profiles: dict[tuple[int, str, str, int | None], tuple] = {}
    screens = {(s.city, s.cinema_name, s.date, s.time, s.ticket_url): s.screen for s in filtered if s.screen}
    for s in filtered:
        day_idx = day_indices[s.date]
        block_key = (s.tmdb_id, *variants[id(s)], _screening_runtime(sd, s))
        block_key = (*block_key[:3], runtime_groups.get(block_key))
        profile = _variant_profile(s)
        block_profiles[block_key] = (
            _merge_profiles(block_profiles[block_key], profile) if block_key in block_profiles else profile
        )
        movie_cinemas[block_key][(s.city, s.cinema_name)][day_idx].append((s.time, s.ticket_url))
        movie_score[block_key] += 1.0 / (1 + day_idx)
        key = (s.date, s.time)
        if block_key not in movie_earliest or key < movie_earliest[block_key]:
            movie_earliest[block_key] = key

    if not movie_cinemas and movie_id is not None:
        # A film page still describes the work when no tickets are published.
        block_key = (movie_id, "", "", sd.movies[movie_id].runtime)
        movie_cinemas[block_key] = {}

    # Films rank by all their variants together; variants of one film stay adjacent.
    film_score: dict[int, float] = defaultdict(float)
    film_earliest: dict[int, tuple[date, time]] = {}
    for (tmdb_id, *_), score in movie_score.items():
        film_score[tmdb_id] += score
    for (tmdb_id, *_), earliest in movie_earliest.items():
        film_earliest[tmdb_id] = min(earliest, film_earliest.get(tmdb_id, earliest))

    def _rank(bk: tuple[int, str, str, int | None]) -> tuple:
        tmdb_id, identity, label, runtime = bk
        return (
            -film_score[tmdb_id],
            film_earliest.get(tmdb_id, (sd.today, time.min)),
            tmdb_id,
            bool(label),
            label.casefold(),
            identity,
            runtime or 0,
        )

    blocks = []
    anchors_by_movie: dict[int, set[str]] = defaultdict(set)
    for s in filtered:
        if s.title:
            anchors_by_movie[s.tmdb_id].add(film_anchor(s.title))
    used_anchors: set[str] = set()
    label_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for block_key in movie_cinemas:
        label_counts[block_key[0]][block_key[2]] += 1
    for block_key in sorted(movie_cinemas, key=_rank):
        tmdb_id, _, variant, runtime = block_key
        movie = sd.movies.get(tmdb_id)
        film_title = movie.title_sv if movie else f"Film {tmdb_id}"
        film_slug = sd.film_slugs.get(tmdb_id, _slugify_sv(film_title))
        anchors = sorted((anchors_by_movie[tmdb_id] | {film_anchor(film_title)}) - used_anchors)
        used_anchors.update(anchors)

        # Movie info line
        mi_parts: list[str] = []
        if movie:
            mi_parts.extend(movie.genres)
            if movie.directors:
                mi_parts.append(", ".join(movie.directors))
            year = movie.release_date[:4] if movie.release_date else ""
            if year:
                mi_parts.append(year)
            if runtime:
                h, m = divmod(runtime, 60)
                mi_parts.append(f"{h} tim. {m} min." if h and m else f"{h} tim." if h else f"{m} min.")
            if movie.age_rating:
                mi_parts.append(movie.age_rating)
        profile = block_profiles.get(block_key)
        if profile and profile[1]:
            mi_parts.append(speech_label(sorted(language.value for language in profile[1])))
        if profile and profile[2] is not None:
            mi_parts.append(
                subtitles_label(sorted(language.value for language in profile[2])) if profile[2] else "Ej textad"
            )
        mi_html = [escape(part) for part in mi_parts]
        if city and movie:
            city_slug = sd.city_slugs.get(city, _slugify_sv(city))
            for index, genre in enumerate(movie.genres):
                genre_slug = _slugify_sv(genre)
                mi_html[index] = f'<a href="/stad/{city_slug}/genre/{genre_slug}/">{escape(genre)}</a>'
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
                    p["screen"] = screens.get((cinema_city, cinema_name, dt.date(), dt.time(), p["url"]))
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
                "anchors": anchors,
                "film_id": "-".join(
                    [
                        film_slug,
                        _slugify_sv(variant) if variant else "",
                        f"{block_key[1]}-{runtime or 'unknown'}" if label_counts[tmdb_id][variant] > 1 else "",
                    ]
                ).strip("-"),
                "film_title": film_title,
                "variant": variant,
                "film_url": film_url,
                "mi": " • ".join(mi_html),
                "mi_text": " • ".join(mi_parts),
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
    page_nodes: list[dict] | None = None,
    og_image: str | None = None,
    og_type: str | None = None,
    clear_filter_url: str | None = None,
    show_next_screening: bool = False,
    movie_id: int | None = None,
    empty_context: list[dict] | None = None,
) -> None:
    programme_note = ""
    in_window = _schedule_screenings(sd, screenings)
    scheduled = in_window
    if show_next_screening and not scheduled and screenings:
        next_show = min(screenings, key=lambda s: (s.date, s.time))
        scheduled = [s for s in screenings if s.date == next_show.date]
        programme_note = (
            "Inga visningar de närmaste två veckorna. "
            f"Nästa visning: {_format_day(next_show.date)} {next_show.date.year} kl. {next_show.time:%H:%M}."
        )
    page_days = _compute_days(scheduled)
    blocks = _prepare_programme_blocks(sd, scheduled, page_days, city=city, movie_id=movie_id)
    if not scheduled:
        programme_note = "Inga kommande visningar publicerade." if show_next_screening else ""
    days = [{"label": _format_day(d), "date": d.isoformat()} for d in page_days]
    movies, events = _programme_nodes(sd, screenings, movie_id, canonical)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_schedule_feeds(out_path, [*movies, *(page_nodes or [])], events, sd.generated_at)
    inline = [*(movies if movie_id is not None else []), *(page_nodes or [])]

    tmpl = env.get_template("program.html")
    html = tmpl.render(
        title=title,
        description=description,
        canonical=canonical,
        jsonld=_jsonld({"@context": "https://schema.org", "@graph": inline}) if inline else None,
        schedule_alternates=True,
        og_image=og_image or _abs(write_card(sd.out_dir)),
        og_type=og_type,
        breadcrumbs=breadcrumbs,
        clear_filter_url=clear_filter_url,
        city=city,
        days=days,
        num_days=max(1, len(page_days)),
        blocks=blocks,
        programme_note=programme_note,
        empty_context=empty_context or [],
    )
    out_path.write_text(html, encoding="utf-8")
    if scheduled is not in_window:
        blocks = _prepare_programme_blocks(sd, in_window, [], city=city, movie_id=movie_id)
        days = []
        programme_note = "Inga visningar de närmaste två veckorna."
    write_programme(out_path, title, blocks, days, note=programme_note, empty_context=empty_context)


def _build_programme_pages(env: Environment, sd: SiteData) -> None:
    print("Building programme pages…")

    by_city: dict[str, list[Screening]] = defaultdict(list)
    by_city_cinema: dict[tuple[str, str], list[Screening]] = defaultdict(list)
    by_film: dict[int, list[Screening]] = defaultdict(list)
    by_city_genre: dict[tuple[str, str], list[Screening]] = defaultdict(list)
    by_city_film: dict[tuple[str, int], list[Screening]] = defaultdict(list)

    for city_name in sd.city_slugs:
        by_city[city_name] = []
    for pair in sd.cinema_slugs:
        by_city_cinema[pair] = []
    for movie_id in sd.movies:
        by_film[movie_id] = []
    for city_name, movie_id in sd.city_films:
        by_city_film[(city_name, movie_id)] = []
        for genre in sd.movies[movie_id].genres:
            by_city_genre[(city_name, genre)] = []

    for s in sd.screenings:
        by_city[s.city].append(s)
        by_city_cinema[(s.city, s.cinema_name)].append(s)
        movie = sd.movies.get(s.tmdb_id)
        if movie and movie.title_sv:
            by_film[s.tmdb_id].append(s)
            by_city_film[(s.city, s.tmdb_id)].append(s)
            for genre in movie.genres:
                by_city_genre[(s.city, genre)].append(s)

    # /stad/{slug}/
    for city_name, city_screenings in sorted(by_city.items()):
        slug = sd.city_slugs[city_name]
        print(f"  /stad/{slug}/")
        out_path = sd.out_dir / "stad" / slug / "index.html"
        canonical = _register(sd, out_path)
        scheduled = _schedule_screenings(sd, city_screenings)
        n_films = len({s.tmdb_id for s in scheduled})
        n_cinemas = len({s.cinema_name for s in scheduled})
        title = f"Bio i {city_name} – program för alla biografer"
        _write_programme(
            env,
            sd,
            city_screenings,
            title=title,
            og_image=_abs(write_card(sd.out_dir, title=f"Bio i {city_name}", subtitle="Program för alla biografer")),
            description=(
                f"Bio i {city_name}: se speltider för {n_films} {'film' if n_films == 1 else 'filmer'} "
                f"på {n_cinemas} {'biograf' if n_cinemas == 1 else 'biografer'} "
                "de närmaste två veckorna. Jämför program och hitta biljetter."
                if scheduled
                else f"Bio i {city_name}. Inga publicerade visningar de närmaste två veckorna."
            ),
            canonical=canonical,
            page_nodes=_collection_nodes(
                f"På bio i {city_name}",
                canonical,
                [(SITE_NAME, f"{BASE_URL}/"), (city_name, canonical)],
            ),
            breadcrumbs=f" / {city_name}",
            out_path=out_path,
            city=city_name,
            empty_context=[
                {
                    "name": cinema_name,
                    "url": f"/stad/{slug}/{cinema_slug}/",
                    "address": sd.venues[(city_name, cinema_name)].address
                    if (city_name, cinema_name) in sd.venues
                    else "",
                }
                for (cinema_city, cinema_name), cinema_slug in sorted(sd.cinema_slugs.items())
                if cinema_city == city_name
            ],
        )

    # /stad/{slug}/{cinema-slug}/
    for (city_name, cinema_name), cinema_screenings in sorted(by_city_cinema.items()):
        city_slug = sd.city_slugs[city_name]
        cinema_slug = sd.cinema_slugs[(city_name, cinema_name)]
        out_path = sd.out_dir / "stad" / city_slug / cinema_slug / "index.html"
        canonical = _register(sd, out_path)
        location = "" if re.search(rf"\b{re.escape(city_name)}\b", cinema_name, re.IGNORECASE) else f" i {city_name}"
        n_films = len({s.tmdb_id for s in _schedule_screenings(sd, cinema_screenings)})
        _write_programme(
            env,
            sd,
            cinema_screenings,
            title=f"{cinema_name}{location} – program och speltider",
            og_image=_abs(
                write_card(
                    sd.out_dir,
                    title=cinema_name,
                    subtitle=f"{city_name} · Program och speltider",
                )
            ),
            description=(
                f"{cinema_name}{location}: program och speltider för "
                f"{n_films} {'film' if n_films == 1 else 'filmer'} de närmaste två veckorna. "
                "Se visningar och hitta biljetter."
                if n_films
                else f"{cinema_name}{location}. Inga publicerade visningar de närmaste två veckorna."
            ),
            canonical=canonical,
            page_nodes=_cinema_nodes(sd, city_name, cinema_name, canonical),
            breadcrumbs=f' / <a href="/stad/{city_slug}/">{city_name}</a> / {cinema_name}',
            clear_filter_url=f"/stad/{city_slug}/",
            out_path=out_path,
            city=city_name,
            empty_context=[
                {
                    "name": cinema_name,
                    "url": f"/stad/{city_slug}/",
                    "address": sd.venues[(city_name, cinema_name)].address
                    if (city_name, cinema_name) in sd.venues
                    else "",
                }
            ],
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
            og_image=_abs(
                write_card(
                    sd.out_dir,
                    title=f"{genre} på bio",
                    subtitle=f"{city_name} · Program och speltider",
                )
            ),
            description=(
                f"{genre}-filmer som visas på bio i {city_name} just nu, med speltider och biografer."
                if _schedule_screenings(sd, genre_screenings)
                else f"{genre} på bio i {city_name}. Inga publicerade visningar de närmaste två veckorna."
            ),
            canonical=canonical,
            page_nodes=_collection_nodes(
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
    for (city_name, movie_id), city_film_screenings in sorted(by_city_film.items()):
        movie = sd.movies[movie_id]
        film_title = movie.title_sv
        city_slug = sd.city_slugs[city_name]
        film_slug = sd.film_slugs[movie_id]
        out_path = sd.out_dir / "stad" / city_slug / "film" / film_slug / "index.html"
        canonical = _register(sd, out_path)
        n_cinemas = len({s.cinema_name for s in _schedule_screenings(sd, city_film_screenings)})
        if n_cinemas:
            description = (
                f"Se speltider för {film_title} i {city_name}. "
                f"Visas på {n_cinemas} {'biograf' if n_cinemas == 1 else 'biografer'} "
                "de närmaste två veckorna, med länkar till biljetter."
            )
        else:
            description = f"Speltider för {film_title} i {city_name}. Inga visningar de närmaste två veckorna."
        og_image = _abs(
            write_card(
                sd.out_dir,
                title=film_title,
                subtitle=f"Speltider i {city_name}",
                poster=_poster_bytes(sd, movie_id),
            )
        )
        _write_programme(
            env,
            sd,
            city_film_screenings,
            title=f"{film_title} i {city_name} – speltider på bio",
            description=description,
            canonical=canonical,
            page_nodes=[_breadcrumb_node([(SITE_NAME, f"{BASE_URL}/"), (film_title, canonical)])],
            og_image=og_image,
            og_type="video.movie",
            breadcrumbs=f' / <a href="/stad/{city_slug}/">{city_name}</a> / {film_title}',
            clear_filter_url=f"/stad/{city_slug}/",
            out_path=out_path,
            city=city_name,
            show_next_screening=True,
            movie_id=movie_id,
        )

    # /film/{slug}/
    for movie_id, film_screenings in sorted(by_film.items()):
        movie = sd.movies[movie_id]
        film_title = movie.title_sv
        slug = sd.film_slugs[movie_id]
        out_path = sd.out_dir / "film" / slug / "index.html"
        canonical = _register(sd, out_path)
        n_cities = len({s.city for s in film_screenings})
        if movie and movie.overview_sv:
            description = movie.overview_sv[:155].rstrip()
            if len(movie.overview_sv) > 155:
                description += "…"
        elif film_screenings:
            description = (
                f"Speltider för {film_title} på biografer i hela Sverige — "
                f"visas i {n_cities} {'stad' if n_cities == 1 else 'städer'}."
            )
        else:
            description = f"{film_title}. Inga kommande visningar publicerade."
        og_image = _abs(
            write_card(
                sd.out_dir,
                title=film_title,
                subtitle="Speltider i Sverige",
                poster=_poster_bytes(sd, movie_id),
            )
        )
        _write_programme(
            env,
            sd,
            film_screenings,
            title=f"{film_title} – speltider på bio i Sverige",
            description=description,
            canonical=canonical,
            page_nodes=[_breadcrumb_node([(SITE_NAME, f"{BASE_URL}/"), (film_title, canonical)])],
            og_image=og_image,
            og_type="video.movie",
            breadcrumbs=f" / {film_title}",
            clear_filter_url="/",
            out_path=out_path,
            show_next_screening=True,
            movie_id=movie_id,
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
        lines.append("Content-Signal: ai-train=no, search=yes, ai-input=yes")
        lines.append("Allow: /")
        lines.append("")
    lines.append(f"Sitemap: {BASE_URL}/sitemap.xml")
    lines.append("")
    (out_dir / "robots.txt").write_text("\n".join(lines), encoding="utf-8")


def _write_llms(sd: SiteData) -> None:
    """Describe public representations and list only feeds generated in this build."""
    lines = [
        "# allabiografer.se",
        "",
        "> Cinema programmes across Sweden, with showtimes and ticket links.",
        "",
        "## Access",
        "",
        "Public pages are server-rendered HTML. A Markdown representation is available at each page's index.md URL, "
        "for example /stad/{city-slug}/index.md. The homepage is /index.md.",
        "",
        "The same page URL also serves Markdown for Accept: text/markdown when its positive quality value is at least "
        "HTML's. Explicit ties prefer Markdown; wildcard-only requests keep HTML. Responses vary on Accept. "
        "HTML alternate links and HTTP Link headers advertise available representations.",
        "",
        "## Programme indexes",
        "",
        f"- {link('Cities', BASE_URL + '/index.md')}: Links to generated city programmes.",
        f"- {link('Sitemap', BASE_URL + '/sitemap.xml')}: Generated public HTML page URLs.",
        "",
        "## Feed contract and limitations",
        "",
        "Each programme has an index.jsonld (Schema.org) with all available screenings. "
        "Fetch these URLs directly. Markdown lists the next 14 local calendar days only. "
        "An empty feed does not prove nothing is showing; failed or empty parses can retain older listings.",
        "",
        "## City schedule feeds",
        "",
    ]
    lines.extend(
        f"- {link(city, BASE_URL + '/stad/' + sd.city_slugs[city] + '/index.jsonld')}"
        for city in sorted(sd.cities, key=_swedish_sort_key)
    )
    (sd.out_dir / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    src = STATIC_DIR
    if src.exists():
        dest = out_dir / "i"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build(sd: SiteData) -> int:
    """Write every page for `sd` to `sd.out_dir`, replacing it. Returns the number of pages."""
    out_dir = sd.out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    _copy_static(out_dir)
    env = _make_env()

    _build_index(env, sd, [])
    _build_programme_pages(env, sd)
    _build_newsletter_preferences(env, out_dir)
    _write_newsletter_cities(sd)

    _write_robots(out_dir)
    _write_llms(sd)
    _write_sitemap(sd)
    _write_redirects(sd)
    return len(set(sd.sitemap_urls))


REDIRECT = """<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flyttad – allabiografer.se</title>
<meta name="robots" content="noindex, follow">
<link rel="canonical" href="{canonical}">
<meta http-equiv="refresh" content="0; url={href}">
<script>location.replace({script});</script>
<link href="/i/style.css" rel="stylesheet" type="text/css">
</head>
<body>
<main>
<p>Sidan har flyttat till <a href="{href}">{label}</a>.</p>
</main>
</body>
</html>
"""


def _write_redirect(sd: SiteData, old: str, url: str) -> None:
    """A page at `old` sending visitors to `url`; aliases never enter internal links or sitemaps.

    The meta refresh moves browsers and crawlers; the canonical link passes the page's
    standing to its new address; the script also keeps the fragment, which a refresh drops.
    """
    page = sd.out_dir / old.strip("/") / "index.html"
    # A rendered page wins over a former name that now belongs to it.
    if page.exists():
        return
    href = quote(url)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        REDIRECT.format(
            href=html.escape(href),
            canonical=html.escape(BASE_URL + href),
            label=html.escape(BASE_URL.removeprefix("https://") + url),
            script=json.dumps(href) + " + location.hash",
        ),
        encoding="utf-8",
    )


def _write_redirects(sd: SiteData) -> None:
    """Former film and cinema slugs, to their current pages."""
    targets: dict[str, set[str]] = defaultdict(set)
    for page in (sd.out_dir / "film").glob("*/index.html"):
        targets[page.parent.name].add("/film")
    for page in (sd.out_dir / "stad").glob("*/film/*/index.html"):
        targets[page.parent.name].add("/" + page.parent.parent.relative_to(sd.out_dir).as_posix())
    for old, current in sorted(sd.film_aliases.items()):
        # Redirect only to pages actually rendered. A city with no remaining
        # screenings must not acquire an alias-to-missing-page redirect chain.
        for prefix in sorted(targets[current]):
            _write_redirect(sd, f"{prefix}/{old}/", f"{prefix}/{current}/")
    for (city, old), current in sorted(sd.cinema_aliases.items()):
        city_slug = sd.city_slugs[city]
        if old != current and (sd.out_dir / "stad" / city_slug / current / "index.html").exists():
            _write_redirect(sd, f"/stad/{city_slug}/{old}/", f"/stad/{city_slug}/{current}/")
