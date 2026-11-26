"""Capture Doc Lounge's event listing and film pages."""

from parse.parsers.doclounge_se import _FILM_URL, _URL, _events, _film_slugs

from .._shared import capture, fetch_main, stable_key


def fetch_pages(session, inputs):
    path = inputs / "programme.html"
    capture(session, _URL, path)
    html = path.read_text(encoding="utf-8")
    slugs = _film_slugs(html)
    for url in sorted({_FILM_URL + slugs[e[0]] for e in _events(html) if e[0] in slugs}):
        capture(session, url, inputs / f"movie-{stable_key(url)}.html")


if __name__ == "__main__":
    fetch_main("doclounge_se", fetch_pages)
