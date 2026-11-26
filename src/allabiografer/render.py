"""Render a merged Dataset to a static website.

Pages are HTML with the page's entities embedded as JSON-LD. Posters are resized once and
stored as ImageObjects in the asset store. The site links `/assets/<sha256>` to the stored
file, so image bytes stay in the store and only the posters a page uses are exposed.
"""

import io
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from . import session as http
from .graph import Graph, media_type
from .model.version import Language
from .sources._shared import STOCKHOLM

SITE = "https://allabiografer.se"
POSTER_WIDTH = 500
# Days listed on city and film pages, from the first listed day; a cinema page lists its whole programme.
CITY_DAYS = 7
FILM_DAYS = 14
# Days of screenings embedded as JSON-LD; the HTML lists them all.
EMBEDDED_DAYS = 14
_LANGUAGES = {language.tag: str(language) for language in Language}
_WEEKDAYS = ["mån", "tis", "ons", "tors", "fre", "lör", "sön"]
_MONTHS = ["jan", "feb", "mars", "apr", "maj", "juni", "juli", "aug", "sep", "okt", "nov", "dec"]
_STYLE = """
:root { color-scheme: light dark; font-family: system-ui, sans-serif; line-height: 1.45; }
body { max-width: 60rem; margin: 0 auto; padding: 1rem; }
a { color: inherit; }
header nav, footer { font-size: .9rem; opacity: .8; }
h1 { margin: .5rem 0 1rem; }
ul.list { columns: 16rem; padding-left: 1.2rem; }
.film { display: grid; grid-template-columns: 7rem 1fr; gap: 1rem; margin: 1.5rem 0; }
.film img, .poster { width: 100%; height: auto; border-radius: .3rem; }
.hero { display: grid; grid-template-columns: 12rem 1fr; gap: 1.5rem; }
.day { margin: .4rem 0; }
.day b { display: inline-block; min-width: 7rem; }
.show { display: inline-block; margin-right: .8rem; white-space: nowrap; }
.tag { font-size: .75rem; opacity: .75; }
@media (max-width: 40rem) { .film { grid-template-columns: 4.5rem 1fr; } .hero { grid-template-columns: 1fr; } }
"""


def slugify(text: str) -> str:
    """URL slug preserving å ä ö."""
    text = re.sub(r"[^\wåäö\s-]", "", text.lower().strip())
    return re.sub(r"[-\s]+", "-", text).strip("-") or "unnamed"


@dataclass
class Show:
    start: datetime
    url: str
    cinema: "Cinema"
    film: "Film"
    labels: list[str]


@dataclass
class Film:
    slug: str
    entity: dict
    poster: str | None = None
    shows: list[Show] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.entity["name"]


@dataclass
class Cinema:
    slug: str
    entity: dict
    city: "City"
    shows: list[Show] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.entity["name"]


@dataclass
class City:
    slug: str
    entity: dict
    cinemas: list[Cinema] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.entity["name"]


def _labels(screening: dict) -> list[str]:
    """Short version labels: spoken and subtitle languages, then picture formats."""
    labels = []
    spoken = [_LANGUAGES.get(tag, tag) for tag in screening.get("inLanguage", [])]
    if spoken:
        labels.append(f"{'/'.join(spoken)} tal")
    if "subtitleLanguage" in screening:
        subtitles = [_LANGUAGES.get(tag, tag).lower() for tag in screening["subtitleLanguage"]]
        labels.append(f"{'/'.join(subtitles)} text" if subtitles else "otextad")
    return labels + screening.get("videoFormat", [])


def _original(graph: Graph, film_path: Path, image, session, downloaded: dict) -> dict | None:
    """The stored poster: a captured ImageObject, or a source URL downloaded into the store once."""
    if isinstance(image, dict):
        return graph.read(graph.resolve(film_path, image))
    if not isinstance(image, str) or not image.startswith(("http://", "https://")):
        return None
    found = downloaded.get(image)
    if found is None:
        try:
            response = session.get(image, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            return None
        media = media_type(image, response.headers.get("Content-Type", ""))
        if not media.startswith("image/"):
            return None
        found = graph.put_bytes(response.content, media, name=Path(image).name, url=image)
        downloaded[image] = found
    return graph.read(found)


def _poster(graph: Graph, film_path: Path, image, session, downloaded: dict) -> str | None:
    """A resized poster in the asset store, as `/assets/<sha256>`; None when unavailable."""
    source = _original(graph, film_path, image, session, downloaded)
    if source is None:
        return None
    try:
        with Image.open(io.BytesIO(graph.content(source))) as opened:
            picture = ImageOps.exif_transpose(opened).convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError):
        return None
    if picture.width > POSTER_WIDTH:
        picture = picture.resize((POSTER_WIDTH, round(picture.height * POSTER_WIDTH / picture.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    picture.save(buffer, "WEBP", quality=80)
    resized = graph.put_bytes(
        buffer.getvalue(), "image/webp", name=f"{source['name']}.webp", url=source["contentUrl"], compress=False
    )
    return f"/assets/{graph.read(resized)['sha256']}"


def _downloaded(graph: Graph) -> dict[str, Path]:
    """Posters already in the store, by the source URL they were downloaded from."""
    found = {}
    for path in graph.schema.glob("ImageObject/*.jsonld"):
        url = graph.read(path).get("isBasedOn")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            found[url] = path
    return found


def load(graph: Graph, merged: Path, today: date) -> tuple[list[City], list[Film]]:
    dataset = graph.read(merged)
    downloaded = _downloaded(graph)
    session = http.session()
    cities: dict[Path, City] = {}
    cinemas: dict[Path, Cinema] = {}
    for reference in dataset["about"]:
        path = graph.resolve(merged, reference)
        entity = graph.read(path)
        city_path = graph.resolve(path, entity["containedInPlace"])
        if city_path not in cities:
            city = graph.read(city_path)
            cities[city_path] = City(slugify(city["name"]), city)
        city = cities[city_path]
        cinemas[path] = Cinema(slugify(entity["name"]), entity, city)
        city.cinemas.append(cinemas[path])
    films: dict[Path, Film] = {}
    film_images = {}
    screenings = []
    for reference in dataset["hasPart"]:
        path = graph.resolve(merged, reference)
        entity = graph.read(path)
        if entity["@type"] == "Movie":
            slug = next(item["value"] for item in entity["identifier"] if item["propertyID"] == "allabiografer:film")
            films[path] = Film(slug, entity)
            film_images[path] = entity.get("image")
        else:
            screenings.append((path, entity))
    for path, entity in screenings:
        start = datetime.fromisoformat(entity["startDate"]).astimezone(STOCKHOLM)
        if start.date() < today:
            continue
        film = films[graph.resolve(path, entity["workPresented"])]
        cinema = cinemas[graph.resolve(path, entity["location"])]
        show = Show(start, entity["offers"]["url"], cinema, film, _labels(entity))
        film.shows.append(show)
        cinema.shows.append(show)
    for item in [*films.values(), *cinemas.values()]:
        item.shows.sort(key=lambda show: (show.start, show.cinema.name, show.film.name))
    showing = [film for film in films.values() if film.shows]
    # Only films on the schedule need a poster.
    for path, film in films.items():
        if film.shows:
            film.poster = _poster(graph, path, film_images[path], session, downloaded)
    ordered_cities = sorted(
        (city for city in cities.values() if any(cinema.shows for cinema in city.cinemas)), key=lambda c: c.name
    )
    for city in ordered_cities:
        city.cinemas.sort(key=lambda cinema: cinema.name)
    return ordered_cities, sorted(showing, key=lambda film: film.name.casefold())


def _day(day: date) -> str:
    return f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"


def _schedule(shows: list[Show], label) -> str:
    """Showtimes grouped by day: a booking link per time, then what the row adds (film or cinema)."""
    by_day = defaultdict(list)
    for show in shows:
        by_day[show.start.date()].append(show)
    lines = []
    for day, items in sorted(by_day.items()):
        entries = " ".join(
            f'<span class="show"><a href="{escape(show.url)}">{show.start:%H:%M}</a> {label(show)}'
            + (f' <span class="tag">{escape(", ".join(show.labels))}</span>' if show.labels else "")
            + "</span>"
            for show in items
        )
        lines.append(f'<div class="day"><b>{_day(day)}</b> {entries}</div>')
    return "\n".join(lines)


def _upcoming(shows: list[Show], days: int) -> list[Show]:
    """Shows within `days` of the first one, so a film opening later still lists its premiere week."""
    if not shows:
        return []
    until = shows[0].start.date() + timedelta(days=days)
    return [show for show in shows if show.start.date() < until]


def _page(title: str, body: str, *, path: str, entity: dict | None = None, crumbs=()) -> str:
    canonical = f"{SITE}{path}"
    nav = " &rsaquo; ".join(
        ['<a href="/">Alla biografer</a>', *(f'<a href="{href}">{escape(name)}</a>' for name, href in crumbs)]
    )
    data = ""
    if entity is not None:
        encoded = json.dumps(entity, ensure_ascii=False).replace("</", "<\\/")
        data = f'<script type="application/ld+json">{encoded}</script>'
    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} – Alla biografer</title>
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="/style.css">
{data}
</head>
<body>
<header><nav>{nav}</nav></header>
<main>
<h1>{escape(title)}</h1>
{body}
</main>
<footer><p>Uppdaterad {datetime.now(STOCKHOLM):%Y-%m-%d %H:%M}. <a href="https://github.com/ngalaiko/allabiografer.se">Källkod</a></p></footer>
</body>
</html>
"""


def _film_entity(film: Film) -> dict:
    entity = {key: value for key, value in film.entity.items() if key not in {"@id", "isBasedOn", "identifier"}}
    entity["@id"] = entity["url"] = f"{SITE}/film/{film.slug}/"
    if film.poster:
        entity["image"] = f"{SITE}{film.poster}"
    return entity


def _cinema_entity(cinema: Cinema) -> dict:
    entity = {
        key: value for key, value in cinema.entity.items() if key not in {"@id", "identifier", "containedInPlace"}
    }
    url = f"{SITE}/stad/{cinema.city.slug}/{cinema.slug}/"
    return entity | {
        "@context": "https://schema.org",
        "@id": url,
        "containedInPlace": {"@type": "City", "name": cinema.city.name},
    }


def _events(shows: list[Show], *, film: bool = True, cinema: bool = True) -> list[dict]:
    """Screenings as JSON-LD for the next EMBEDDED_DAYS; the film and venue are linked, not repeated.

    The page's own film or cinema is omitted from each event: it is the page's main entity.
    """
    if not shows:
        return []
    until = shows[0].start.date() + timedelta(days=EMBEDDED_DAYS)
    return [
        {
            "@type": "ScreeningEvent",
            "startDate": show.start.isoformat(),
            **({"workPresented": {"@id": f"{SITE}/film/{show.film.slug}/"}} if film else {}),
            **({"location": {"@id": f"{SITE}/stad/{show.cinema.city.slug}/{show.cinema.slug}/"}} if cinema else {}),
            "url": show.url,
        }
        for show in shows
        if show.start.date() < until
    ]


def render(graph: Graph, merged: Path, out: Path, *, today: date | None = None) -> int:
    """Write the site for `merged` to `out`, replacing it. Returns the number of pages."""
    today = today or datetime.now(STOCKHOLM).date()
    cities, films = load(graph, merged, today)
    staging = out.with_name(f".{out.name}.tmp")
    shutil.rmtree(staging, ignore_errors=True)
    pages = {}

    film_list = "".join(
        '<div class="film">'
        + (f'<img src="{film.poster}" alt="" loading="lazy" width="112">' if film.poster else "<span></span>")
        + f'<div><a href="/film/{film.slug}/"><b>{escape(film.name)}</b></a><br>'
        f"<small>{len({show.cinema.slug for show in film.shows})} biografer, "
        f"{len(film.shows)} visningar</small></div></div>"
        for film in films
    )
    city_list = "".join(f'<li><a href="/stad/{city.slug}/">{escape(city.name)}</a></li>' for city in cities)
    pages["index.html"] = _page(
        "Bio i hela Sverige",
        f'<h2>Städer</h2><ul class="list">{city_list}</ul><h2>Filmer</h2>{film_list}',
        path="/",
        entity={"@context": "https://schema.org", "@type": "WebSite", "name": "Alla biografer", "url": f"{SITE}/"},
    )

    for city in cities:
        showing = [cinema for cinema in city.cinemas if cinema.shows]
        body = "".join(
            f'<h2><a href="/stad/{city.slug}/{cinema.slug}/">{escape(cinema.name)}</a></h2>'
            + _schedule(
                _upcoming(cinema.shows, CITY_DAYS),
                lambda show: f'<a href="/film/{show.film.slug}/">{escape(show.film.name)}</a>',
            )
            for cinema in showing
        )
        pages[f"stad/{city.slug}/index.html"] = _page(
            f"Bio i {city.name}",
            f"<p>En vecka framåt per biograf. Se varje biograf för hela programmet.</p>{body}",
            path=f"/stad/{city.slug}/",
            crumbs=[(city.name, f"/stad/{city.slug}/")],
        )
        for cinema in showing:
            address = cinema.entity.get("address", {})
            details = ", ".join(filter(None, [address.get("streetAddress"), address.get("addressLocality")]))
            website = cinema.entity.get("url")
            header = escape(details) + (f' · <a href="{escape(website)}">Webbplats</a>' if website else "")
            schedule = _schedule(
                cinema.shows, lambda show: f'<a href="/film/{show.film.slug}/">{escape(show.film.name)}</a>'
            )
            pages[f"stad/{city.slug}/{cinema.slug}/index.html"] = _page(
                cinema.name,
                f"<p>{header}</p>{schedule}",
                path=f"/stad/{city.slug}/{cinema.slug}/",
                entity=_cinema_entity(cinema) | {"event": _events(cinema.shows, cinema=False)},
                crumbs=[(city.name, f"/stad/{city.slug}/"), (cinema.name, f"/stad/{city.slug}/{cinema.slug}/")],
            )

    for film in films:
        entity = film.entity
        facts = [
            entity.get("datePublished", "")[:4],
            f"{_minutes(entity.get('duration'))} min" if _minutes(entity.get("duration")) else "",
            ", ".join(person["name"] for person in _list(entity.get("director")) if isinstance(person, dict)),
        ]
        by_city = defaultdict(list)
        for show in _upcoming(film.shows, FILM_DAYS):
            by_city[show.cinema.city.name, show.cinema.city.slug].append(show)
        schedules = "".join(
            f'<h2><a href="/stad/{slug}/">{escape(name)}</a></h2>'
            + _schedule(
                shows,
                lambda show: (
                    f'<a href="/stad/{show.cinema.city.slug}/{show.cinema.slug}/">{escape(show.cinema.name)}</a>'
                ),
            )
            for (name, slug), shows in sorted(by_city.items())
        )
        poster = f'<img class="poster" src="{film.poster}" alt="">' if film.poster else "<span></span>"
        intro = (
            f'<p class="tag">{escape(" · ".join(filter(None, facts)))}</p>'
            f"<p>{escape(entity.get('description', ''))}</p>"
        )
        pages[f"film/{film.slug}/index.html"] = _page(
            film.name,
            f'<div class="hero">{poster}<div>{intro}</div></div>'
            f"<p>{FILM_DAYS} dagar från {_day(film.shows[0].start.date())}.</p>{schedules}",
            path=f"/film/{film.slug}/",
            entity=_film_entity(film) | {"subjectOf": _events(film.shows, film=False)},
            crumbs=[(film.name, f"/film/{film.slug}/")],
        )
        for alias in (
            item["value"] for item in film.entity["identifier"] if item["propertyID"] == "allabiografer:film-alias"
        ):
            pages[f"film/{alias}/index.html"] = _redirect(f"/film/{film.slug}/")

    for relative, content in pages.items():
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (staging / "style.css").write_text(_STYLE.lstrip(), encoding="utf-8")
    # Posters stay in the asset store; the site links to them.
    posters = staging / "assets"
    posters.mkdir()
    for poster in {film.poster for film in films if film.poster}:
        digest = poster.rsplit("/", 1)[1]
        (posters / digest).symlink_to(Path("..", "..", "assets", digest))
    shutil.rmtree(out, ignore_errors=True)
    staging.rename(out)
    return len(pages)


def _redirect(target: str) -> str:
    return (
        f'<!DOCTYPE html><meta charset="utf-8"><link rel="canonical" href="{SITE}{target}">'
        f'<meta http-equiv="refresh" content="0; url={target}"><a href="{target}">{target}</a>\n'
    )


def _list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def _minutes(duration: str | None) -> int | None:
    found = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration or "")
    return (int(found[1] or 0) * 60 + int(found[2] or 0)) or None if found else None
