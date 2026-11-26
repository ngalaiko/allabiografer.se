"""Convert a saved Rio Tomelilla capture to JSON-LD without network access."""

import argparse
import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from parse import _version

from ...schema import Catalogue, entity_path, link, write
from .._shared import movie_fields
from . import BASE, SOURCE, STOCKHOLM, new_source, response_rows


def poster_asset(root: Path, capture: Path) -> Path:
    data = capture.read_bytes()
    path = root / "assets" / hashlib.sha256(data).hexdigest()
    path.parent.mkdir(exist_ok=True)
    try:
        with path.open("xb") as asset:
            asset.write(data)
    except FileExistsError:
        pass  # An existing object has the same content address.
    return path


def parse(fetch_dir: Path) -> Path:
    inputs = fetch_dir / "sources" / SOURCE
    root = fetch_dir.parents[1]
    output = new_source(root, "parse")
    output.mkdir(parents=True)
    catalogue = Catalogue(output)
    city = output / entity_path("City", "tomelilla")
    cinema = output / entity_path("MovieTheater", "riobiografen-tomelilla")
    try:
        rows = [
            row
            for row in response_rows(inputs / "programme.json")
            if not row["show_locked"]
            and row["title"].strip()
            and not row["title"].strip().casefold().startswith("filmquiz")
        ]
        catalogue.node(city, name="Tomelilla")
        catalogue.node(
            cinema,
            name="Tomelilla Riobiografen",
            containedInPlace=link(city, cinema.parent),
            address={"@type": "PostalAddress", "streetAddress": "Norregatan 3", "addressCountry": "SE"},
        )
        movies = {}
        for row in rows:
            movies.setdefault(row["movie_id"], row)
        for movie_id, row in movies.items():
            detail_file = f"movie-details-{movie_id}.json"
            detail = next(item for item in response_rows(inputs / detail_file) if item["movie_id"] == movie_id)
            description = BeautifulSoup(detail.get("description") or "", "html.parser").get_text(" ", strip=True)
            fields = movie_fields(
                row["title"].strip(),
                f"{BASE}/#/movie/{movie_id}",
                description,
                detail.get("running_time") or row.get("running_time"),
                {
                    role: [name.strip() for name in (detail.get(key) or "").split(",") if name.strip()]
                    for role, key in (("director", "director_name"), ("actor", "actors_name"))
                },
                year=str(detail.get("production_year") or ""),
            )
            if re.fullmatch(r"tt\d+", imdb := str(detail.get("imdb_id") or "")):
                fields.setdefault("sameAs", f"https://www.imdb.com/title/{imdb}")
            if rating := detail.get("rating_name") or row.get("rating_name"):
                fields["contentRating"] = rating
            movie = output / entity_path("Movie", str(movie_id))
            if poster := detail.get("movie_poster"):
                asset = poster_asset(root, inputs / f"poster-{movie_id}{Path(poster).suffix}")
                fields["image"] = link(asset, movie.parent)
            catalogue.node(
                movie,
                identifier=str(movie_id),
                isBasedOn=link(inputs / detail_file, movie.parent),
                **fields,
            )
        for row in rows:
            screening_id = row["show_time_id"]
            start = datetime.fromisoformat(row["show_time"])
            fields = {}
            if runtime := row.get("running_time"):
                fields["endDate"] = (start + timedelta(minutes=runtime)).astimezone(STOCKHOLM).isoformat()
            if audio := _version.languages(row.get("audio_lang") or ""):
                fields["inLanguage"] = sorted(audio)
            if subtitles := _version.languages(row.get("subtitle_lang") or ""):
                fields["subtitleLanguage"] = sorted(subtitles)
            screening = output / entity_path("ScreeningEvent", str(screening_id))
            movie = output / entity_path("Movie", str(row["movie_id"]))
            catalogue.node(
                screening,
                name=row["title"].strip(),
                startDate=start.astimezone(STOCKHOLM).isoformat(),
                workPresented=link(movie, screening.parent),
                location=link(cinema, screening.parent),
                offers={"@type": "Offer", "url": f"{BASE}/#/book/{screening_id}"},
                **fields,
            )
        return catalogue.finish(
            name="Rio Tomelilla source catalogue",
            dateCreated=datetime.now(UTC).isoformat(),
            based_on=sorted(inputs.iterdir()),
        )
    except Exception as error:
        write(output / "error.json", {"error": str(error)})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fetch", type=Path, help="Fetch directory printed by fetch.py")
    args = parser.parse_args()
    fetch_dir = args.fetch.resolve()
    if fetch_dir.parent.name != "fetch" or not (fetch_dir / "sources" / SOURCE).is_dir():
        parser.error(f"expected a fetch/<timestamp> directory containing sources/{SOURCE}")
    print(parse(fetch_dir).as_uri())


if __name__ == "__main__":
    main()
