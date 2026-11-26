"""Capture Nortic's public events response."""

from parse.parsers.nortic_se import _API

from .._shared import capture_json, fetch_main


def fetch_pages(session, inputs):
    capture_json(session, _API, inputs / "events.json")


if __name__ == "__main__":
    fetch_main("nortic_se", fetch_pages)
