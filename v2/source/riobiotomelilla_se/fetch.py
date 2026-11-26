"""Fetch Rio Tomelilla's programme, movie details, and posters."""

from pathlib import Path

from .._shared import saved, single
from . import BASE, response_rows


def capture(session, path: Path, endpoint: str, **params) -> list[dict]:
    response = session.get(f"{BASE}/webservices/{endpoint}", params={"cinema_id": 8, **params}, timeout=30)
    response.raise_for_status()
    saved(session, path, response)
    return response_rows(path)


def fetch_pages(session, inputs, today, *, selectors=None):
    single(selectors)
    rows = capture(
        session,
        inputs / "programme.json",
        "show_times/getShowTimesDays",
        date=today.isoformat(),
        number_of_days=35,
    )
    for movie_id in dict.fromkeys(row["movie_id"] for row in rows):
        details = capture(
            session, inputs / f"movie-details-{movie_id}.json", "movies/getMovieDetails", movie_id=movie_id
        )
        detail = next(item for item in details if item["movie_id"] == movie_id)
        if poster := detail.get("movie_poster"):
            response = session.get(f"{BASE}/media/posters/{movie_id}/{poster}", timeout=30)
            response.raise_for_status()
            if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                raise ValueError(f"Poster for movie {movie_id} is not an image")
            saved(session, inputs / f"poster-{movie_id}{Path(poster).suffix}", response)
