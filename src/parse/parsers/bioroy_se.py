"""bioroy.se — Next.js with __NEXT_DATA__ JSON containing full schedule."""

import html
import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "bioroy_se"
_URL = "https://www.bioroy.se/"
_HOST = "www.bioroy.se"
_CINEMA = "Bio Roy"
_CITY = "Göteborg"
_ADDRESS = "Kungsportsavenyen 45"
# The CMS emits media URLs for its own origin; the crop parameters are ours to set.
_POSTER_SIZE = {"width": "500", "height": "750"}


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    resp = session.get(_URL, timeout=30)
    resp.raise_for_status()

    m = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not m:
        raise ValueError("bioroy.se: no JSON data found")

    data = json.loads(m.group(1))
    for item in _parse_program_list(data["props"]["pageProps"]["programList"]):
        yield _films.register(item, session=session) if isinstance(item, Film) else item


def _text(raw: str | None) -> str:
    """Plain text from an HTML fragment."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw or "")).split())


def _poster_url(image: dict | None) -> str:
    """The site's own 2:3 crop, re-requested at poster size."""
    crops = {c.get("alias"): c for c in (image or {}).get("crops") or []}
    url = (crops.get("poster") or {}).get("url") or ""
    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query)) | _POSTER_SIZE
    return urlunsplit(("https", _HOST, parts.path, urlencode(query), ""))


def _film(feature: dict) -> Film:
    info = feature.get("info") or {}
    return _films.make(
        _SOURCE,
        info["title"],
        overview=_text(info.get("synopsis")),
        runtime=info.get("duration"),
        genres=[g["name"] for g in info.get("genres") or [] if g.get("name")],
        age_rating=info.get("ageLimit") or "",
        release_date=(feature.get("premiereDate") or "")[:10],
        poster_url=_poster_url(info.get("image")),
        url=feature.get("url") or "",
    )


def _parse_program_list(pl: dict) -> Iterator[Screening | Film]:
    features = {f["id"]: f for f in pl.get("features", [])}

    films: dict[str, Film] = {}
    screenings: list[Screening] = []
    for entry in pl.get("schedule", []):
        feature = features.get(entry.get("featureId")) or {}
        info = feature.get("info") or {}
        film_title = info.get("title", "")
        if not film_title:
            continue
        if film_title == "Biosalongen abonnerad":
            continue
        tmdb_id = _tmdb(film_title, runtime=info.get("duration"))
        film = _film(feature)

        for show in entry.get("dates", []):
            raw = show.get("startDate", "")
            ticket_url = show.get("ticksterLink", "")
            if not raw or not ticket_url:
                continue
            if show.get("soldOut"):
                continue

            dt = datetime.fromisoformat(raw.rstrip("Z"))

            screenings.append(
                Screening(
                    tmdb_id=tmdb_id,
                    title=film_title,
                    date=dt.date(),
                    time=dt.time(),
                    ticket_url=ticket_url,
                    cinema_name=_CINEMA,
                    city=_CITY,
                    screen=show.get("saloonLabel", ""),
                    language=info.get("audioLanguage") or "",
                    subtitles=info.get("textLanguage") or "",
                    film_key=film.key,
                )
            )
            films.setdefault(film.key, film)

    yield from films.values()
    yield from screenings

    log.info("bioroy.se: %d screenings, %d films", len(screenings), len(films))
