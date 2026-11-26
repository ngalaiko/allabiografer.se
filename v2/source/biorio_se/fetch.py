"""Capture Bio Rio's public programme and movie details."""

from parse.parsers.biorio_se import _API, _SHOWTIMES_URL

from .._shared import fetch_main


def fetch_pages(session, inputs):
    response = session.get(_SHOWTIMES_URL, timeout=30)
    response.raise_for_status()
    (inputs / "showtimes.json").write_bytes(response.content)
    for slug in sorted(
        {s["movie"]["slug"] for s in response.json()["showtimes"] if (s.get("movie") or {}).get("slug")}
    ):
        response = session.get(f"{_API}/movies/{slug}", timeout=30)
        response.raise_for_status()
        (inputs / f"movie-{slug}.json").write_bytes(response.content)


if __name__ == "__main__":
    fetch_main("biorio_se", fetch_pages)
