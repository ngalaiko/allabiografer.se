"""Parse the Stockholm screenings in Nortic's saved response."""

import json
from datetime import datetime

from allabiografer import normalize as _version
from allabiografer.sources.nortic_se.site import (
    _COMPOSER,
    _DUBBED,
    _OTHER_PROGRAMMES,
    _SPEECH,
    _arena,
    _broadcasts,
    _cinema_names,
    _city,
    _film,
    _is_screening,
    _text,
    _title,
)

from .._shared import STOCKHOLM, facts, movie_fields, stable_key

_VENUE_ALIASES = {
    "d97e37737b8573ad9ae80537": "e381546df50c3bd3bfeada04",
    "28437ac4a171ab3665e2f2d2": "5abe9f74b43fc5a465bff57e",
}


def rows(inputs, today):
    capture = "events.json"
    events = json.loads((inputs / capture).read_bytes())["events"]
    broadcasters = {
        e["organizerId"] for e in events if e.get("organizerId") and e.get("category") == "Opera" and _broadcasts(e)
    }
    films = [e for e in events if _is_screening(e, broadcasters)]
    names = _cinema_names(films)
    seen = set()
    for event in films:
        shows = [
            show for show in event.get("shows") or [] if _city(show) and show.get("link") and show.get("startDate")
        ]
        if not shows:
            continue
        title, _ = _title(event["title"])
        if event.get("category") == "Opera":
            title = _COMPOSER.sub("", title)
        title, fmt, _, subtitles = _version.split_title(title)
        film = _film(event, title)
        desc = _text(event.get("description"))
        audio, stated_subtitles = _version.from_text(desc)
        for show in shows:
            start = datetime.fromisoformat(show["startDate"])
            start = start.astimezone(STOCKHOLM) if start.tzinfo else start.replace(tzinfo=STOCKHOLM)
            if start.date() < today:
                continue
            arena, _ = _arena(show)
            city = _city(show)
            cinema = names.get((event.get("organizerId"), city, arena), arena)
            if not cinema or (city, cinema) in _OTHER_PROGRAMMES:
                continue
            if city in {"Midsommarkransen", "Spånga"}:
                city = "Stockholm"
            ticket = show["link"]
            show_id = stable_key(city, cinema, start.isoformat(), ticket)
            if show_id in seen:
                continue
            seen.add(show_id)
            venue_id = stable_key(city, cinema)
            yield (
                (_VENUE_ALIASES.get(venue_id, venue_id), cinema, show.get("arenaAddress") or "", city),
                show_id,
                start,
                ticket,
                *facts(
                    format=fmt,
                    language=audio if _DUBBED.search(desc) or _SPEECH.search(desc) else "",
                    subtitles=subtitles or stated_subtitles,
                ),
                stable_key(film.key),
                capture,
                movie_fields(film.title, film.url, film.overview, film.runtime, alternate=film.title_original),
            )
