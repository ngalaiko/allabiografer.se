"""Capture Nortic's public events response."""

from parse.parsers.nortic_se import _API

from .._shared import capture_json


def fetch_pages(session, inputs, today, *, selectors=None):
    capture_json(session, _API, inputs / "events.json")
