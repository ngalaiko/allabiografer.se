"""Build Hallunda's catalogue from saved programme, articles and booking pages."""

from datetime import datetime
from urllib.parse import urljoin

from allabiografer.sources import _tickster
from allabiografer.sources.hallundafolketshus_se import site as site

from .._shared import STOCKHOLM, facts, stable_key
from ..tickster_se.pages import Pages, source_movie
from .fetch import articles

VENUE = (None, site._CINEMA, site._ADDRESS, site._CITY)


def rows(inputs, today):
    pages = Pages(inputs)
    for (raw, day, time, url, *_), html, ticket in articles(pages, today):
        event = _tickster.fetch_event(ticket, pages) if ticket else None
        title = site._title(raw, event.title if event else "")
        audio, subtitles = site._stated_version(html) if html else ("", "")
        if event:
            _, spoken, subs = _tickster.version(event.title)
            audio, subtitles = spoken or audio, subs or subtitles
        details = site._details(html) if html else {}
        if url.endswith("/forhandsvisning-av-arets-julkalender-den-ofrivillige-tomten"):
            details.pop("runtime", None)  # The 80-minute event and the four-episode runtime differ.
        if image := details.get("poster_url"):
            details["poster_url"] = urljoin(url, image)
        start = datetime.combine(day, time, STOCKHOLM)
        yield (
            VENUE,
            stable_key(url, start.isoformat()),
            start,
            event.url if event else ticket or url,
            *facts(language=audio, subtitles=subtitles),
            stable_key(title.casefold()),
            pages.filename(url if html else site._URL),
            source_movie(title, url, details),
        )
