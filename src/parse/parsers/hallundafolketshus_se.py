"""hallundafolketshus.se — CaféBio, film and opera events; tickets per showing on Tickster."""

import logging
import re
from collections.abc import Iterator
from datetime import date, time
from itertools import pairwise

import requests
from bs4 import BeautifulSoup

from parse import _http, _version
from parse._util import infer_year
from parse.parsers import _films, _tickster
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue, film_key

log = logging.getLogger(__name__)

_BASE = "https://www.hallundafolketshus.se"
# "Alla kommande evenemang": every upcoming event on one page; the front page stops after a fortnight.
_URL = _BASE + "/events-2"
_CINEMA = "Hallunda Folkets Hus"
_CITY = "Norsborg"
_ADDRESS = "Borgvägen 1"
_SOURCE = "hallundafolketshus_se"

_SESSION = _http.session("Mozilla/5.0")

# Site chrome that shares the uploads directory with film posters.
_NOT_A_POSTER = re.compile(r"logo|favicon|icon", re.IGNORECASE)

# Event categories that are screenings: "CaféBio", "Film", "Opera - Live på Bio".
_SCREENING = re.compile(r"bio|^film$", re.IGNORECASE)
_WHEN = re.compile(r"^(\d{2})/(\d{2})\s+(\d{2}):(\d{2})")
# Programme names set before the title: "Drive-in-Bio LUST FOR LIFE".
_PROGRAMME = re.compile(r"^(Drive-in-Bio)\s+", re.IGNORECASE)

_HOURS = re.compile(r"(\d+)\s*tim\w*(?:\s*(?:och\s*)?(\d+)\s*min\w*)?", re.IGNORECASE)
_MINUTES = re.compile(r"^(\d+)\s*min\w*$", re.IGNORECASE)
_AGE = re.compile(r"^(barntillåten|(?:från|fr\.?)\s*\d+\s*år|\d+\s*år)$", re.IGNORECASE)

# Labelled fact paragraphs: "Längd: 1 tim 22 min", "Speltid Cirka 3 timmar och 29 minuter", "Språk Italienska".
_LABELLED = re.compile(r"^(Speltid|Längd|Genre|Språk)\s*:?\s*(.+)$", re.IGNORECASE)
_LABEL = re.compile(r"^(Speltid|Längd|Genre|Språk)\s*:?$", re.IGNORECASE)
_SUBTITLED = re.compile(r"^(\w+)\s+undertext", re.IGNORECASE)
# Fact and credit lines: "Regi: …", "Medverkande:", "Pris: 120 kr", "Filmen börjar kl 19.00".
_FACT = re.compile(
    r"^(?:[^\W\d_]+(?:\s+[^\W\d_]+){0,2}\s*:(?:\s|$)"
    r"|(?:speltid|längd|genre|språk|pris|filmen börjar|dörrarna|kassan)\b)",
    re.IGNORECASE,
)
# Broadcast date sentences: "Live på bio 17 oktober 2026.", "Otello livesänds till biografer …, 24 april 2027."
_BROADCAST_DATE = re.compile(r"\s*[^.!?]*\b(?:live på bio|livesänds)\b[^.!?]*\b\d{4}\.", re.IGNORECASE)
# Shorter paragraphs are notes, not synopsis.
_SYNOPSIS_MIN = 90
# A lone question is a note to the audience: "Du har väl inte missat … buffé?"
_QUESTION = re.compile(r"^[^.!?]*\?$")
# Marks line breaks; source newlines are formatting whitespace.
_BREAK = "\u2029"


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _title(raw: str, ticket: str = "") -> str:
    """Film and opera titles are set in capitals: "MACBETH" becomes "Macbeth".

    The Tickster title, when it opens with the same words, gives the casing:
    "COSì FAN TUTTE" becomes "Così fan Tutte".
    """
    title = " ".join(raw.split())
    if sum(c.isupper() for c in title) <= sum(c.islower() for c in title):
        return title
    cased = " ".join(_tickster.version(ticket)[0].split())
    end = len(title)
    if cased.lower().startswith(title.lower()) and not cased[end : end + 1].isalnum():
        return cased[:end]
    return title.capitalize()


def _events(html: str) -> Iterator[tuple[str, date, time, str, tuple[str, ...]]]:
    """Yield (title, date, time, event_url, programme labels) for every screening event in *html*.

    Titles keep the site's casing; :func:`_title` recases them.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, date, time]] = set()

    for item in soup.select(".em-event.em-item"):
        if not _SCREENING.search(_text(item.select_one(".em-item-cat"))):
            continue
        link = item.select_one(".em-item-title a[href]")
        m = _WHEN.match(_text(item.select_one(".em-date-time")))
        if not link or not m:
            continue

        title = _text(link)
        labels: tuple[str, ...] = ()
        if prefix := _PROGRAMME.match(title):
            title, labels = title[prefix.end() :], (prefix.group(1),)
        day, month = int(m.group(1)), int(m.group(2))
        when = date(infer_year(month), month, day)
        start = time(int(m.group(3)), int(m.group(4)))
        href = link["href"]
        if not title or (title, when, start) in seen:
            continue
        seen.add((title, when, start))
        if not href.startswith("http"):
            href = _BASE + href

        yield title, when, start, href, labels


def _runtime(line: str) -> int | None:
    """Minutes from "1 timme 51 min" or "111 min"."""
    if m := _MINUTES.match(line):
        return int(m.group(1))
    if m := _HOURS.search(line):
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    return None


def _article(html: str):
    """The event article, line breaks marked with :data:`_BREAK`."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup
    for tag in article(["script", "style"]):
        tag.decompose()
    for br in article.find_all("br"):
        br.replace_with(_BREAK)
    return article


def _lines(p) -> list[str]:
    return [line for part in p.get_text("").split(_BREAK) if (line := " ".join(part.split()))]


def _synopsis(paragraphs) -> str:
    """Descriptive paragraphs, without fact lines, credits, notes or broadcast dates."""
    texts: list[str] = []
    for p in paragraphs:
        lines = _lines(p)
        if p.find("p") or not lines or any(_FACT.match(line) for line in lines):
            continue
        text = " ".join(lines)
        if len(text) < _SYNOPSIS_MIN or _QUESTION.match(text):
            continue
        if text := _BROADCAST_DATE.sub("", text).strip():
            texts.append(text)
    return "\n\n".join(texts)


def _details(html: str) -> dict:
    """Poster, genres, runtime, age rating and synopsis from one event page."""
    article = _article(html)

    poster_url = ""
    for img in article.find_all("img"):
        src = img.get("src", "")
        if "/uploads/" in src and not _NOT_A_POSTER.search(src):
            poster_url = src
            break

    # The CaféBio film block is three bold lines: genres, length or age, director.
    paragraphs = article.find_all("p")
    details: dict = {"poster_url": poster_url, "genres": [], "runtime": None, "age_rating": "", "overview": ""}
    for p in paragraphs:
        lines = _lines(p)
        if len(" ".join(lines)) > 300 or not any(line.startswith("Regi:") for line in lines):
            continue

        if not lines[0].startswith("Regi:"):
            details["genres"] = [g.strip() for g in re.split(r"[,/]", lines[0]) if g.strip()]
        for line in lines[1:]:
            if _AGE.match(line):
                details["age_rating"] = line
            elif runtime := _runtime(line):
                details["runtime"] = runtime
        break

    # Film and opera pages label each fact instead.
    for label, value in _labelled(article):
        if label in ("speltid", "längd") and not details["runtime"]:
            details["runtime"] = _runtime(value)
        elif label == "genre" and not details["genres"]:
            details["genres"] = [g.strip() for g in re.split(r"[,/]", value) if g.strip()]
    # Unclosed tags can leave a paragraph wrapping the rest of the page; only innermost ones count.
    details["overview"] = _synopsis(paragraphs)

    return details


def _labelled(article) -> Iterator[tuple[str, str]]:
    """(label, value) per fact line; a bare label takes the next line as its value."""
    for p in article.find_all("p"):
        if p.find("p"):
            continue
        lines = _lines(p)
        for line, following in pairwise([*lines, ""]):
            if m := _LABELLED.match(line):
                yield m.group(1).lower(), m.group(2)
            elif following and (m := _LABEL.match(line)):
                yield m.group(1).lower(), following


def _stated_version(html: str) -> tuple[str, str]:
    """(language, subtitles) from "Språk Italienska" and "Svenska undertexter!"."""
    article = _article(html)
    language = next((_version.language(v) for label, v in _labelled(article) if label == "språk"), "")
    subtitles = next(
        (_version.subtitles(m.group(1)) for p in article.find_all("p") if (m := _SUBTITLED.match(_text(p)))), ""
    )
    return language, subtitles


def _ticket(html: str) -> str:
    """The "Köp Biljett" Tickster link on an event page."""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("a[href*='tickster.com']")
    return link["href"] if link else ""


def _screen(venue: str) -> str:
    """ "Hallunda Folkets Hus - Brage" names the Brage salon."""
    return venue.removeprefix(_CINEMA).strip(" -")


def _fetch(url: str) -> str:
    resp = _SESSION.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    seen: set[str] = set()
    for raw, day, start, href, labels in _events(_fetch(_URL)):
        page = ""
        try:
            page = _fetch(href)
        except requests.RequestException as exc:
            log.warning("hallundafolketshus: %s failed: %s", href, exc)

        ticket = _ticket(page) if page else ""
        event = _tickster.fetch_event(ticket, _SESSION) if ticket else None
        title = _title(raw, event.title if event else "")
        if title not in seen:
            seen.add(title)
            details = _details(page) if page else {}
            yield _films.register(_films.make(_SOURCE, title, url=href, **details))

        language, subtitles = _stated_version(page) if page else ("", "")
        if event:
            _, spoken, subs = _tickster.version(event.title)
            language, subtitles = spoken or language, subs or subtitles

        yield Screening(
            tmdb_id=_tmdb(title),
            film_key=film_key(_SOURCE, title),
            title=title,
            date=day,
            time=start,
            ticket_url=event.url if event else ticket or href,
            cinema_name=_CINEMA,
            city=_CITY,
            screen=_screen(event.venue) if event else "",
            **_version.screening_facts(language=language, subtitles=subtitles, raw_attributes=labels),
        )
