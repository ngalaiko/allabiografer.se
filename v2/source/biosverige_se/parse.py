"""Replay BioSverige schedules and Tickster ticket evidence from disk."""

import json
from datetime import datetime
from types import SimpleNamespace

from requests import ConnectionError as RequestConnectionError

from parse.parsers import _biosverige_api, _tickster
from parse.parsers.biosverige_se import _SITES

from .._shared import STOCKHOLM, facts, movie_fields, stable_key


def tickster_path(inputs, url):
    return inputs / f"tickster-{stable_key(url)}.html"


class SavedTickster:
    def __init__(self, inputs):
        self.inputs = inputs

    def get(self, url, timeout=None):
        path = tickster_path(self.inputs, url)
        if not path.is_file():
            raise RequestConnectionError(f"not captured: {url}")
        return SimpleNamespace(text=path.read_text(encoding="utf-8"), raise_for_status=lambda: None)


def schedule_rows(items):
    for item in items:
        for title, _, _, screen, language, subtitles, movie, ticket, _ in _biosverige_api.showtimes([item]):
            when = datetime.fromisoformat(item["startDate"])
            start = when.astimezone(STOCKHOLM) if when.tzinfo else when.replace(tzinfo=STOCKHOLM)
            yield item.get("id"), title, start, screen, language, subtitles, movie, ticket


def venue_id(url):
    return stable_key(url)


def rows(inputs, today):
    for site in _SITES:
        site_id = stable_key(site.url)
        path = inputs / f"schedule-{site_id}.json"
        if not path.is_file():
            continue
        items = json.loads(path.read_bytes())
        if not isinstance(items, list):
            raise ValueError(f"BioSverige: {site.url} returned a non-list schedule")
        upcoming = [row for row in schedule_rows(items) if row[2].date() >= today]
        programme = (
            _tickster.Programme.fetch(site.programme, SavedTickster(inputs)) if upcoming and site.programme else None
        )
        seen = set()
        movies = {}
        for event_id, title, start, screen, audio, subtitles, movie, booking in upcoming:
            movie_id = stable_key(site_id, movie.get("id") or movie.get("slug") or title)
            show_id = (
                stable_key(site_id, event_id)
                if event_id is not None
                else stable_key(site_id, movie_id, start.isoformat(), screen, booking)
            )
            if show_id in seen:
                continue
            seen.add(show_id)
            event = None
            if programme is not None:
                event, audio, subtitles, _ = _biosverige_api.showing(
                    programme, title, start.date(), start.time(), audio, subtitles
                )
            if movie_id not in movies:
                details = _biosverige_api.film_details(movie)
                url = f"{site.url}/filmer/{movie['slug']}" if movie.get("slug") else ""
                credits = {
                    role: [name.strip() for name in (movie.get(key) or "").split(",") if name.strip()]
                    for role, key in (("director", "director"), ("actor", "actors"))
                }
                fields = movie_fields(
                    title,
                    url,
                    details["overview"],
                    details["runtime"],
                    credits,
                    year=details["release_date"],
                    alternate=details["title_original"],
                )
                for key, value in (
                    ("image", details["poster_url"]),
                    ("genre", details["genres"]),
                    ("contentRating", details["age_rating"]),
                ):
                    if value:
                        fields[key] = value
                movies[movie_id] = fields
            yield (
                (venue_id(site.url), site.name, site.address, site.city),
                show_id,
                start,
                booking or (event.url if event else site.tickets),
                *facts(language=audio, subtitles=subtitles),
                movie_id,
                path.name,
                movies[movie_id],
            )
