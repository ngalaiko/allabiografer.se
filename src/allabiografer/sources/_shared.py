"""Capture helpers and the row contract shared by source adapters.

Fetch adapters expose `fetch_pages(session, inputs, today, *, selectors=None)` and
write captures into `inputs` by file name. Parse adapters expose `rows(inputs, today)`
yielding `(venue, show_id, start, ticket, version, presentation, movie_id, capture, movie)`,
where `venue[0]` is the adapter's venue ID (None for single-cinema adapters)
and `capture` names the file the movie came from.
"""

import json
import re
from hashlib import sha256
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from allabiografer import normalize as _version

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def stable_key(*parts):
    return sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def saved(session, path, response):
    """Write a response body and report its origin to a recording session."""
    path.write_bytes(response.content)
    if note := getattr(session, "note", None):
        note(path.name, response.url, response.headers.get("Content-Type", ""))


def capture_json(session, url, path, *, body=None, params=None):
    response = session.get(url, params=params, timeout=30) if body is None else session.post(url, json=body, timeout=30)
    response.raise_for_status()
    data = response.json()
    saved(session, path, response)
    return data


def capture(session, url, path):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    saved(session, path, response)
    return read_page(path)


def film_id(url):
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
        raise ValueError(f"Unexpected film URL: {url}")
    return slug


def read_page(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def single(selectors):
    """Reject selections other than an adapter's only cinema, whose venue ID is None."""
    if selectors is not None and selectors != {None}:
        raise ValueError(f"Single-cinema adapter cannot select {sorted(map(str, selectors))}")


def facts(*, format="", language="", subtitles="", source_texts=(), audio_role_text=""):
    """Typed (version, presentation) from a source's format and language labels."""
    found = _version.screening_facts(
        format=format,
        language=language,
        subtitles=subtitles,
        source_texts=tuple(source_texts),
        audio_role_text=audio_role_text,
    )
    return found["version"], found["presentation"]


def single_venue_rows(venue_id, screenings):
    """Rows for adapters that publish one cinema and link each film to its own page."""
    for show_id, start, ticket, audio, subtitles, url, title, description, runtime, credits in screenings:
        slug = film_id(url)
        yield (
            (venue_id,),
            show_id,
            start,
            ticket,
            *facts(language=audio, subtitles=subtitles),
            slug,
            f"movie-{slug}.html",
            movie_fields(title, url, description, runtime, credits),
        )


def movie_fields(title, url, description, runtime, credits=None, *, year="", alternate=""):
    return {
        "name": title,
        "url": url,
        **({"description": description} if description else {}),
        **({"duration": f"PT{runtime}M"} if runtime else {}),
        **({"datePublished": year} if year else {}),
        **({"alternateName": alternate} if alternate else {}),
        **{
            role: [{"@type": "Person", "name": name} for name in dict.fromkeys(names) if name]
            for role, names in (credits or {}).items()
            if names
        },
    }
