"""Tickster event pages: organiser listings, per-event microdata and showing lookup.

An organiser page (``/se/sv/events/by/<id>/<slug>``) lists one card per
showing with its date, title and venue, 24 per page. Start times are only on
the event pages, so those are fetched when a date holds several showings of
one title.
"""

import logging
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from typing import Protocol
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from parse import _version

log = logging.getLogger(__name__)

_BASE = "https://www.tickster.com"
_PAGES = 5
_TZ = ZoneInfo("Europe/Stockholm")

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "maj": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}

# "4 okt 2026, Söderköpings Bio", "5 okt 2026, Hallunda Folkets Hus - Brage, Norsborg"
_LABEL = re.compile(r"(\d{1,2})\s+([a-zåäö]{3})\w*\s+(\d{4}),\s*([^,]+)", re.IGNORECASE)

# "(Tal: Engelska)", "(Text: Svenska)"; titles are cut at 50 characters, which can drop the ")".
_TAG = re.compile(r"\(\s*(Tal|Text|Txt)\s*:\s*([^()]*?)\s*(?:\)|$)", re.IGNORECASE)
_PARENS = re.compile(r"\([^)]*\)?")
# Listing titles longer than this may be cut mid-word.
_CUT = 45


class _Session(Protocol):
    def get(self, url: str, timeout: float | None = ...) -> requests.Response: ...


@dataclass(frozen=True)
class Event:
    """One Tickster showing."""

    url: str
    title: str
    date: date
    venue: str
    start: datetime | None = None


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def listing(html: str) -> tuple[list[Event], str]:
    """Events on one organiser page and the URL of the next page, or ""."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[Event] = []
    for card in soup.select(".c-card"):
        link = card.select_one("a.c-card__body[href]")
        m = _LABEL.search(_text(card.select_one(".c-card__label")))
        month = _MONTHS.get(m.group(2).lower()) if m else None
        if not link or not m or not month:
            continue
        events.append(
            Event(
                url=urljoin(_BASE, link["href"]),
                title=_text(card.select_one(".c-card__title")),
                date=date(int(m.group(3)), month, int(m.group(1))),
                venue=m.group(4).strip(),
            )
        )
    following = next((a["href"] for a in soup.select("a.c-pager__page[href]") if "Nästa" in _text(a)), "")
    return events, urljoin(_BASE, following) if following else ""


def event(html: str) -> Event | None:
    """The showing an event page describes, from its schema.org microdata."""
    soup = BeautifulSoup(html, "html.parser")
    scope = soup.select_one("[itemtype$='schema.org/Event']") or soup
    url = scope.select_one("meta[itemprop=url][content]")
    stamp = scope.select_one("[itemprop=startDate][content]")
    if not url or not stamp:
        return None
    try:
        start = datetime.fromisoformat(stamp["content"]).replace(tzinfo=_TZ)
    except ValueError:
        return None
    return Event(
        url=url["content"],
        title=_text(scope.select_one("h1[itemprop=name]")),
        date=start.date(),
        venue=_text(scope.select_one("[itemprop=location] [itemprop=name]")),
        start=start,
    )


def fetch_event(url: str, session: _Session) -> Event | None:
    """The showing at *url*; None when the page is unreachable or unreadable."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("tickster: %s failed: %s", url, exc)
        return None
    return event(resp.text)


def version(title: str) -> tuple[str, str, str]:
    """Split a Tickster title into (title, language, subtitles).

    Handles "(Tal: Engelska) (Text: Svenska)" and "(Sv. txt)" suffixes.
    """
    language = subtitles = ""
    for kind, value in _TAG.findall(title):
        if kind.lower() == "tal":
            language = language or _version.language(value)
        else:
            subtitles = subtitles or _version.subtitles(value)
    rest, _, spoken, subs = _version.split_title(" ".join(_TAG.sub(" ", title).split()))
    return rest, language or spoken, subtitles or subs


def labels(title: str) -> tuple[str, ...]:
    """Parenthesised programme tags other than the version: "(Dagbio)"."""
    rest = version(title)[0]
    return tuple(tag for m in re.findall(r"\(([^()]*)\)", rest) if (tag := " ".join(m.split())))


def _words(title: str) -> list[str]:
    return re.findall(r"\w+", _PARENS.sub(" ", title).casefold())


def _same(title: str, other: str) -> bool:
    return _words(title) == _words(other)


def _prefix(title: str, other: str) -> bool:
    """One title's words open the other's: "Macbeth" and "Macbeth - Live på bio"."""
    a, b = _words(title), _words(other)
    short, long = sorted((a, b), key=len)
    return bool(short) and long[: len(short)] == short


def same_title(title: str, other: str) -> bool:
    """Titles name the same work, ignoring tags, case and a trailing extension."""
    return _same(title, other) or _prefix(title, other)


def _cut(title: str, listed: str) -> bool:
    """*listed* is *title* cut mid-word at Tickster's title limit."""
    if len(listed) < _CUT:
        return False
    whole = _words(listed)[:-1]
    return bool(whole) and _words(title)[: len(whole)] == whole


class Programme:
    """An organiser's showings, matched to a site's own by date, title and start time."""

    def __init__(self, events: list[Event], session: _Session):
        self.events = events
        self._session = session

    @classmethod
    def fetch(cls, url: str, session: _Session, pages: int = _PAGES) -> "Programme":
        """Every listed showing; empty when the organiser page is unreachable."""
        events: list[Event] = []
        for _ in range(pages):
            try:
                resp = session.get(url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as exc:
                log.warning("tickster: %s failed: %s", url, exc)
                break
            found, url = listing(resp.text)
            events.extend(found)
            if not url:
                break
        return cls(events, session)

    def find(self, title: str, day: date, start: time) -> Event | None:
        """The showing of *title* at *day* *start*; None when none or several fit."""
        same_day = [e for e in self.events if e.date == day]
        candidates = (
            [e for e in same_day if _same(title, e.title)]
            or [e for e in same_day if _prefix(title, e.title)]
            or [e for e in same_day if _cut(title, e.title)]
        )
        if len(candidates) == 1 and candidates[0].start is None:
            return candidates[0]
        timed = [e for e in map(self._timed, candidates) if e.start and e.start.time() == start]
        return timed[0] if len(timed) == 1 else None

    def _timed(self, ev: Event) -> Event:
        """*ev* with its start time read from its page; cached in the listing."""
        if ev.start is not None:
            return ev
        page = fetch_event(ev.url, self._session)
        if page is None or page.start is None:
            return ev
        timed = replace(ev, start=page.start, title=page.title or ev.title, venue=page.venue or ev.venue)
        self.events[self.events.index(ev)] = timed
        return timed
