"""Folkets Hus och Parker — Bio Roy, Spegeln and Röda Kvarn."""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from allabiografer import normalize as _version
from allabiografer.model.version import Language
from allabiografer.sources import _films

if TYPE_CHECKING:
    from allabiografer.model import Film

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
_TZ = ZoneInfo("Europe/Stockholm")
# The CMS emits media URLs for its own origin; the crop parameters are ours to set.
_POSTER_SIZE = {"width": "500", "height": "750"}
_PRIVATE_HIRE = "Biosalongen abonnerad"
# Audio codes for a track without speech.
_SILENT = {"STUM"}
# Series title prefixes: "Sing Along: Grease", "Met: Tosca".
_SERIES_PREFIX = re.compile(
    r"^(?P<label>sing\s+along|party\s+along|cine|(?P<live>met|national\s+theatre|balett))\s*:\s*", re.IGNORECASE
)


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
