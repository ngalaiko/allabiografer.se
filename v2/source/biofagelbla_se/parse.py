"""Build Fågel Blå's JSON-LD catalogue from a saved fetch."""

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from parse.parsers.biofagelbla_se import _RUNTIME

from .._shared import STOCKHOLM, film_id, read_page, single_venue_rows

BASE = "https://biofagelbla.se"
SOURCE = "biofagelbla_se"


def credits(detail):
    for tag in detail.select('script[type="application/ld+json"]'):
        try:
            movie = json.loads(tag.get_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(movie, dict) or movie.get("@type") != "Movie":
            continue
        result = {}
        for role in ("director", "actor"):
            people = movie.get(role)
            result[role] = [
                name.strip()
                for person in (people if isinstance(people, list) else [people])
                if isinstance(person, dict) and isinstance(person.get("name"), str)
                for name in (person["name"].split(",") if role == "director" else [person["name"]])
                if name.strip()
            ]
        return result
    return {}


def screenings(inputs, today):
    programme = read_page(inputs / "programme.html")
    cards = programme.select(".js-movie-listing-by-date article")
    if not cards:
        raise ValueError("No Fågel Blå programme cards")
    seen = set()
    details = {}
    for card in cards:
        clock = card.select_one("h3 time[datetime]")
        if clock is None:
            raise ValueError("Missing Fågel Blå programme time")
        start = datetime.fromisoformat(clock["datetime"])
        if start.tzinfo is None or start.astimezone(STOCKHOLM).strftime("%H:%M") != clock.get_text(strip=True):
            raise ValueError(f"Inconsistent Fågel Blå time: {start}")
        start = start.astimezone(STOCKHOLM)
        heading = clock.parent
        clock.extract()
        title = heading.get_text(" ", strip=True)
        if title.startswith("De Gaulle:"):
            title = re.sub(r"\s+–\s+del [IVX]+$", "", title, flags=re.IGNORECASE)
        if start.date() < today or "slutet sällskap" in title.casefold():
            continue
        link = card.select_one('a[href*="showtime="]')
        if link is None:
            raise ValueError(f"Missing Fågel Blå ticket link for {title} at {start}")
        ticket = link["href"]
        booking = urlsplit(ticket)
        ids = parse_qs(booking.query).get("showtime", [])
        if booking.netloc != urlsplit(BASE).netloc or len(ids) != 1 or not ids[0].isdigit():
            raise ValueError(f"Unexpected Fågel Blå ticket link: {ticket}")
        show_id = ids[0]
        if show_id in seen:
            continue
        seen.add(show_id)
        movie = f"{BASE}{booking.path}"
        labels = [tag.get_text(" ", strip=True) for tag in card.select("span.leading-none")]
        if movie not in details:
            detail = read_page(inputs / f"movie-{film_id(movie)}.html")
            meta = detail.select_one('meta[name="description"]')
            runtime = None
            if duration := next((m for text in labels if (m := _RUNTIME.fullmatch(text))), None):
                hours, minutes, only_minutes = duration.groups()
                runtime = int(hours or 0) * 60 + int(minutes or only_minutes or 0)
            details[movie] = (meta.get("content", "") if meta else "", runtime, credits(detail))
        audio = next((text[7:] for text in labels if text.startswith("Språk: ")), "")
        subtitles = next((text[6:] for text in labels if text.startswith("Text: ")), "")
        yield show_id, start, ticket, audio, subtitles, movie, title, *details[movie]


def rows(inputs, today):
    return single_venue_rows(None, screenings(inputs, today))
