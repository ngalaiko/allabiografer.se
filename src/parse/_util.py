"""Shared utilities for parsers."""

import datetime
from zoneinfo import ZoneInfo

# Swedish cinema times are in CET/CEST.
_TZ = ZoneInfo("Europe/Stockholm")


def infer_year(month: int) -> int:
    """Infer the year for a parsed month with no explicit year.

    The previous month is a recent past screening still listed; other
    months before the current one are next year (e.g. January parsed in
    November).
    """
    today = datetime.datetime.now(tz=_TZ).date()
    if month == (today.month - 2) % 12 + 1:
        return today.year - 1 if today.month == 1 else today.year
    if month < today.month:
        return today.year + 1
    return today.year
