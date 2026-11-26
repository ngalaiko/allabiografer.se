"""biorio.se — the site's public showtimes and movie JSON API."""

import logging
import re
from datetime import date, time

log = logging.getLogger(__name__)

_SITE = "https://www.biorio.se"
_API = "https://api.biorio.se/api/public/site"
# The default page holds 50 showtimes; the whole programme is a few hundred at most.
_SHOWTIMES_URL = f"{_API}/showtimes?limit=1000"


# Showtime statuses the box office will not sell.
_CANCELLED = re.compile(r"cancel", re.IGNORECASE)

# "13:15", "13:15:00".
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::\d{2})?")

# Placeholders the API writes for an unstated language.
_UNSTATED = {"", "-", "n/a", "tba", "tbc", "ej angivet"}


def _label(text: str | None) -> str:
    text = (text or "").strip()
    return "" if text.casefold() in _UNSTATED else text


def _release_date(movie: dict) -> str:
    """releaseDate where it falls in releaseYear; it is otherwise a Swedish premiere or booking date."""
    year = str(movie.get("releaseYear") or "")
    full = movie.get("releaseDate") or ""
    return full if year and full[:4] == year else year


def _show_time(text: object) -> time | None:
    """Time from "13:15" or "13:15:00"."""
    m = _TIME.fullmatch(text.strip()) if isinstance(text, str) else None
    try:
        return time(int(m.group(1)), int(m.group(2))) if m else None
    except ValueError:
        return None


def _show_date(text: object) -> date | None:
    try:
        return date.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        return None
