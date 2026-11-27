"""Render a merged Dataset as the allabiografer.se website.

The pages are `site/pages.py` with its templates, styles and scripts; this module only
translates the merged Schema.org graph into the page data they render from.
"""

import hashlib
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from . import session as http
from .model import Screening, Venue
from .model.movie import Movie
from .model.version import (
    FORMATS,
    AudioFormat,
    AudioVersion,
    ContentVersion,
    Language,
    Presentation,
    SubtitleVersion,
    VideoFormat,
)
from .posters import poster as _poster
from .posters import stored_downloads
from .site import pages
from .sources._shared import STOCKHOLM

if TYPE_CHECKING:
    from pathlib import Path

    from .graph import Graph

FILM = "allabiografer:film"
ALIAS = "allabiografer:film-alias"
_LANGUAGES = {language.tag: language for language in Language}


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
        original_language=next(iter(film.get("inLanguage") or []), ""),
        spoken_languages=film.get("inLanguage") or None,
        directors=directors or None,
    )


def _version(screening: dict) -> tuple[ContentVersion, Presentation]:
    audio = frozenset(_LANGUAGES[tag] for tag in screening.get("inLanguage", []) if tag in _LANGUAGES)
    subtitles = None
    if "subtitleLanguage" in screening:
        subtitles = frozenset(_LANGUAGES[tag] for tag in screening["subtitleLanguage"] if tag in _LANGUAGES)
    found = {FORMATS[value] for value in screening.get("videoFormat", []) if value in FORMATS}
    return (
        ContentVersion(AudioVersion(languages=audio), SubtitleVersion(subtitles)),
        Presentation(
            video=frozenset(value for value in found if isinstance(value, VideoFormat)),
            audio=frozenset(value for value in found if isinstance(value, AudioFormat)),
        ),
    )


def published(graph: Graph, site: Path | None) -> set[str]:
    """The paths a Dataset of pages lists as published."""
    if site is None:
        return set()
    return {
        part["url"].removeprefix(pages.BASE_URL) for part in graph.parts(site).values() if part["@type"] == "WebPage"
    }


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
        if former := cinema.get("alternateName"):
            sd.cinema_aliases[(city, pages._slugify_sv(former))] = pages._slugify_sv(cinema["name"])
    sd.venues = {(venue.city, venue.name): venue for venue in venues.values()}

    downloaded = stored_downloads(graph)
    session = http.session()
    identities, images, screenings = {}, {}, []
    for entity in graph.parts(merged).values():
        if entity["@type"] == "Movie":
            slug = next(item["value"] for item in entity["identifier"] if item["propertyID"] == FILM)
            identifier = _identity(slug)
            identities[entity["@id"]] = identifier
            sd.movies[identifier] = _movie(identifier, entity)
            sd.film_slugs[identifier] = slug
            sd.tmdb_ids[identifier] = None
            images[identifier] = (merged, entity.get("image"))
            for item in entity["identifier"]:
                if item["propertyID"] == ALIAS:
                    sd.film_aliases[item["value"]] = slug
                    sd.film_slug_of[item["value"]] = slug
        elif entity["@type"] == "ScreeningEvent":
            screenings.append(entity)

    for entity in screenings:
        start = datetime.fromisoformat(entity["startDate"]).astimezone(STOCKHOLM)
        if start.date() < sd.today:
            continue
        identifier = identities[entity["workPresented"]["@id"]]
        venue = venues[graph.resolve(merged, entity["location"])]
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


def render(graph: Graph, merged: Path, out: Path, *, previous: Path | None = None, today: date | None = None) -> Path:
    """Write the site for `merged` to `out`, replacing it; return the Dataset of its pages.

    The Dataset lists every page ever published, now and in `previous`, the one before, as
    `WebPage` parts: a page no longer served is a redirect to its nearest one, so a published
    address never breaks.
    """
    sd = site_data(graph, merged, out, today=today)
    sd.published = published(graph, previous)
    pages.build(sd)
    paths = sorted(sd.published | pages.served(sd))
    return graph.put_dataset(
        {
            "name": "Published pages",
            "url": pages.BASE_URL,
            # The pages before are all listed here; linking them would keep every earlier site.
            "isBasedOn": graph.ref(merged),
        },
        [
            {"@id": f"#page-{index}", "@type": "WebPage", "url": pages.BASE_URL + path}
            for index, path in enumerate(paths)
        ],
    )
