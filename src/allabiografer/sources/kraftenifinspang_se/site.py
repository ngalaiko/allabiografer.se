"""Free film screenings in Kraften i Finspång's public local calendar."""

import re
from datetime import UTC, datetime
from html import unescape
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from allabiografer import normalize as _version
from allabiografer.model import Venue
from allabiografer.sources import _films

_SOURCE = "kraftenifinspang_se"
_URL = "https://kraftenifinspang.se/wp-json/tribe/events/v1/events"
_TZ = ZoneInfo("Europe/Stockholm")
_FREE = re.compile(r"^(?:fri entr[eé]|gratis|kostnadsfri(?:tt)?|0(?:[.,]0+)?\s*(?:kr|sek)?)\s*!?$", re.IGNORECASE)
_PREFIX = re.compile(r"^(?:Knattebio|Barnbio|Familjebio|Dagbio|Bio)\s*:\s*", re.IGNORECASE)
_SUFFIX = re.compile(r"\s+[-–—]\s*(?:fri entr[eé]|gratis)\s*!?$", re.IGNORECASE)
_TICKSTER = re.compile(r"https?://(?:[\w-]+\.)?tickster\.com/", re.IGNORECASE)


def _showtimes(events, today):
    for event in events:
        fields = event.get("custom_fields") or {}
        if not any("Film/Bio" in field["value"].split("|") for field in fields.values()):
            continue
        # A missing price is unknown, not free; paid listings belong to Tickster.
        if not _FREE.fullmatch(unescape(event.get("cost", "")).strip()) or event.get("all_day"):
            continue
        description = BeautifulSoup(event.get("description", ""), "html.parser")
        if _TICKSTER.match(unescape(event.get("website", ""))) or description.find("a", href=_TICKSTER):
            continue
        venue = event.get("venue") or {}
        name, city = venue.get("venue", "").strip(), venue.get("city", "").strip()
        if not name or not city or (city, name) == ("Finspång", "Kulturhuset Finspång"):
            continue  # Tickster owns Kulturhuset's programme.
        # The API supplies UTC separately; convert it before taking the local date and time.
        start = datetime.fromisoformat(event["utc_start_date"]).replace(tzinfo=UTC).astimezone(_TZ)
        if start.date() < today:
            continue
        raw = _SUFFIX.sub("", _PREFIX.sub("", unescape(event["title"]))).strip()
        title, fmt, language, subtitles = _version.split_title(raw)
        film = _films.make(_SOURCE, title, url=event["url"], overview=description.get_text(" ", strip=True))
        yield Venue(name=name, city=city, address=venue.get("address", "")), film, start, fmt, language, subtitles
