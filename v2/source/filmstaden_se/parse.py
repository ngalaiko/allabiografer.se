"""Parse the saved Filmstaden programmes and movies."""

import json
from datetime import datetime

from parse.parsers.filmstaden_se import _CINEMA_STATUS, _film, _screening

from .._shared import STOCKHOLM, catalogue_main, movie_fields
from .fetch import venue_id


def rows(inputs, today):
    cinemas = {c["ncgId"]: c for c in json.loads((inputs / "cinemas.json").read_bytes())["items"]}
    films = {}
    seen = set()
    for path in sorted(inputs.glob("shows-*.json")):
        _, cinema_id, _ = path.stem.split("-")
        cinema = cinemas[cinema_id]
        name = _CINEMA_STATUS.sub("", cinema["title"].strip())
        address = cinema["address"]
        city = address["city"]["name"]
        venue = (venue_id(cinema_id), name, address.get("streetAddress") or "", city)
        for row in json.loads(path.read_bytes())["items"]:
            movie = row.get("movie") or {}
            if not row.get("time") or not movie.get("title") or not row.get("remoteEntityId"):
                continue
            start = datetime.fromisoformat(row["time"])
            start = start.astimezone(STOCKHOLM) if start.tzinfo else start.replace(tzinfo=STOCKHOLM)
            show_id = row["remoteEntityId"]
            if start.date() < today or show_id in seen:
                continue
            seen.add(show_id)
            movie_id = movie["ncgId"]
            capture = f"movie-{movie_id}.json"
            if movie_id not in films:
                detail = json.loads((inputs / capture).read_bytes())
                film = _film(movie, detail)
                films[movie_id] = movie_fields(
                    film.title,
                    film.url,
                    film.overview,
                    film.runtime,
                    {
                        role: [p["displayName"] for p in detail.get(key) or [] if p.get("displayName")]
                        for role, key in (("director", "directors"), ("actor", "actors"))
                    },
                    year=film.release_date,
                    alternate=film.title_original,
                )
            show = _screening(row, tmdb_id=None, cinema_name=name, city=city)
            yield (
                venue,
                show_id,
                start,
                show.ticket_url,
                show.version.audio.languages,
                show.version.subtitles.languages,
                movie_id,
                capture,
                films[movie_id],
            )


if __name__ == "__main__":
    catalogue_main("filmstaden_se", rows)
