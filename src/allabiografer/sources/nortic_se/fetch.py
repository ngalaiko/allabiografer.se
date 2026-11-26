"""Capture Nortic's public events response."""

from allabiografer.sources.nortic_se.site import _API

from .._shared import capture_json


def fetch_pages(session, inputs, today, *, selectors=None):
    # The feed covers every venue; parse keeps the selected ones.
    if selectors is not None and any(not selector for selector in selectors):
        raise ValueError("Nortic selections need venue IDs")
    capture_json(session, _API, inputs / "events.json")
