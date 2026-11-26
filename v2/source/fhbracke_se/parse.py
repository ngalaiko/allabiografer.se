"""Build Bräcke's catalogue from the saved local programme and Tickster listings."""

from datetime import datetime
from urllib.parse import urljoin

from parse.parsers import _tickster
from parse.parsers import fhbracke_se as site
from store import title_key

from .._shared import STOCKHOLM, catalogue_main, stable_key
from ..tickster_se.pages import Pages, source_movie
from .fetch import SOURCE, broadcast_page, programme_rows

VENUE = ("bracke-bio", site._CINEMA, site._ADDRESS, site._CITY)


def rows(inputs, today):
    pages = Pages(inputs)
    seen = set()
    for show, event, broadcast in programme_rows(pages, today):
        title = show["title"]
        url = show["url"]
        html = pages.text(url, optional=True)
        if broadcast:
            time, overview = broadcast_page(pages, show, event, html) if html else (None, "")
            if time is None:
                continue
            title = site._PROGRAMME_SUFFIX.sub("", title)
            details = {"overview": overview}
        else:
            time = show["time"]
            details = site._details(html) if html else {}
        if show["poster_url"]:
            details["poster_url"] = urljoin(url, show["poster_url"])
        _, audio, subtitles = _tickster.version(event.title) if event else ("", "", "")
        start = datetime.combine(show["date"], time, STOCKHOLM)
        ticket = event.url if event else url
        show_id = stable_key(url, start.isoformat(), ticket)
        if show_id in seen:
            continue
        seen.add(show_id)
        yield (
            VENUE,
            show_id,
            start,
            ticket,
            audio,
            subtitles,
            stable_key(broadcast, title_key(title)),
            pages.filename(url if html else site._URL),
            source_movie(title, url, details),
        )


if __name__ == "__main__":
    catalogue_main(SOURCE, rows)
