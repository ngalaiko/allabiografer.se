"""Parse the saved bio.se Stockholm programmes."""

import json
from datetime import datetime

from parse.parsers.bio_se import _cinema_url, _showtimes, _venue

from .._shared import STOCKHOLM, catalogue_main, film_id, movie_fields, stable_key
from .fetch import OTHER_PROGRAMME_IDS, programme_city, venue_id

# Cinemateket's 5 December programme distinguishes these same-title films.
METROPOLIS = {"15619": ("1927", "Fritz Lang"), "43154": ("2001", "Rintarô")}

# Listings disagree on the programme length; neither establishes the work's runtime.
UNVERIFIED_RUNTIMES = {"42627", "49827", "49922"}


def rows(inputs, today):
    cinemas = {str(c["id"]): c for c in json.loads((inputs / "cinemas.json").read_bytes())["cinemas"]}
    seen = set()
    for path in sorted(inputs.glob("programme-*.json")):
        cinema_id = path.stem.removeprefix("programme-")
        if int(cinema_id) in OTHER_PROGRAMME_IDS:
            continue  # Replaying an older capture must still respect current timetable ownership.
        cinema = cinemas[cinema_id]
        venue = _venue(cinema)
        for film, day, clock, ticket, hall, _, audio, subtitles, *_ in _showtimes(
            json.loads(path.read_bytes()), _cinema_url(cinema)
        ):
            if day < today:
                continue
            start = datetime.combine(day, clock, STOCKHOLM)
            # Generic cinema links are shared by distinct shows; ticket links are not.
            show_id = stable_key(
                cinema_id,
                start.isoformat(),
                ticket,
                film.title if ticket == _cinema_url(cinema) else "",
                hall if ticket == _cinema_url(cinema) else "",
            )
            if show_id in seen:
                continue
            seen.add(show_id)
            movie_id = film_id(film.url) if film.url else stable_key(film.key)
            year, director = METROPOLIS.get(movie_id, (film.release_date, ""))
            yield (
                (venue_id(cinema_id), venue.name, venue.address, programme_city(venue)),
                show_id,
                start,
                ticket,
                audio,
                subtitles,
                movie_id,
                path.name,
                movie_fields(
                    film.title,
                    film.url,
                    film.overview,
                    None if movie_id in UNVERIFIED_RUNTIMES else film.runtime,
                    {"director": [director]} if director else None,
                    year=year,
                ),
            )


if __name__ == "__main__":
    catalogue_main("bio_se", rows)
