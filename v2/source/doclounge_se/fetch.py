"""Capture Doc Lounge's event listing and film pages."""

from parse.parsers.doclounge_se import _FILM_URL, _URL, _events, _film_slugs

from .._shared import capture, fetch_main, stable_key


def fetch_pages(session, inputs, *, selectors=None):
    path = inputs / "programme.html"
    capture(session, _URL, path)
    html = path.read_text(encoding="utf-8")
    slugs = _film_slugs(html)
    urls = {
        _FILM_URL + slugs[title]
        for title, _, _, _, name, city, *_ in _events(html)
        if title in slugs and (selectors is None or stable_key(city, name) in selectors)
    }
    for url in sorted(urls):
        capture(session, url, inputs / f"movie-{stable_key(url)}.html")


if __name__ == "__main__":
    fetch_main("doclounge_se", fetch_pages)
