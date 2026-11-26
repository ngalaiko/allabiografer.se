"""Fetch Rio Tomelilla's programme, movie details, and posters to disk."""

import argparse
from datetime import datetime
from pathlib import Path

from parse import _http

from . import BASE, STOCKHOLM, new_source, response_rows


def capture(session, path: Path, endpoint: str, **params) -> list[dict]:
    response = session.get(f"{BASE}/webservices/{endpoint}", params={"cinema_id": 8, **params}, timeout=30)
    response.raise_for_status()
    path.write_bytes(response.content)
    return response_rows(path)


def fetch(root: Path) -> Path:
    inputs = new_source(root, "fetch")
    inputs.mkdir(parents=True)
    with _http.session() as session:
        rows = capture(
            session,
            inputs / "programme.json",
            "show_times/getShowTimesDays",
            date=datetime.now(STOCKHOLM).date().isoformat(),
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
                (inputs / f"poster-{movie_id}{Path(poster).suffix}").write_bytes(response.content)
    return inputs.parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[2] / "data")
    args = parser.parse_args()
    print(fetch(args.data.resolve()))


if __name__ == "__main__":
    main()
