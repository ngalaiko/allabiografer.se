"""Capture Hypnos Theatre's public programme."""

from parse.parsers.hypnostheatre_com import _URL

from .._shared import capture, fetch_main


def fetch_pages(session, inputs):
    capture(session, _URL, inputs / "programme.html")


if __name__ == "__main__":
    fetch_main("hypnostheatre_com", fetch_pages)
