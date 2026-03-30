"""Shared utilities for parsers."""

import datetime
from zoneinfo import ZoneInfo

# Swedish cinema times are in CET/CEST.
_TZ = ZoneInfo("Europe/Stockholm")


def infer_year(month: int) -> int:
    """Infer the year for a parsed month with no explicit year.

    If the parsed month is before the current month, the screening
    must be next year (e.g. parsing January dates while in November).
    """
    today = datetime.datetime.now(tz=_TZ).date()
    if month < today.month:
        return today.year + 1
    return today.year
