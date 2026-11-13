"""Verified Tickster cinema organisers not already covered by another source."""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from parse import _http, _version
from parse.parsers import _films, _tickster
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)
_SOURCE = "tickster_se"
_BASE = "https://www.tickster.com/se/sv/events/by/"
_TZ = ZoneInfo("Europe/Stockholm")


@dataclass(frozen=True)
class _Site:
    organiser: str
    name: str
    city: str
    venue: str = ""


# Do not add cinemas already imported via bio.se, Cinemascenen, BioSverige, etc.
# Some organisers also sell tickets for concerts, theatre and other venues.
_SITES = (
    _Site("8efk0t38a63ealr/kulturhuset-finspang", "Kulturhuset Finspång", "Finspång"),
    _Site("mxrn1p8013ak53k/emmaboda-folketshus", "Emmaboda Folkets Hus", "Emmaboda"),
    _Site("r81ewlrj3upvvm7/storm", "Storm", "Grebbestad"),
    _Site("6fyy0bjpl74d6r5/florabiografen", "Flora Biografteater", "Sjöbo"),
    _Site("z46gh66v0v951ac/bobo-film", "Biograf Aniara", "Gnesta"),
    _Site("cm4wj7hhvxmhhb8/vilhelmina-f-h", "Vilhelmina Folkets Hus", "Vilhelmina"),
    _Site("57775z43gv88xrk/folkets-hus-sater", "Folkets Hus Säter", "Säter", "Biosalongen"),
    _Site("tntfe5rzu5zybfl/folketshus-alvsbyn", "Folkets Hus Älvsbyn", "Älvsbyn", "Andromeda"),
    _Site("ddaey584vk71j32/kristianstad-rtf", "Roxy Bio", "Kristianstad"),
    _Site("agd4gkadcmcxeeg/metropol-kultur", "Metropol Kultur", "Karlshamn"),
    _Site("1m4h76jn8pvw8b0/ersboda-folkets-hus", "Ersboda Folkets Hus", "Umeå"),
    _Site("3gaa3vubd6a3yr5/skarpnacks-kulturhus", "Skarpnäcks Kulturhus", "Skarpnäck", "A-salen"),
)

_NOT_A_SHOWING = re.compile(r"presentkort|medlemskort|säsongskort|abonnemang|\bmall\b", re.IGNORECASE)
_PREFIX = re.compile(r"^(Knattebio|Barnbio|Familjebio|Dagbio|Bio)\s*[:-]\s*", re.IGNORECASE)
_SUFFIX = re.compile(r"\s+-\s+(Lunchbio|Dagbio)$", re.IGNORECASE)
_SCREEN = re.compile(r"\s+sal\s*(\d+)$", re.IGNORECASE)


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()
    today = datetime.now(_TZ).date()
    seen: set[str] = set()
    films: set[str] = set()
    for site in _SITES:
        yield Venue(name=site.name, city=site.city)
        url = _BASE + site.organiser
        pages: set[str] = set()
        count = 0
        while url:
            if url in pages:
                raise ValueError(f"Tickster pagination loop: {url}")
            pages.add(url)
            response = session.get(url, timeout=30)
            response.raise_for_status()
            events, url = _tickster.listing(response.text)
            for item in events:
                # Gift cards and reusable event templates can have dates decades ahead.
                if (
                    item.url in seen
                    or not today <= item.date <= today + timedelta(days=365)
                    or _NOT_A_SHOWING.search(item.title)
                ):
                    continue
                seen.add(item.url)
                response = session.get(item.url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                if not any(a.get_text(strip=True).casefold() == "bio" for a in soup.select("a[rel=tag]")):
                    continue
                event = _tickster.event(response.text)
                if not event or not event.start or not event.title:
                    raise ValueError(f"Unreadable Tickster screening: {item.url}")
                location = soup.select_one("[itemprop=location]")
                city = location.select_one("[itemprop=addressLocality]") if location else None
                venue = site.venue or site.name
                if (
                    not city
                    or city.get_text(strip=True).casefold() != site.city.casefold()
                    or not event.venue.startswith(venue)
                ):
                    continue
                if _NOT_A_SHOWING.search(event.title):
                    continue
                status = soup.select_one("[itemprop=eventStatus]")
                if status and "EventCancelled" in str(status):
                    continue

                raw, language, subtitles = _tickster.version(event.title)
                labels = list(_tickster.labels(event.title))
                if prefix := _PREFIX.match(raw):
                    labels.append(prefix.group(1))
                    raw = raw[prefix.end() :]
                if suffix := _SUFFIX.search(raw):
                    labels.append(suffix.group(1))
                    raw = raw[: suffix.start()]
                screen = event.venue.removeprefix(site.name).strip(" ,-")
                if room := _SCREEN.search(raw):
                    screen = "Salong " + room.group(1)
                    raw = raw[: room.start()]
                # Some Roxy titles end in the showing's clock time.
                title = raw.removesuffix(event.start.strftime(" %H.%M")).strip()
                description = soup.select_one("#event-description")
                if description:
                    for credits in description.select("[itemprop=description]"):
                        credits.decompose()
                film = _films.make(
                    _SOURCE,
                    title,
                    url=event.url,
                    overview=description.get_text(" ", strip=True) if description else "",
                )
                # Tickster supplies landscape banners and event slots, not film posters or runtimes.
                if film.key not in films:
                    films.add(film.key)
                    yield film
                yield Screening(
                    title=title,
                    film_key=film.key,
                    tmdb_id=_tmdb(title),
                    date=event.date,
                    time=event.start.time(),
                    ticket_url=event.url,
                    cinema_name=site.name,
                    city=site.city,
                    screen=screen,
                    **_version.screening_facts(language=language, subtitles=subtitles, raw_attributes=tuple(labels)),
                )
                count += 1
        log.info("Tickster: %s: %d screenings", site.name, count)
