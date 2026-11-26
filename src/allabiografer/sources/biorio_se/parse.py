"""Parse Bio Rio's saved API responses without network access."""

import json
from datetime import datetime

from allabiografer.sources.biorio_se.site import _CANCELLED, _SITE, _label, _release_date, _show_date, _show_time

from .._shared import STOCKHOLM, _version, facts, movie_fields


def rows(inputs, today):
    details = {}
    for show in json.loads((inputs / "showtimes.json").read_bytes())["showtimes"]:
        if show.get("membersOnly") or _CANCELLED.search(show.get("status") or ""):
            continue
        day, clock = _show_date(show.get("date")), _show_time(show.get("time"))
        if day is None or clock is None or day < today:
            continue
        slug = show["movie"]["slug"]
        capture = f"movie-{slug}.json"
        if slug not in details:
            movie = show["movie"] | (json.loads((inputs / capture).read_bytes()).get("movie") or {})
            synopsis = (movie.get("synopsis") or "").strip()
            fields = movie_fields(
                movie["title"].strip(),
                f"{_SITE}/sv/filmer/{slug}",
                synopsis,
                movie.get("duration"),
                {"director": (movie.get("director") or "").split(", "), "actor": movie.get("cast") or []},
                year=_release_date(movie),
                genre=movie.get("genres") or [],
                # The poster is AVIF; its JPEG share image is the same artwork.
                image=movie.get("ogImageUrl") or movie.get("posterPath") or "",
                languages=_version.languages(movie.get("language") or ""),
                trailers=[movie.get("trailerUrl") or ""],
                same_as=[f"https://www.themoviedb.org/movie/{movie['tmdbId']}"] if movie.get("tmdbId") else [],
            )
            if "visas i director's cut" in synopsis.casefold():
                fields["version"] = "Director's Cut"
            details[slug] = fields
        yield (
            (None, "Bio Rio", "Hornstulls strand 3"),
            show["id"],
            datetime.combine(day, clock, STOCKHOLM),
            f"{_SITE}/sv/boka/{show['id']}",
            *facts(language=_label(show.get("audio")), subtitles=_label(show.get("subtitles"))),
            slug,
            capture,
            details[slug],
        )
