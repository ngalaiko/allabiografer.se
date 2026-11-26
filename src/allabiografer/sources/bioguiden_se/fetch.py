"""Capture Bioguiden programmes for its assigned cinemas, and each film's gallery poster."""

import re

from allabiografer.sources.bioguiden_se.site import _BASE, _SITES, gallery, poster

from ...schedule import checked
from .._shared import capture, stable_key

_MOVIE = re.compile(r"filmfokus\.aspx\?movieid=([0-9a-f-]{36})")


def fetch_pages(session, inputs, today, *, selectors=None):
    checked(selectors, {stable_key(url) for url in _SITES})
    movies = {}
    for url in _SITES:
        if selectors is not None and stable_key(url) not in selectors:
            continue
        page = capture(session, url, inputs / f"programme-{stable_key(url)}.html")
        for link in page.select("#SearchResultDetails a[href*='filmfokus.aspx']"):
            if found := _MOVIE.search(link["href"]):
                movies.setdefault(found[1], f"{_BASE}{link['href']}")
    for movie_id, url in movies.items():
        film = capture(session, url, inputs / f"film-{movie_id}.html")
        images = gallery(str(film))
        if not images:
            continue
        # Without its film page as referrer, Bioguiden serves a "Bild saknas" placeholder.
        response = session.get(images[0], headers={"Referer": url}, timeout=30)
        response.raise_for_status()
        # Only a portrait within its canvas is a poster; other gallery images are stills.
        if response.headers.get("Content-Type", "").lower().startswith("image/") and (
            cropped := poster(response.content)
        ):
            path = inputs / f"poster-{movie_id}.jpg"
            path.write_bytes(cropped)
            if note := getattr(session, "note", None):
                note(path.name, images[0], "image/jpeg")
