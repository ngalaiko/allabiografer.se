"""Shared test fixtures."""

from datetime import datetime
from types import SimpleNamespace

import pytest

import store
from parse import _util


@pytest.fixture
def store_clock(monkeypatch):
    # January 2 in Stockholm, but still January 1 in UTC.
    instant = datetime.fromisoformat("2026-01-01T23:30:00+00:00")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(store, "datetime", FrozenDateTime)


@pytest.fixture
def parser_clock(monkeypatch, request):
    """Freeze year inference to the HTML fixtures' capture date."""
    instant = datetime.fromisoformat(getattr(request, "param", "2026-09-20T12:00:00+02:00"))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(_util, "datetime", SimpleNamespace(datetime=FrozenDateTime))
