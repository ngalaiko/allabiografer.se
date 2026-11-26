"""Replay the saved Roxy Bio schedule and movie details without enrichment."""

import json
from datetime import datetime

from bs4 import BeautifulSoup

from allabiografer.movie_fields import booking_fields
from allabiografer.sources.roxy_bio.site import _BASE, _VENUE, _showtimes

from .._shared import STOCKHOLM, facts, movie_fields
from .fetch import response_rows


def rows(inputs, today):
    programme = "programme.json"
    payload = json.loads((inputs / programme).read_bytes())
    movies = {}
    seen = set()
    for row in _showtimes(response_rows(payload, programme)):
        start = datetime.fromisoformat(row["show_time"]).astimezone(STOCKHOLM)
        show = str(int(row["show_time_id"]))
        if start.date() < today or show in seen:
            continue
        seen.add(show)
        movie_id = int(row["movie_id"])
        capture = f"movie-{movie_id}.json"
        if movie_id not in movies:
            details = response_rows(json.loads((inputs / capture).read_bytes()), capture)
            detail = next(item for item in details if int(item["movie_id"]) == movie_id)
            description = BeautifulSoup(detail.get("description") or "", "html.parser").get_text(" ", strip=True)
            credits = {
                role: [name.strip() for name in (detail.get(field) or "").split(",") if name.strip()]
                for role, field in (("director", "director_name"), ("actor", "actors_name"))
            }
            fields = movie_fields(
                detail.get("movie_name") or row["title"].strip(),
                f"{_BASE}/#/movie/{movie_id}",
                description,
                detail.get("running_time") or row.get("running_time"),
                credits,
                year=str(detail.get("production_year") or ""),
                **booking_fields(detail),
            )
            if poster := detail.get("movie_poster"):
                fields["image"] = f"{_BASE}/media/posters/{movie_id}/{poster}"
            if rating := detail.get("rating_name") or row.get("rating_name"):
                fields["contentRating"] = rating
            movies[movie_id] = fields
        yield (
            (None, _VENUE.name, _VENUE.address, _VENUE.city),
            show,
            start,
            f"{_BASE}/#/book/{show}",
            *facts(language=row.get("audio_lang") or "", subtitles=row.get("subtitle_lang") or ""),
            str(movie_id),
            capture,
            movies[movie_id],
        )
