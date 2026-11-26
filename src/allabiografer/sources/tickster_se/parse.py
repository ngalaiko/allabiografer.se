"""Build a source catalogue from saved Tickster listings and events."""

import re

from bs4 import BeautifulSoup

from allabiografer.model import title_key
from allabiografer.sources import _tickster
from allabiografer.sources.tickster_se.site import _NOT_A_SHOWING, _PREFIX, _SCREEN, _SUFFIX, _runtime

from .._shared import facts, stable_key
from .fetch import candidates
from .pages import Pages, source_movie

_EXTRA_PREFIX = re.compile(r"^(Extravisning|Live på bio)\s*[:-]\s*", re.IGNORECASE)
_COMBINED_VERSION = re.compile(r"\((\w+\.?\s*tal)\s*&\s*(\w+\.?\s*(?:txt|text))\)", re.IGNORECASE)


def rows(inputs, today):
    pages = Pages(inputs)
    screenings = []
    films = {}
    seen = set()
    for site, item in candidates(pages, today):
        html = pages.text(item.url, optional=True)
        soup = BeautifulSoup(html, "html.parser")
        if not any(tag.get_text(strip=True).casefold() == "bio" for tag in soup.select("a[rel=tag]")):
            continue
        event = _tickster.event(html)
        if not event or not event.start or not event.title:
            raise ValueError(f"Unreadable Tickster screening: {item.url}")
        location = soup.select_one("[itemprop=location]")
        city = location.select_one("[itemprop=addressLocality]") if location else None
        if (
            not city
            or city.get_text(strip=True).casefold() != site.city.casefold()
            or not event.venue.startswith(site.venue or site.name)
            or _NOT_A_SHOWING.search(event.title)
            or event.date < today
        ):
            continue
        status = soup.select_one("[itemprop=eventStatus]")
        if status and "EventCancelled" in str(status):
            continue
        if event.url in seen:
            continue
        seen.add(event.url)
        raw, audio, subtitles = _tickster.version(_COMBINED_VERSION.sub(r"(\1) (\2)", event.title))
        raw = _EXTRA_PREFIX.sub("", raw)
        raw = _PREFIX.sub("", raw)
        raw = _SUFFIX.sub("", raw)
        raw = _SCREEN.sub("", raw)
        title = raw.removesuffix(event.start.strftime(" %H.%M")).strip()
        description = soup.select_one("#event-description")
        if description:
            for credits in description.select("[itemprop=description]"):
                credits.decompose()
        overview = description.get_text(" ", strip=True) if description else ""
        slug = stable_key(title_key(title))
        if slug not in films or (overview and not films[slug][1].get("description")):
            films[slug] = (
                pages.filename(item.url),
                source_movie(title, event.url, {"overview": overview, "runtime": _runtime(overview)}),
            )
        street = location.select_one("[itemprop=streetAddress]")
        address = (street.get("content") or street.get_text(" ", strip=True)) if street else ""
        venue = (site.organiser.split("/", 1)[0], site.name, address, site.city)
        screenings.append(
            (venue, stable_key(event.url), event.start, event.url, *facts(language=audio, subtitles=subtitles), slug)
        )
    for row in screenings:
        yield (*row, *films[row[-1]])
