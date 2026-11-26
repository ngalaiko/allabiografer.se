"""Render a merged Dataset as the allabiografer.se website.

The pages are `site/pages.py` with its templates, styles and scripts; this module only
translates the merged Schema.org graph into the page data they render from.
"""

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

from . import session as http
from .graph import Graph, media_type
from .model import Screening, Venue
from .model.movie import Movie
from .model.version import (
    AudioVersion,
    ContentVersion,
    Dimension,
    Language,
    Presentation,
    PresentationSystem,
    ProjectionMedium,
    SubtitleVersion,
)
from .site import pages
from .sources._shared import STOCKHOLM

FILM = "allabiografer:film"
ALIAS = "allabiografer:film-alias"
_LANGUAGES = {language.tag: language for language in Language}
_SYSTEMS = {system.value: system for system in PresentationSystem}
_MEDIA = {medium.value: medium for medium in ProjectionMedium}


def _identity(slug: str) -> int:
    """Pages key films by negative integers; derive a stable one from the film's slug."""
    return -int.from_bytes(hashlib.sha256(slug.encode()).digest()[:7], "big")


def _list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def _minutes(duration: str | None) -> int | None:
    found = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration or "")
    return (int(found[1] or 0) * 60 + int(found[2] or 0)) or None if found else None


def _movie(identifier: int, film: dict) -> Movie:
    directors = [person["name"] for person in _list(film.get("director")) if isinstance(person, dict)]
    alternate = _list(film.get("alternateName"))
    return Movie(
        tmdb_id=identifier,
        title_sv=film["name"],
        title_original=alternate[0] if alternate else "",
        overview_sv=film.get("description") or "",
        genres=[genre for genre in _list(film.get("genre")) if isinstance(genre, str)],
        release_date=film.get("datePublished") or "",
        release_date_se="",
        runtime=_minutes(film.get("duration")),
        poster_path="",
        vote_average=None,
        age_rating=film.get("contentRating") or "",
        directors=directors or None,
    )


def _version(screening: dict) -> tuple[ContentVersion, Presentation]:
    audio = frozenset(_LANGUAGES[tag] for tag in screening.get("inLanguage", []) if tag in _LANGUAGES)
    subtitles = None
    if "subtitleLanguage" in screening:
        subtitles = frozenset(_LANGUAGES[tag] for tag in screening["subtitleLanguage"] if tag in _LANGUAGES)
    formats = screening.get("videoFormat", [])
    dimension = next((Dimension(value) for value in formats if value in {"2D", "3D"}), Dimension.UNKNOWN)
    medium = next((_MEDIA[value] for value in formats if value in _MEDIA), ProjectionMedium.UNKNOWN)
    return (
        ContentVersion(AudioVersion(languages=audio), SubtitleVersion(subtitles)),
        Presentation(
            experiences=frozenset(_SYSTEMS[value] for value in formats if value in _SYSTEMS),
            dimension=dimension,
            medium=medium,
        ),
    )


def _poster(graph: Graph, film_path: Path, image, session, downloaded: dict[str, Path]) -> dict | None:
    """The stored original poster: a captured image, or a source URL downloaded into the store once."""
    if isinstance(image, dict):
        return graph.read(graph.resolve(film_path, image))
    if not isinstance(image, str) or not image.startswith(("http://", "https://")):
        return None
    if image not in downloaded:
        try:
            response = session.get(image, timeout=30)
            response.raise_for_status()
        except Exception:
            return None
        media = media_type(image, response.headers.get("Content-Type", ""))
        if not media.startswith("image/"):
            return None
        downloaded[image] = graph.put_bytes(response.content, media, name=Path(image).name, url=image)
    return graph.read(downloaded[image])


def site_data(graph: Graph, merged: Path, out: Path, *, today: date | None = None) -> pages.SiteData:
    """Page data for a merged Dataset."""
    sd = pages.SiteData(out_dir=out)
    sd.graph = graph
    if today is not None:
        sd.today = today
    dataset = graph.read(merged)

    venues = {}
    for reference in dataset["about"]:
        path = graph.resolve(merged, reference)
        cinema = graph.read(path)
        city = graph.read(graph.resolve(path, cinema["containedInPlace"]))["name"]
        venues[path] = Venue(name=cinema["name"], city=city, address=cinema.get("address", {}).get("streetAddress", ""))
    sd.venues = {(venue.city, venue.name): venue for venue in venues.values()}

    downloaded = {}
    for path in graph.schema.glob("ImageObject/*.jsonld"):
        url = graph.read(path).get("isBasedOn")
        if isinstance(url, str):
            downloaded[url] = path
    session = http.session()
    identities, images, screenings = {}, {}, []
    for reference in dataset["hasPart"]:
        path = graph.resolve(merged, reference)
        entity = graph.read(path)
        if entity["@type"] == "Movie":
            slug = next(item["value"] for item in entity["identifier"] if item["propertyID"] == FILM)
            identifier = _identity(slug)
            identities[path] = identifier
            sd.movies[identifier] = _movie(identifier, entity)
            sd.film_slugs[identifier] = slug
            sd.tmdb_ids[identifier] = None
            images[identifier] = (path, entity.get("image"))
            for item in entity["identifier"]:
                if item["propertyID"] == ALIAS:
                    sd.film_aliases[item["value"]] = slug
        else:
            screenings.append((path, entity))

    for path, entity in screenings:
        start = datetime.fromisoformat(entity["startDate"]).astimezone(STOCKHOLM)
        if start.date() < sd.today:
            continue
        identifier = identities[graph.resolve(path, entity["workPresented"])]
        venue = venues[graph.resolve(path, entity["location"])]
        version, presentation = _version(entity)
        sd.screenings.append(
            Screening(
                tmdb_id=identifier,
                date=start.date(),
                time=start.time().replace(tzinfo=None),
                ticket_url=entity["offers"]["url"],
                cinema_name=venue.name,
                city=venue.city,
                title=entity["name"],
                source=entity["identifier"]["propertyID"].rsplit(":", 1)[1],
                version=version,
                presentation=presentation,
                runtime=sd.movies[identifier].runtime,
            )
        )
    sd.screenings.sort(key=lambda s: (s.date, s.time, s.city, s.cinema_name, s.tmdb_id, s.ticket_url))

    showing = {s.tmdb_id for s in sd.screenings}
    for identifier in showing:
        film_path, image = images[identifier]
        if poster := _poster(graph, film_path, image, session, downloaded):
            sd.posters[identifier] = poster
    for venue in venues.values():
        sd.cities.setdefault(venue.city, 0)
        sd.city_slugs[venue.city] = pages._slugify_sv(venue.city)
        sd.cinema_slugs[(venue.city, venue.name)] = pages._slugify_sv(venue.name)
    for screening in sd.screenings:
        sd.cities[screening.city] += 1
        sd.city_films.add((screening.city, screening.tmdb_id))
    # Every registry cinema and city has a page; films are listed while they show.
    sd.movies = {identifier: movie for identifier, movie in sd.movies.items() if identifier in showing}
    return sd


def render(graph: Graph, merged: Path, out: Path, *, today: date | None = None) -> int:
    """Write the site for `merged` to `out`, replacing it. Returns the number of pages."""
    return pages.build(site_data(graph, merged, out, today=today))
