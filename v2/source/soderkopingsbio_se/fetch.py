"""Capture Söderköpings Bio's schedule API and Tickster booking pages."""

from parse.parsers import _biosverige_api, _tickster
from parse.parsers.soderkopingsbio_se import _SITE, _TICKSTER

from .._shared import capture_json, fetch_main
from ..tickster_se.pages import Pages, capture_day

SOURCE = "soderkopingsbio_se"
SCHEDULE = "schedule.json"


def showings(pages, schedule, today):
    if not isinstance(schedule, list):
        raise ValueError("Söderköpings Bio returned a non-list schedule")
    shows = [row for row in _biosverige_api.showtimes(schedule) if row[1] >= today]
    if not shows:
        return
    programme = _tickster.Programme.fetch(_TICKSTER, pages)
    for row in shows:
        title, day, start, _, audio, subtitles, *_ = row
        event, audio, subtitles, _ = _biosverige_api.showing(programme, title, day, start, audio, subtitles)
        yield row, event, audio, subtitles


def fetch_pages(session, inputs):
    today = capture_day(inputs)
    schedule = capture_json(
        session,
        f"{_SITE}/api/eventschedules",
        inputs / SCHEDULE,
        params={"StartDate": today.isoformat(), "Limit": 500, "Months": 12, "Days": 365},
    )
    # Matching can require a detail request to disambiguate same-day showings.
    for _ in showings(Pages(inputs, session), schedule, today):
        pass


if __name__ == "__main__":
    fetch_main(SOURCE, fetch_pages)
