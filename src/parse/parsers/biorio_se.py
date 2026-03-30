"""biorio.se — Next.js calendar page, rendered client-side via Playwright."""

import re
from collections.abc import Iterator
from datetime import date, time

from parse._util import infer_year
from parse.parsers._browser import page as browser_page
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Screening, Venue

_URL = "https://www.biorio.se/sv/kalender"
_CINEMA = "Bio Rio"
_CITY = "Stockholm"
_ADDRESS = "Hornstulls strand 3"

_MONTHS = {
    "januari": 1,
    "februari": 2,
    "mars": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "augusti": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}

_JS = """() => {
    const results = [];
    for (const a of document.querySelectorAll('a[href*="/boka/"]')) {
        const img = a.querySelector('img');
        const title = img?.alt || '';

        // Full text is like "10:00I SwearSalong 1 · 120 min"
        // Parse time from the beginning
        const fullText = a.textContent.trim();
        const timeMatch = fullText.match(/^(\\d{1,2}:\\d{2})/);
        const time = timeMatch ? timeMatch[1] : '';

        // Screen from "Salong N" pattern
        const screenMatch = fullText.match(/(Salong\\s*\\d+)/);
        const screen = screenMatch ? screenMatch[1] : '';

        // Find date header by walking up
        let dateText = '';
        let el = a;
        for (let i = 0; i < 10; i++) {
            el = el.parentElement;
            if (!el) break;
            const h = el.querySelector('h2, h3');
            if (h && /\\d{1,2}/.test(h.textContent)) {
                dateText = h.textContent.trim();
                break;
            }
        }

        results.push({title, time, dateText, href: a.href, screen});
    }
    return results;
}"""


def _parse_date(text: str) -> date | None:
    """Parse 'Idag 31 mars', 'Imorgon 1 april', 'Fredag 3 april', etc."""
    m = re.search(r"(\d{1,2})\s+(\w+)", text)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    return date(infer_year(month), month, day)


def parse() -> Iterator[Screening | Venue]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)
    with browser_page() as page:
        page.goto(_URL, wait_until="networkidle", timeout=30000)

        for raw in page.evaluate(_JS):
            title = raw.get("title", "").strip()
            time_str = raw.get("time", "").strip()
            href = raw.get("href", "")
            d = _parse_date(raw.get("dateText", ""))

            if not title or not time_str or not href or not d:
                continue

            tmdb_id = _tmdb(title)
            if tmdb_id is None:
                continue

            m = re.match(r"(\d{1,2}):(\d{2})", time_str)
            if not m:
                continue

            yield Screening(
                tmdb_id=tmdb_id,
                date=d,
                time=time(int(m.group(1)), int(m.group(2))),
                ticket_url=href,
                cinema_name=_CINEMA,
                city=_CITY,
                screen=raw.get("screen", ""),
            )
