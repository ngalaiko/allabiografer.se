"""Replay Doc Lounge's event listing and film pages."""

from datetime import datetime

from allabiografer.movie_fields import details_fields
from allabiografer.sources.doclounge_se.site import _FILM_URL, _events, _film_details, _film_slugs, _listed_details

from .._shared import STOCKHOLM, facts, stable_key


def rows(inputs, today):
    html = (inputs / "programme.html").read_text(encoding="utf-8")
    slugs = _film_slugs(html)
    listed = _listed_details(html)
    seen = set()
    for title, day, clock, ticket, name, city, address, _ in _events(html):
        if day < today or not city:
            continue
        start = datetime.combine(day, clock, STOCKHOLM)
        cinema = stable_key(city, name)
        key = stable_key(cinema, title, start.isoformat(), ticket)
        if key in seen:
            continue
        seen.add(key)
        url = _FILM_URL + slugs[title] if title in slugs else ""
        capture = f"movie-{stable_key(url)}.html" if url else "programme.html"
        details = listed.get(title, {}) | (
            {k: v for k, v in _film_details((inputs / capture).read_text(encoding="utf-8")).items() if v} if url else {}
        )
        yield (
            (cinema, name, address, city),
            key,
            start,
            ticket,
            *facts(language=details.get("language_label", ""), subtitles=details.get("subtitle_label", "")),
            stable_key(url or title),
            capture,
            details_fields(title, url, details),
            "programme.html",
        )
