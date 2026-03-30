"""Build the static site from screening + movie data.

Usage::

    uv run build <output-dir>

Outputs to the given directory with this URL structure:

    /                           - city A-O index
    /premiarer/                 - upcoming premieres
    /filmer/                    - all films currently showing
    /stad/{slug}/               - programme for a city
    /stad/{slug}/{cinema-slug}/ - programme for a cinema
    /film/{slug}/               - programme for a film (nationwide)
"""

import argparse
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from store import (
    MOVIES_DIR,
    SCREENINGS_FILE,
    VENUES_DIR,
    Movie,
    Screening,
    Venue,
    movie_poster_path,
    read_movie,
    read_screenings,
    read_venues,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SWEDEN_TZ = ZoneInfo("Europe/Stockholm")
TEMPLATE_DIR = Path(__file__).parent / "templates"


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


def _compute_time_positions(
    times: list[tuple[time, str]],
) -> list[dict]:
    """Return list of dicts {label, url, left, top, past} for template."""
    if not times:
        return []

    sorted_times = sorted(times, key=lambda t: (t[0].hour, t[0].minute))

    cell_w = 200
    label_w = 45
    row_h = 22.5
    pad = 5

    result: list[dict] = []
    row_rights: list[float] = []

    for t, url in sorted_times:
        minutes = t.hour * 60 + t.minute
        frac = max(0, (minutes - 360)) / 1080
        left = pad + frac * (cell_w - label_w - 2 * pad)
        left = max(pad, min(left, cell_w - label_w - pad))

        placed = False
        for row_idx, right in enumerate(row_rights):
            if left >= right:
                row_rights[row_idx] = left + label_w
                top = pad + row_idx * row_h + pad / 2
                result.append({"label": t.strftime("%H:%M"), "url": url, "left": round(left, 1), "top": round(top, 2)})
                placed = True
                break
        if not placed:
            row_idx = len(row_rights)
            row_rights.append(left + label_w)
            top = pad + row_idx * row_h + pad / 2
            result.append({"label": t.strftime("%H:%M"), "url": url, "left": round(left, 1), "top": round(top, 2)})

    return result


def _cell_min_height(positions: list[dict]) -> float:
    if not positions:
        return 0
    max_top = max(p["top"] for p in positions)
    return max_top + 22.5 + 5


# ---------------------------------------------------------------------------
# Site data
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class SiteData:
    out_dir: Path = field(default_factory=lambda: Path("build"))
    screenings: list[Screening] = field(default_factory=list)
    movies: dict[int, Movie] = field(default_factory=dict)
    poster_files: dict[int, Path] = field(default_factory=dict)
    cities: dict[str, int] = field(default_factory=dict)
    today: date = field(default_factory=lambda: datetime.now(tz=SWEDEN_TZ).date())
    days: list[date] = field(default_factory=list)
    venues: dict[tuple[str, str], Venue] = field(default_factory=dict)  # (city, name) → Venue
    city_slugs: dict[str, str] = field(default_factory=dict)
    cinema_slugs: dict[tuple[str, str], str] = field(default_factory=dict)
    film_slugs: dict[str, str] = field(default_factory=dict)


def _load_data(out_dir: Path) -> SiteData:
    sd = SiteData(out_dir=out_dir)
    sd.today = datetime.now(tz=SWEDEN_TZ).date()

    print("Reading screenings…")
    sd.screenings = read_screenings(path=SCREENINGS_FILE)
    print(f"  {len(sd.screenings)} screenings")

    # Today through end of next week (same weekday)
    sd.days = [sd.today + timedelta(days=i) for i in range(8)]

    tmdb_ids: set[int] = set()
    for s in sd.screenings:
        tmdb_ids.add(s.tmdb_id)
        sd.cities[s.city] = sd.cities.get(s.city, 0) + 1

    print("Reading movie metadata…")
    for tid in tmdb_ids:
        m = read_movie(tid, movies_dir=MOVIES_DIR)
        if m:
            sd.movies[tid] = m
        p = movie_poster_path(tid, movies_dir=MOVIES_DIR)
        if p:
            sd.poster_files[tid] = p
    print(f"  {len(sd.movies)} movies, {len(sd.poster_files)} posters")

    print("Reading venues…")
    for v in read_venues(data_dir=VENUES_DIR):
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


def _process_poster(src: Path, dest: Path) -> None:
    """Resize and convert a poster to @2x WebP."""
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
        img = img.resize((POSTER_W, POSTER_H), Image.LANCZOS)
        img.save(dest, "WEBP", quality=POSTER_QUALITY)


def _poster_url(sd: SiteData, tmdb_id: int) -> str | None:
    src = sd.poster_files.get(tmdb_id)
    if not src:
        return None
    dest = sd.out_dir / "posters" / f"{tmdb_id}.webp"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _process_poster(src, dest)
    return f"/posters/{tmdb_id}.webp"


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


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

    tmpl = env.get_template("index.html")
    html = tmpl.render(
        title="Alla biografer i Sverige",
        active="index",
        groups=groups,
    )
    out = sd.out_dir / "index.html"
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

    tmpl = env.get_template("premiarer.html")
    html = tmpl.render(
        title="Alla biografer i Sverige",
        active="premiarer",
        date_groups=date_groups,
    )
    out = sd.out_dir / "premiarer" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
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

    tmpl = env.get_template("filmer.html")
    html = tmpl.render(
        title="Alla filmer i Sverige",
        active="filmer",
        films=films,
    )
    out = sd.out_dir / "filmer" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Programme page data preparation
# ---------------------------------------------------------------------------


def _prepare_programme_blocks(
    sd: SiteData,
    screenings: list[Screening],
    *,
    city: str | None = None,
) -> list[dict]:
    """Prepare template-ready block dicts for a programme page."""

    now = datetime.now(tz=SWEDEN_TZ)
    day_set = set(sd.days)
    filtered = [s for s in screenings if s.date in day_set]

    # movie → (city, cinema) → day → [(time, url)]
    movie_cinemas: dict[int, dict[tuple[str, str], dict[int, list[tuple[time, str]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    movie_counts: dict[int, int] = defaultdict(int)

    for s in filtered:
        try:
            day_idx = sd.days.index(s.date)
        except ValueError:
            continue
        movie_cinemas[s.tmdb_id][(s.city, s.cinema_name)][day_idx].append((s.time, s.ticket_url))
        movie_counts[s.tmdb_id] += 1

    blocks = []
    for tmdb_id in sorted(movie_cinemas, key=lambda tid: -movie_counts[tid]):
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
                ar = movie.age_rating
                if ar.isdigit():
                    mi_parts.append(f"Från {ar} år")
                elif ar.upper() == "BTL":
                    mi_parts.append("Barntillåten")
                else:
                    mi_parts.append(ar)

        desc = ""
        full_desc = ""
        if movie and movie.overview_sv:
            full_desc = movie.overview_sv
            desc = full_desc[:200] + "…" if len(full_desc) > 200 else full_desc

        cinema_map = movie_cinemas[tmdb_id]
        cinema_rows = []
        for cinema_city, cinema_name in sorted(cinema_map):
            day_times = cinema_map[(cinema_city, cinema_name)]

            cells = []
            max_h = 55.0
            for day_idx in range(len(sd.days)):
                raw = day_times.get(day_idx, [])
                positions = _compute_time_positions(raw)
                # Mark past times
                for p in positions:
                    dt = datetime.combine(sd.days[day_idx], time(*map(int, p["label"].split(":"))), tzinfo=SWEDEN_TZ)
                    p["past"] = dt < now
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

        blocks.append(
            {
                "poster_url": _poster_url(sd, tmdb_id),
                "film_title": film_title,
                "film_url": f"/film/{film_slug}/",
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
    city: str | None = None,
) -> None:
    blocks = _prepare_programme_blocks(sd, screenings, city=city)
    days = [{"label": _format_day(d)} for d in sd.days]

    tmpl = env.get_template("program.html")
    html = tmpl.render(
        title=title,
        breadcrumbs=breadcrumbs,
        days=days,
        num_days=len(sd.days),
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

    for s in sd.screenings:
        by_city[s.city].append(s)
        by_city_cinema[(s.city, s.cinema_name)].append(s)
        movie = sd.movies.get(s.tmdb_id)
        if movie and movie.title_sv:
            by_film[movie.title_sv].append(s)
            for genre in movie.genres:
                by_city_genre[(s.city, genre)].append(s)

    # /stad/{slug}/
    for city_name, city_screenings in sorted(by_city.items()):
        slug = sd.city_slugs[city_name]
        print(f"  /stad/{slug}/")
        _write_programme(
            env,
            sd,
            city_screenings,
            title=f"Föreställningar i {city_name}",
            breadcrumbs=f" / {city_name}",
            out_path=sd.out_dir / "stad" / slug / "index.html",
            city=city_name,
        )

    # /stad/{slug}/{cinema-slug}/
    for (city_name, cinema_name), cinema_screenings in sorted(by_city_cinema.items()):
        city_slug = sd.city_slugs[city_name]
        cinema_slug = sd.cinema_slugs[(city_name, cinema_name)]
        _write_programme(
            env,
            sd,
            cinema_screenings,
            title=f"Föreställningar på {cinema_name} i {city_name}",
            breadcrumbs=f' / <a href="/stad/{city_slug}/">{city_name}</a> / {cinema_name}',
            out_path=sd.out_dir / "stad" / city_slug / cinema_slug / "index.html",
            city=city_name,
        )

    # /stad/{slug}/genre/{genre-slug}/
    for (city_name, genre), genre_screenings in sorted(by_city_genre.items()):
        city_slug = sd.city_slugs[city_name]
        genre_slug = _slugify_sv(genre)
        _write_programme(
            env,
            sd,
            genre_screenings,
            title=f"{genre} i {city_name}",
            breadcrumbs=f' / <a href="/stad/{city_slug}/">{city_name}</a> / {genre}',
            out_path=sd.out_dir / "stad" / city_slug / "genre" / genre_slug / "index.html",
            city=city_name,
        )

    # /film/{slug}/
    for film_title, film_screenings in sorted(by_film.items()):
        slug = sd.film_slugs[film_title]
        _write_programme(
            env,
            sd,
            film_screenings,
            title=f"Föreställningar av {film_title}",
            breadcrumbs=f" / {film_title}",
            out_path=sd.out_dir / "film" / slug / "index.html",
        )


# ---------------------------------------------------------------------------
# Copy static assets
# ---------------------------------------------------------------------------


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

    print(f"\nDone. Output in {out_dir}/")
