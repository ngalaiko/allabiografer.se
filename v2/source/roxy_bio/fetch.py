"""Capture Roxy Bio's My Cloud Cinema schedule and movie API responses."""

from datetime import datetime

from parse.parsers.roxy_bio import _BASE, _SOURCE, _showtimes

from .._shared import STOCKHOLM, capture_json, fetch_main


def response_rows(payload, capture):
    if payload["resultCode"] != 0:
        raise ValueError(f"Roxy Bio {capture} returned resultCode {payload['resultCode']}")
    return payload["data"]


def fetch_pages(session, inputs):
    today = datetime.fromtimestamp(int(inputs.parents[1].name), STOCKHOLM).date()
    programme = capture_json(
        session,
        f"{_BASE}/webservices/show_times/getShowTimesDays",
        inputs / "programme.json",
        params={"cinema_id": 12, "date": today.isoformat(), "number_of_days": 35},
    )
    rows = _showtimes(response_rows(programme, "programme.json"))
    for movie_id in dict.fromkeys(int(row["movie_id"]) for row in rows):
        name = f"movie-{movie_id}.json"
        data = capture_json(
            session,
            f"{_BASE}/webservices/movies/getMovieDetails",
            inputs / name,
            params={"cinema_id": 12, "movie_id": movie_id},
        )
        if not any(int(row["movie_id"]) == movie_id for row in response_rows(data, name)):
            raise ValueError(f"Roxy Bio details missing in {name}")


if __name__ == "__main__":
    fetch_main(_SOURCE, fetch_pages)
