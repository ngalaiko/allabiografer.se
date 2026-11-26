"""Capture Aspen's paginated programme and film pages."""

from urllib.parse import urljoin

from .._shared import capture, fetch_main, film_id

PROGRAMME = "https://www.bioaspen.se/visningar/filmer/"
SOURCE = "bioaspen_se"


def fetch_pages(session, inputs):
    url = PROGRAMME
    visited = set()
    movies = {}
    while url:
        if url in visited:
            raise ValueError(f"Aspen programme pagination loop: {url}")
        visited.add(url)
        programme = capture(session, url, inputs / f"programme-{len(visited):02d}.html")
        cards = programme.select('.movie > a[href*="/movies/"]')
        if not cards:
            raise ValueError(f"No Aspen film cards at {url}")
        movies.update(dict.fromkeys(urljoin(url, card["href"]) for card in cards))
        following = programme.select_one("a.next.page-numbers[href]")
        url = urljoin(url, following["href"]) if following else ""
    for movie in movies:
        capture(session, movie, inputs / f"movie-{film_id(movie)}.html")


if __name__ == "__main__":
    fetch_main(SOURCE, fetch_pages)
