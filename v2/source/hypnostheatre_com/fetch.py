"""Capture Hypnos Theatre's public programme."""

from parse.parsers.hypnostheatre_com import _URL

from .._shared import capture, single


def fetch_pages(session, inputs, today, *, selectors=None):
    single(selectors)
    capture(session, _URL, inputs / "programme.html")
