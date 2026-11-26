"""Replay Hypnos Theatre's captured programme."""

from datetime import datetime

from parse.parsers.hypnostheatre_com import _ADDRESS, _CINEMA, _CITY, _showtimes

from .._shared import STOCKHOLM, catalogue_main, movie_fields, stable_key

REVIEWED_CREDITS = {
    ("die hard", "1988"): "https://biografspegeln.se/program/die-hard",
    ("the holdovers", "2023"): "https://biografspegeln.se/program/the-holdovers",
}


def rows(inputs, today):
    capture = "programme.html"
    seen = set()
    for film, show in _showtimes((inputs / capture).read_text(encoding="utf-8")):
        if show.date < today:
            continue
        start = datetime.combine(show.date, show.time, STOCKHOLM)
        movie_id = stable_key(film.key, film.release_date)
        key = stable_key(movie_id, start.isoformat(), show.ticket_url)
        if key in seen:
            continue
        seen.add(key)
        fields = movie_fields(film.title, "", film.overview, film.runtime, year=film.release_date)
        if equivalent := REVIEWED_CREDITS.get((film.title.casefold(), film.release_date)):
            fields["sameAs"] = equivalent
        yield (
            ("hypnos-theatre", _CINEMA, _ADDRESS, _CITY),
            key,
            start,
            show.ticket_url,
            show.version.audio.languages,
            show.version.subtitles.languages,
            movie_id,
            capture,
            fields,
        )


if __name__ == "__main__":
    catalogue_main("hypnostheatre_com", rows)
