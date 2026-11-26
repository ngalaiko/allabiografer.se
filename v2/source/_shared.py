"""Shared capture and JSON-LD catalogue helpers for cinema sources."""

import argparse
import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from parse import _http, _version

from ..schema import Catalogue, entity_path, link, write
from .stockholm_movie_links import REVIEWED_MOVIE_LINKS

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def stable_key(*parts):
    return sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def capture_json(session, url, path, *, body=None, params=None):
    response = session.get(url, params=params, timeout=30) if body is None else session.post(url, json=body, timeout=30)
    response.raise_for_status()
    data = response.json()
    path.write_bytes(response.content)
    return data


def source_path(root, stage, source):
    return root / stage / str(int(time())) / "sources" / source


def film_id(url):
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
        raise ValueError(f"Unexpected film URL: {url}")
    return slug


def capture(session, url, path):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    path.write_bytes(response.content)
    return read_page(path)


def read_page(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def fetch_main(source, fetch_pages):
    cli = argparse.ArgumentParser(description=f"Capture {source}'s programme")
    cli.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    inputs = source_path(cli.parse_args().data.resolve(), "fetch", source)
    inputs.mkdir(parents=True)
    with _http.session() as session:
        fetch_pages(session, inputs)
    print(inputs.parents[1])


def fetch_cities_main(source, fetch_pages):
    cli = argparse.ArgumentParser(description=f"Capture {source}'s programme")
    cli.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    cli.add_argument("--city", action="append", help="Limit capture to this city; repeat to include more cities")
    args = cli.parse_args()
    inputs = source_path(args.data.resolve(), "fetch", source)
    inputs.mkdir(parents=True)
    with _http.session() as session:
        fetch_pages(session, inputs, set(args.city or ()))
    print(inputs.parents[1])


def parse_main(source, cinema_id, cinema_name, address, screenings):
    def rows(inputs, today):
        for show_id, start, ticket, audio, subtitles, url, title, description, runtime, credits in screenings(
            inputs, today
        ):
            slug = film_id(url)
            fields = movie_fields(title, url, description, runtime, credits)
            yield (
                (cinema_id, cinema_name, address),
                show_id,
                start,
                ticket,
                audio,
                subtitles,
                slug,
                f"movie-{slug}.html",
                fields,
            )

    catalogue_main(source, rows)


def movie_fields(title, url, description, runtime, credits=None, *, year="", alternate=""):
    same_as = REVIEWED_MOVIE_LINKS.get(url.rstrip("/"))
    return {
        "name": title,
        "url": url,
        **({"description": description} if description else {}),
        **({"duration": f"PT{runtime}M"} if runtime else {}),
        **({"datePublished": year} if year else {}),
        **({"alternateName": alternate} if alternate else {}),
        **({"sameAs": same_as} if same_as else {}),
        **{
            role: [{"@type": "Person", "name": name} for name in dict.fromkeys(names) if name]
            for role, names in (credits or {}).items()
            if names
        },
    }


def catalogue_main(source, rows):
    cli = argparse.ArgumentParser(description=f"Parse a saved {source} fetch")
    cli.add_argument("fetch", type=Path, help="Fetch directory printed by fetch.py")
    cli.add_argument("--city", action="append", help="Limit output to this city; repeat to include more cities")
    args = cli.parse_args()
    fetch = args.fetch.resolve()
    inputs = fetch / "sources" / source
    if fetch.parent.name != "fetch" or not fetch.name.isdecimal() or not inputs.is_dir():
        cli.error(f"expected a fetch/<timestamp> directory containing sources/{source}")
    today = datetime.fromtimestamp(int(fetch.name), STOCKHOLM).date()
    output = source_path(fetch.parents[1], "parse", source)
    output.mkdir(parents=True)
    catalogue = Catalogue(output)

    try:
        cities = set()
        movies = set()
        cinemas = set()
        for venue, show_id, start, ticket, audio, subtitles, slug, capture_name, movie_data in rows(inputs, today):
            cinema_id, cinema_name, address, *place = venue
            city = place[0] if place else "Stockholm"
            if args.city and city not in args.city:
                continue
            city_key = "stockholm" if city == "Stockholm" else stable_key(city.casefold())
            city_path = output / entity_path("City", city_key)
            if city_key not in cities:
                catalogue.node(city_path, name=city)
                cities.add(city_key)
            cinema = output / entity_path("MovieTheater", cinema_id)
            if cinema_id not in cinemas:
                catalogue.node(
                    cinema,
                    name=cinema_name,
                    containedInPlace=link(city_path, cinema.parent),
                    address={"@type": "PostalAddress", "streetAddress": address, "addressCountry": "SE"},
                )
                cinemas.add(cinema_id)
            movie = output / entity_path("Movie", slug)
            if slug not in movies:
                catalogue.node(
                    movie,
                    isBasedOn=link(inputs / capture_name, movie.parent),
                    **movie_data,
                )
                movies.add(slug)
            fields = {}
            if languages := (_version.languages(audio) if isinstance(audio, str) else audio):
                fields["inLanguage"] = sorted(languages)
            if languages := (_version.languages(subtitles) if isinstance(subtitles, str) else subtitles):
                fields["subtitleLanguage"] = sorted(languages)
            screening = output / entity_path("ScreeningEvent", show_id)
            catalogue.node(
                screening,
                name=movie_data["name"],
                startDate=start.isoformat(),
                workPresented=link(movie, screening.parent),
                location=link(cinema, screening.parent),
                offers={"@type": "Offer", "url": ticket},
                **fields,
            )
        path = catalogue.finish(
            name=f"{source} source catalogue",
            dateCreated=datetime.now(UTC).isoformat(),
            based_on=sorted(inputs.iterdir()),
        )
    except Exception as error:
        write(output / "error.json", {"error": str(error)})
        raise
    print(path.as_uri())
