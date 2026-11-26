"""Replay Rio Tomelilla's saved programme and movie details."""

import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from .._shared import facts, movie_fields
from . import BASE, STOCKHOLM, response_rows

VENUE = (None,)


def rows(inputs, today):
    movies = {}
    for row in response_rows(inputs / "programme.json"):
        title = row["title"].strip()
        if row["show_locked"] or not title or title.casefold().startswith("filmquiz"):
            continue
        start = datetime.fromisoformat(row["show_time"]).astimezone(STOCKHOLM)
        if start.date() < today:
            continue
        movie_id = str(row["movie_id"])
        capture = f"movie-details-{movie_id}.json"
        if movie_id not in movies:
            detail = next(item for item in response_rows(inputs / capture) if str(item["movie_id"]) == movie_id)
            description = BeautifulSoup(detail.get("description") or "", "html.parser").get_text(" ", strip=True)
            fields = movie_fields(
                title,
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
            if poster := detail.get("movie_poster"):
                # A capture name: the pipeline links it to the stored ImageObject.
                fields["image"] = f"poster-{movie_id}{Path(poster).suffix}"
            movies[movie_id] = fields
        show_id = str(row["show_time_id"])
        yield (
            VENUE,
            show_id,
            start,
            f"{BASE}/#/book/{show_id}",
            *facts(language=row.get("audio_lang") or "", subtitles=row.get("subtitle_lang") or ""),
            movie_id,
            capture,
            movies[movie_id],
        )
