"""Replay Osby Borgen's Vue session and movie payloads from captured HTML."""

from datetime import datetime
from functools import partial
from urllib.parse import urljoin

from parse.parsers.osbyborgen_se import (
    _ADDRESS,
    _CINEMA,
    _CITY,
    _SOURCE,
    _URL,
    _detail,
    _film,
    _label_facts,
    _parse_date,
    _parse_time,
    _sessions,
)

from .._regional import year_from_capture
from .._shared import STOCKHOLM, catalogue_main, movie_fields, stable_key


def rows(inputs, today):
    movies = {}
    seen = set()
    for session in _sessions((inputs / "programme.html").read_text(encoding="utf-8")):
        movie_id = session.get("f_id")
        href = session.get("f_href")
        if not movie_id or not href or not session.get("f_title", "").strip():
            continue
        day = _parse_date(session.get("f_date", ""), year_for_month=partial(year_from_capture, today))
        time = _parse_time(session.get("f_time", ""))
        if day is None or day < today or time is None:
            continue
        start = datetime.combine(day, time, STOCKHOLM)
        ticket = urljoin(_URL, href)
        show = stable_key(str(movie_id), start.isoformat(), ticket)
        if show in seen:
            continue
        seen.add(show)
        key = stable_key(str(movie_id))
        capture = f"movie-{key}.html"
        if key not in movies:
            detail = _detail((inputs / capture).read_text(encoding="utf-8"))
            film = _film(session, detail)
            # The documentary page has the correct poster and trailer but a copied Minecraft synopsis.
            overview = "" if str(movie_id) == "335" and "A Minecraft Movie" in film.overview else film.overview
            fields = movie_fields(film.title, film.url, overview, film.runtime, {"director": film.directors})
            if film.poster_url:
                fields["image"] = urljoin(_URL, film.poster_url)
            if film.genres:
                fields["genre"] = list(film.genres)
            if film.age_rating:
                fields["contentRating"] = film.age_rating
            movies[key] = fields, detail.get("f_label")
        fields, label = movies[key]
        version = _label_facts(session.get("f_label"), label)["version"]
        yield (
            ("bio-borgen-osby", _CINEMA, _ADDRESS, _CITY),
            show,
            start,
            ticket,
            version.audio.languages,
            "",
            key,
            capture,
            fields,
        )


if __name__ == "__main__":
    catalogue_main(_SOURCE, rows)
