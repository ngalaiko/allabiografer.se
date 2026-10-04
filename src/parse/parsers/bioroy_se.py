"""bioroy.se — Next.js with __NEXT_DATA__ JSON containing full schedule."""

import html
import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue
from store.version import Language

log = logging.getLogger(__name__)

_SOURCE = "bioroy_se"
_URL = "https://www.bioroy.se/"
_HOST = "www.bioroy.se"
_CINEMA = "Bio Roy"
_CITY = "Göteborg"
_ADDRESS = "Kungsportsavenyen 45"
# The CMS emits media URLs for its own origin; the crop parameters are ours to set.
_POSTER_SIZE = {"width": "500", "height": "750"}
# Film pages carry the poster itself; the programme only a 2:3 crop of a still.
_PAGE_POSTER_SIZE = {**_POSTER_SIZE, "rmode": "max", "format": "jpg"}
_PRIVATE_HIRE = "Biosalongen abonnerad"
# Audio codes for a track without speech.
_SILENT = {"STUM"}


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    session = _http.session()

    resp = session.get(_URL, timeout=30)
    resp.raise_for_status()

    m = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not m:
        raise ValueError("bioroy.se: no JSON data found")

    pl = json.loads(m.group(1))["props"]["pageProps"]["programList"]
    posters = {feature_id: _poster(session, url) for feature_id, url in _scheduled_pages(pl).items()}
    for item in _parse_program_list(pl, posters={k: v for k, v in posters.items() if v}):
        yield _films.register(item, session=session) if isinstance(item, Film) else item


def _scheduled_pages(pl: dict) -> dict[int, str]:
    """Film page of every feature with shows."""
    features = {f["id"]: f for f in pl.get("features", [])}
    pages: dict[int, str] = {}
    for entry in pl.get("schedule", []):
        feature = features.get(entry.get("featureId")) or {}
        title = (feature.get("info") or {}).get("title", "").strip()
        if title and title != _PRIVATE_HIRE and feature.get("url"):
            pages[feature["id"]] = feature["url"]
    return pages


def _poster(session: requests.Session, url: str) -> str:
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("bioroy.se: film page %s failed: %s", url, exc)
        return ""
    return _page_poster(resp.text)


def _page_poster(page: str) -> str:
    """The poster image picked on a film page, re-requested at poster size."""
    m = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', page, re.DOTALL)
    if not m:
        return ""
    node = json.loads(m.group(1))
    for key in (
        "props",
        "pageProps",
        "page",
        "documentData",
        "connectedFeature",
        "umbracoContent",
        "compositions",
        "posterImageComposition",
        "posterImagePicker",
        "url",
    ):
        node = node.get(key) if isinstance(node, dict) else None
    if not node:
        return ""
    return urlunsplit(("https", _HOST, urlsplit(node).path, urlencode(_PAGE_POSTER_SIZE), ""))


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


def _original_languages(info: dict) -> frozenset:
    """Spoken languages, unless the track may be a dub.

    The site states one audio language per feature.  Swedish speech with no
    stated subtitles, or on animation and family films, may be a Swedish dub.
    """
    audio = info.get("audioLanguage") or ""
    if audio.strip().upper() in _SILENT:
        return frozenset()
    languages = _version.languages(audio)
    genres = {g.get("name", "").casefold() for g in info.get("genres") or []}
    if Language.SWEDISH in languages and (not info.get("textLanguage") or genres & {"animation", "familj", "barn"}):
        return frozenset()
    return languages


def _film(feature: dict, poster_url: str = "") -> Film:
    info = feature.get("info") or {}
    return _films.make(
        _SOURCE,
        info["title"],
        overview=_text(info.get("synopsis")),
        runtime=info.get("duration"),
        genres=[g["name"] for g in info.get("genres") or [] if g.get("name")],
        age_rating=info.get("ageLimit") or "",
        release_date=(feature.get("premiereDate") or "")[:10],
        poster_url=poster_url or _poster_url(info.get("image")),
        url=feature.get("url") or "",
        original_languages=_original_languages(info),
    )


def _parse_program_list(pl: dict, *, posters: dict[int, str] | None = None) -> Iterator[Screening | Film]:
    features = {f["id"]: f for f in pl.get("features", [])}

    films: dict[str, Film] = {}
    screenings: list[Screening] = []
    for entry in pl.get("schedule", []):
        feature = features.get(entry.get("featureId")) or {}
        info = feature.get("info") or {}
        film_title = info.get("title", "").strip()
        if not film_title:
            continue
        if film_title == _PRIVATE_HIRE:
            continue
        tmdb_id = _tmdb(film_title, runtime=info.get("duration"))
        film = _film(feature, (posters or {}).get(feature["id"], ""))
        themes = tuple(t["label"].strip() for t in entry.get("themes") or [] if (t.get("label") or "").strip())
        silent = any("stumfilm" in theme.casefold() for theme in themes)

        for show in entry.get("dates", []):
            raw = show.get("startDate", "")
            ticket_url = show.get("ticksterLink", "")
            if not raw or not ticket_url:
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
                    **_version.screening_facts(
                        language=info.get("audioLanguage") or "",
                        subtitles=info.get("textLanguage") or "",
                        audio_role_text="stumfilm" if silent else "",
                        raw_attributes=themes,
                    ),
                    film_key=film.key,
                )
            )
            films.setdefault(film.key, film)

    yield from films.values()
    yield from screenings

    log.info("bioroy.se: %d screenings, %d films", len(screenings), len(films))
