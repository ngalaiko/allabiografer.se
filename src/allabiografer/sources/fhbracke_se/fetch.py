"""Capture Bräcke's cinema programme, film details, Tickster and broadcast pages."""

from functools import partial

from allabiografer.sources import _tickster
from allabiografer.sources.fhbracke_se import site as site

from .._shared import single
from ..tickster_se.pages import Pages, year_for_month

SOURCE = "fhbracke_se"


def programme_rows(pages, today):
    programme = _tickster.Programme.fetch(site._TICKSTER, pages)
    shows = [
        show
        for show in site._listings(pages.text(site._URL), year_for_month=partial(year_for_month, today))
        if show["date"] >= today
    ]
    matched = set()
    for show in shows:
        event = programme.find(show["title"], show["date"], show["time"])
        if event:
            matched.add(event.url)
        yield show, event, False

    unmatched = [
        e
        for e in programme.events
        if e.date >= today
        and e.url not in matched
        and not any(s["date"] == e.date and _tickster.same_title(s["title"], e.title) for s in shows)
    ]
    if not unmatched:
        return
    cards = list(site._events(pages.text(site._EVENTS, optional=True)))
    for event in unmatched:
        rest, _, _ = _tickster.version(event.title)
        for title, url, poster in cards:
            if _tickster.same_title(title, rest):
                yield {"title": rest, "date": event.date, "url": url, "poster_url": poster}, event, True
                break


def broadcast_page(pages, show, event, html):
    detail = site._event_page(html, show["date"])
    if detail is None:
        return None, ""
    time, overview = detail
    if time is None and (timed := _tickster.fetch_event(event.url, pages)) and timed.start:
        time = timed.start.time()
    return time, overview


def fetch_pages(session, inputs, today, *, selectors=None):
    single(selectors)
    session.headers["User-Agent"] = "Mozilla/5.0"
    pages = Pages(inputs, session)
    for show, event, broadcast in programme_rows(pages, today):
        html = pages.text(show["url"], optional=True)
        if broadcast and html:
            broadcast_page(pages, show, event, html)
