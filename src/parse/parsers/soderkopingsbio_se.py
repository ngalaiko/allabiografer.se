"""soderkopingsbio.se — dx.tech checkout widget, rendered client-side via Playwright."""

import logging
from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

from parse.parsers._browser import page as browser_page
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

log = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Stockholm")
_URL = "https://soderkopingsbio.se/program"
_CINEMA = "Söderköpings Bio"
_CITY = "Söderköping"
_ADDRESS = "Ringvägen 45"

_JS = """() => {
    const results = [];
    for (const a of document.querySelectorAll('a[href*="checkout.dx.tech/screenings/"]')) {
        let parent = a;
        for (let i = 0; i < 8; i++) {
            parent = parent.parentElement;
            if (!parent) break;
            const h = parent.querySelector('h1, h2, h3, h4');
            const time = parent.querySelector('time');
            if (h && time) {
                results.push({
                    title: h.textContent.trim(),
                    datetime: time.getAttribute('datetime') || '',
                    href: a.href,
                });
                break;
            }
        }
    }
    return results;
}"""


def parse() -> Iterator[Screening | Venue]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    with browser_page() as page:
        page.goto(_URL, wait_until="networkidle", timeout=30000)

        for raw in page.evaluate(_JS):
            title = raw.get("title", "").strip()
            dt_str = raw.get("datetime", "")
            href = raw.get("href", "")
            if not title or not dt_str or not href:
                continue
            tmdb_id = _tmdb(title)
            if tmdb_id is None:
                continue
            dt = datetime.fromisoformat(dt_str).astimezone(_TZ)
            yield Screening(
                tmdb_id=tmdb_id,
                date=dt.date(),
                time=dt.time().replace(tzinfo=None),
                ticket_url=href,
                cinema_name=_CINEMA,
                city=_CITY,
            )
