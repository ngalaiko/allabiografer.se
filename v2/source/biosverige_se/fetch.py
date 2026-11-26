"""Capture all BioSverige schedule APIs and the Tickster pages they need."""

from parse.parsers import _tickster
from parse.parsers.biosverige_se import _SITES

from ...schedule import checked
from .._shared import capture_json, saved, stable_key
from .parse import schedule_rows, tickster_path, venue_id


class CaptureTickster:
    def __init__(self, session, inputs):
        self.session = session
        self.inputs = inputs

    def get(self, url, timeout=None):
        response = self.session.get(url, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        saved(self.session, tickster_path(self.inputs, url), response)
        return response


def fetch_pages(session, inputs, today, *, selectors=None):
    params = {"StartDate": today.isoformat(), "Limit": 500, "Months": 12, "Days": 365}
    tickets = CaptureTickster(session, inputs)
    checked(selectors, {venue_id(site.url) for site in _SITES})
    for site in _SITES:
        if selectors is not None and venue_id(site.url) not in selectors:
            continue
        path = inputs / f"schedule-{stable_key(site.url)}.json"
        items = capture_json(session, f"{site.url}/api/eventschedules", path, params=params)
        if not isinstance(items, list):
            raise ValueError(f"BioSverige: {site.url} returned a non-list schedule")
        upcoming = [row for row in schedule_rows(items) if row[2].date() >= today]
        if upcoming and site.programme:
            programme = _tickster.Programme.fetch(site.programme, tickets)
            # Ambiguous same-day title matches cause Programme.find to read event details.
            for _, title, start, *_ in upcoming:
                programme.find(title, start.date(), start.time())
