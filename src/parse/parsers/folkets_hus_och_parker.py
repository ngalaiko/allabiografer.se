"""Folkets Hus och Parker — Bio Roy, Spegeln and Röda Kvarn."""

import html
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue
from store.version import Language

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Site:
    source: str
    host: str
    cinema: str
    city: str
    address: str
    excluded_titles: frozenset[str] = frozenset()


_BIO_ROY = Site("bioroy_se", "www.bioroy.se", "Bio Roy", "Göteborg", "Kungsportsavenyen 45")
_SITES = (
    _BIO_ROY,
    Site(
        "biografspegeln_se", "biografspegeln.se", "Spegeln", "Malmö", "Stortorget 29", frozenset({"Spegelns filmquiz"})
    ),
    Site("biorodakvarn_se", "www.biorodakvarn.se", "Röda Kvarn", "Helsingborg", "Karlsgatan 7"),
)
REPLACES_SOURCES = ("bioroy_se",)
_TZ = ZoneInfo("Europe/Stockholm")
# The CMS emits media URLs for its own origin; the crop parameters are ours to set.
_POSTER_SIZE = {"width": "500", "height": "750"}
# Film pages carry the poster itself; the programme only a 2:3 crop of a still.
_PAGE_POSTER_SIZE = {**_POSTER_SIZE, "rmode": "max", "format": "jpg"}
_CROPPED_PAGE_POSTER_SIZE = {**_PAGE_POSTER_SIZE, "rmode": "crop"}
# Height over width below which a picked image is no poster; posters are 1.5.
_MIN_PORTRAIT = 1.25
_PRIVATE_HIRE = "Biosalongen abonnerad"
# Audio codes for a track without speech.
_SILENT = {"STUM"}
# Series title prefixes: "Sing Along: Grease", "Met: Tosca".
_SERIES_PREFIX = re.compile(
    r"^(?P<label>sing\s+along|party\s+along|cine|(?P<live>met|national\s+theatre|balett))\s*:\s*", re.IGNORECASE
)


def parse() -> Iterator[Screening | Venue | Film]:
    for site in _SITES:
        yield from _parse_site(site)


def _parse_site(site: Site) -> Iterator[Screening | Venue | Film]:
    yield Venue(name=site.cinema, city=site.city, address=site.address)
    session = _http.session()

    resp = session.get(f"https://{site.host}/", timeout=30)
    resp.raise_for_status()

    m = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not m:
        raise ValueError(f"{site.host}: no JSON data found")

    pl = json.loads(m.group(1))["props"]["pageProps"]["programList"]
    posters = {
        feature_id: _poster(session, url, site=site) for feature_id, url in _scheduled_pages(pl, site=site).items()
    }
    for item in _parse_program_list(pl, posters={k: v for k, v in posters.items() if v}, site=site):
        yield _films.register(item, session=session) if isinstance(item, Film) else item


def _scheduled_pages(pl: dict, *, site: Site = _BIO_ROY) -> dict[int, str]:
    """Film page of every feature with shows."""
    features = {f["id"]: f for f in pl.get("features", [])}
    pages: dict[int, str] = {}
    for entry in pl.get("schedule", []):
        feature = features.get(entry.get("featureId")) or {}
        title = (feature.get("info") or {}).get("title", "").strip()
        if title and title not in {_PRIVATE_HIRE, *site.excluded_titles} and feature.get("url"):
            pages[feature["id"]] = feature["url"]
    return pages


def _poster(session: requests.Session, url: str, *, site: Site) -> str:
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("%s: film page %s failed: %s", site.host, url, exc)
        return ""
    return _page_poster(resp.text, site=site)


def _page_poster(page: str, *, site: Site = _BIO_ROY) -> str:
    """The poster image picked on a film page, re-requested at poster size.

    Editors sometimes pick a landscape hero; that is no poster.  An image of
    unstated size is cropped to 2:3.
    """
    m = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', page, re.DOTALL)
    if not m:
        return ""
    try:
        node = json.loads(m.group(1))
    except ValueError as exc:
        log.warning("%s: film page JSON invalid: %s", site.host, exc)
        return ""
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
    ):
        node = node.get(key) if isinstance(node, dict) else None
    url = node.get("url") if isinstance(node, dict) else None
    if not url:
        return ""
    media = (node.get("umbracoContent") or {}).get("mediaData") or {}
    width, height = media.get("width"), media.get("height")
    if width and height:
        if height < width * _MIN_PORTRAIT:
            return ""
        size = _PAGE_POSTER_SIZE
    else:
        size = _CROPPED_PAGE_POSTER_SIZE
    return urlunsplit(("https", site.host, urlsplit(url).path, urlencode(size), ""))


def _text(raw: str | None) -> str:
    """Plain text from an HTML fragment."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw or "")).split())


def _poster_url(image: dict | None, *, site: Site = _BIO_ROY) -> str:
    """The site's own 2:3 crop, re-requested at poster size."""
    crops = {c.get("alias"): c for c in (image or {}).get("crops") or []}
    url = (crops.get("poster") or {}).get("url") or ""
    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query)) | _POSTER_SIZE
    return urlunsplit(("https", site.host, parts.path, urlencode(query), ""))


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


def _split_title(title: str) -> tuple[str, str, bool]:
    """Title without its series prefix, the prefix, and whether it marks a live broadcast."""
    m = _SERIES_PREFIX.match(title)
    if not m:
        return title, "", False
    return title[m.end() :], " ".join(m.group("label").split()), bool(m.group("live"))


def _start(raw: str) -> datetime:
    """Local start time; an offset such as "Z" is converted to Stockholm time."""
    dt = datetime.fromisoformat(raw)
    return dt.astimezone(_TZ).replace(tzinfo=None) if dt.tzinfo else dt


def _film(feature: dict, poster_url: str = "", *, site: Site = _BIO_ROY) -> Film:
    info = feature.get("info") or {}
    return _films.make(
        site.source,
        _split_title(info["title"].strip())[0],
        overview=_text(info.get("synopsis")),
        runtime=info.get("duration") or None,
        genres=[g["name"] for g in info.get("genres") or [] if g.get("name")],
        age_rating=info.get("ageLimit") or "",
        release_date=(feature.get("premiereDate") or "")[:10],
        poster_url=poster_url or _poster_url(info.get("image"), site=site),
        url=feature.get("url") or "",
        original_languages=_original_languages(info),
    )


def _parse_program_list(
    pl: dict, *, posters: dict[int, str] | None = None, site: Site = _BIO_ROY
) -> Iterator[Screening | Film]:
    features = {f["id"]: f for f in pl.get("features", [])}

    films: dict[str, Film] = {}
    screenings: list[Screening] = []
    tmdb_ids: dict[tuple[str, int | None, int | None], int | None] = {}
    for entry in pl.get("schedule", []):
        feature = features.get(entry.get("featureId")) or {}
        info = feature.get("info") or {}
        film_title = info.get("title", "").strip()
        if not film_title:
            continue
        if film_title in {_PRIVATE_HIRE, *site.excluded_titles}:
            continue
        film_title, series, live = _split_title(film_title)
        film = _film(feature, (posters or {}).get(feature["id"], ""), site=site)
        themes = tuple(t["label"].strip() for t in entry.get("themes") or [] if (t.get("label") or "").strip())
        labels = ((series,) if series else ()) + themes
        silent = any("stumfilm" in theme.casefold() for theme in themes)

        for show in entry.get("dates", []):
            raw = show.get("startDate", "")
            ticket_url = show.get("ticksterLink", "")
            if not raw or not ticket_url:
                continue

            dt = _start(raw)
            # Live broadcasts share titles with older films of the same work.
            year = dt.year if live else None
            key = (film_title, film.runtime, year)
            if key not in tmdb_ids:
                tmdb_ids[key] = _tmdb(film_title, runtime=film.runtime, year=year)

            screenings.append(
                Screening(
                    tmdb_id=tmdb_ids[key],
                    title=film_title,
                    date=dt.date(),
                    time=dt.time(),
                    ticket_url=ticket_url,
                    cinema_name=site.cinema,
                    city=site.city,
                    screen=show.get("saloonLabel", ""),
                    **_version.screening_facts(
                        language=info.get("audioLanguage") or "",
                        subtitles=info.get("textLanguage") or "",
                        audio_role_text="stumfilm" if silent else "",
                        raw_attributes=labels,
                    ),
                    film_key=film.key,
                )
            )
            films.setdefault(film.key, film)

    yield from films.values()
    yield from screenings

    log.info("%s: %d screenings, %d films", site.host, len(screenings), len(films))
