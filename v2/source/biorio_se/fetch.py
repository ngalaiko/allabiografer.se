"""Capture Bio Rio's public programme and movie details."""

from parse.parsers.biorio_se import _API, _SHOWTIMES_URL

from .._shared import saved


def fetch_pages(session, inputs, today, *, selectors=None):
    response = session.get(_SHOWTIMES_URL, timeout=30)
    response.raise_for_status()
    saved(session, inputs / "showtimes.json", response)
    for slug in sorted(
        {s["movie"]["slug"] for s in response.json()["showtimes"] if (s.get("movie") or {}).get("slug")}
    ):
        response = session.get(f"{_API}/movies/{slug}", timeout=30)
        response.raise_for_status()
        saved(session, inputs / f"movie-{slug}.json", response)
