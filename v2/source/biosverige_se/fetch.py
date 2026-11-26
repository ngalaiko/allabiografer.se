"""Capture all BioSverige schedule APIs and the Tickster pages they need."""

from datetime import datetime

from parse.parsers import _tickster
from parse.parsers.biosverige_se import _SITES

from .._shared import STOCKHOLM, capture_json, fetch_cities_main, stable_key
from .parse import schedule_rows, tickster_path


class CaptureTickster:
    def __init__(self, session, inputs):
        self.session = session
        self.inputs = inputs

    def get(self, url, timeout=None):
        response = self.session.get(url, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        tickster_path(self.inputs, url).write_bytes(response.content)
        return response


def fetch_pages(session, inputs, cities):
    today = datetime.fromtimestamp(int(inputs.parents[1].name), STOCKHOLM).date()
    params = {"StartDate": today.isoformat(), "Limit": 500, "Months": 12, "Days": 365}
    tickets = CaptureTickster(session, inputs)
    for site in _SITES:
        if cities and site.city not in cities:
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


if __name__ == "__main__":
    fetch_cities_main("biosverige_se", fetch_pages)
