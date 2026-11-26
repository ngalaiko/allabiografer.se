"""Capture Hypnos Theatre's public programme."""

from parse.parsers.hypnostheatre_com import _URL

from .._shared import capture


def fetch_pages(session, inputs, today, *, selectors=None):
    capture(session, _URL, inputs / "programme.html")
