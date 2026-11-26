"""Build Aspen's JSON-LD catalogue from a saved fetch."""

import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from parse.parsers.bioaspen_se import _RUNTIME

from .._shared import STOCKHOLM, film_id, read_page, single_venue_rows

BASE = "https://www.bioaspen.se"
SOURCE = "bioaspen_se"
SHOW = re.compile(r"/shows/(?P<id>bio-aspen-.+-\d+-(?P<utc>\d{4}-\d{2}-\d{2}t\d{6})-0000000)/")
EVENT_INTRO = re.compile(
    r"^(?:Visningen den |\w+dagen den .+? får vi besök av |Före huvudfilmen visas )", re.IGNORECASE
)
CAST = re.compile(
    r"(?:\bI filmen medverkar |\bI rollerna(?: i [^.!?]+?)? ser vi |\(spelade? av )([^.!?()]+)(?=[.!?\)])"
)
CAST_SEPARATOR = re.compile(r",\s*(?:med\s+)?|\s+(?:och|samt)\s+")


def credits(movie, paragraphs):
    director = movie.find("h3", string=re.compile(r"^\s*Regissör\s*$"))
    label = director.find_next_sibling("span") if director else None
    names = label.get_text(" ", strip=True) if label else ""
    result = {"director": [name.strip() for name in names.split(",") if name.strip()]}
    for paragraph in paragraphs:
        # Only read explicit cast lists, not names mentioned in the synopsis.
        if cast := CAST.search(paragraph):
            result["actor"] = [
                re.sub(r"^Oscars(?:nominerade|vinnaren)\s+|\s+m fl$", "", name)
                for part in CAST_SEPARATOR.split(cast[1])
                if (name := part.strip())
            ]
            break
    return result


def screenings(inputs, today):
    seen = set()
    pages = sorted(inputs.glob("programme-*.html"))
    if not pages or read_page(pages[-1]).select_one("a.next.page-numbers[href]"):
        raise ValueError("Incomplete Aspen programme capture")
    movies = dict.fromkeys(
        urljoin(BASE, card["href"]) for page in pages for card in read_page(page).select('.movie > a[href*="/movies/"]')
    )
    for url in movies:
        path = inputs / f"movie-{film_id(url)}.html"
        movie = read_page(path)
        heading = movie.select_one("h1.entry-title")
        if not heading:
            raise ValueError(f"Missing Aspen movie title in {path.name}")
        title = heading.get_text(" ", strip=True)
        if title == "Nightborn (Yön lapsi)":
            title = "Nightborn"
        paragraphs = [text for p in movie.select(".entry-content p") if (text := p.get_text(" ", strip=True))]
        synopsis = [text for text in paragraphs if not EVENT_INTRO.match(text)]
        description = ""
        if synopsis:
            description = synopsis[0]
            # A one-line date can be the first sentence of the synopsis.
            if len(synopsis) > 1 and re.fullmatch(r"\w+ \d{4}\.", description):
                description += " " + synopsis[1]
        rows = []
        runtimes = set()
        for card in movie.select('a[href*="/shows/"]:has(h2)'):
            ticket = urljoin(url, card["href"])
            target = urlsplit(ticket)
            match = SHOW.fullmatch(target.path) if target.netloc == urlsplit(BASE).netloc else None
            if not match:
                raise ValueError(f"Unexpected Aspen booking URL: {ticket}")
            start = datetime.strptime(match["utc"] + "+0000", "%Y-%m-%dt%H%M%S%z").astimezone(STOCKHOLM)
            if start.strftime("%H:%M") != card.h2.get_text(strip=True):
                raise ValueError(f"Aspen time does not match booking URL: {ticket}")
            if start.date() < today or match["id"] in seen:
                continue
            seen.add(match["id"])
            labels = [tag.get_text(" ", strip=True) for tag in card.select("span.font-menu")]
            audio = next((text[4:] for text in labels if text.startswith("TAL ")), "")
            subtitles = next((text[5:] for text in labels if text.startswith("TEXT ")), "")
            if duration := next((m for text in labels if (m := _RUNTIME.fullmatch(text))), None):
                hours, minutes, only_minutes = duration.groups()
                runtimes.add(int(hours or 0) * 60 + int(minutes or only_minutes or 0))
            rows.append((match["id"], start, ticket, audio, subtitles))
        runtime = next(iter(runtimes)) if len(runtimes) == 1 else None
        people = credits(movie, synopsis)
        for row in rows:
            yield *row, url, title, description, runtime, people


def rows(inputs, today):
    return single_venue_rows("aspen", screenings(inputs, today))
