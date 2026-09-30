"""Shared test fixtures."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from parse import _util


@pytest.fixture
def parser_clock(monkeypatch, request):
    """Freeze year inference to the HTML fixtures' capture date."""
    instant = datetime.fromisoformat(getattr(request, "param", "2026-09-20T12:00:00+02:00"))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(_util, "datetime", SimpleNamespace(datetime=FrozenDateTime))
