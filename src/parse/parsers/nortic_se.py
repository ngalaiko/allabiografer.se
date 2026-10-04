"""nortic.se — public JSON API, Bio category events only."""

import dataclasses
import html
import logging
import re
from collections import Counter
from collections.abc import Iterator
from datetime import date, time

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue, film_key

log = logging.getLogger(__name__)

_SOURCE = "nortic_se"
_API = "https://www.nortic.se/api/json/shows"
# Venues file cinema screenings under either label.
_CATEGORIES = {"Bio", "Film"}
# Opera holds stage productions and cinema broadcasts alike; broadcasts say so.
_BROADCAST = re.compile(r"metropolitan|\bmet\b|på bio\b|\bbio\b|livesänd|direktsänd", re.IGNORECASE)

# Event wrappers around film titles: "Bio: Kevlarsjäl", "Bio Kontrast - Super Mario Galaxy", "Frukostbio Top Hat".
_PREFIX = re.compile(
    r"^(?:(?P<label>bio kontrast|doc lounge|opera på bio|live på bio|bio)\s*[:\-–]\s*|(?P<word>frukostbio)\s+)",
    re.IGNORECASE,
)
# "Rebuilding - Bio Kontrast", "(För Funkisfamiljer)", "Fjord with English subtitles", "Macbeth - Live från…".
_SUFFIXES = (
    re.compile(r"\s+[-–]\s+(?P<label>bio kontrast|bioversionen|live från .+|film\b.*)$", re.IGNORECASE),
    re.compile(r"\s*\((?P<label>för [^)]+)\)$", re.IGNORECASE),
    re.compile(r"\s+(?P<label>with english subtitles)$", re.IGNORECASE),
)

# Labels opening a fact in descriptions: "Speltid: 96 minuter Språk: Engelska Text: Svenska".
_LABELS = (
    r"speltid|längd|runtime|genre|åldersgräns|age rating|originaltitel|originalspråk|land|språk|language|"
    r"subtitles|tal|text|regi|manus|directors?|övrigt|biljetter|arrangör|bio"
)
_FIELD_END = rf"(?=\s+(?:{_LABELS})(?:\s*(?:&|och)\s*\w+)?\s*:|\.\s|\.?$)"
_DUBBED = re.compile(r"\b(?:tal|språk|originalspråk)\s*:[^.:]*dubb", re.IGNORECASE)
# Labels stating the screening's speech; "Originalspråk:" states the film's.
_SPEECH = re.compile(r"\b(?:tal|språk|language)\s*:", re.IGNORECASE)
# Values of a genre field that name no genre: "Bio: Ej angivet", "Bio: Live på bio".
_NOT_GENRES = {"ej angivet", "live på bio"}

# Season passes and multi-film packages: "Wernamo Filmstudio hösten 2026", "Minifilmfestival Höst 26".
_PACKAGE = re.compile(r"\b(?:höst|vår)(?:en)?\s+(?:20)?\d{2}\b", re.IGNORECASE)
# Composer after an opera title: "Manon/ Massenet", "Simson & Delila/ Camille Saint-Saenss".
_COMPOSER = re.compile(r"\s*/\s*[A-ZÀ-Þ][\w-]*(?:\s+[A-ZÀ-Þ][\w-]*)*$")

# Arena names that are a hall of a cinema named elsewhere.
_ARENAS = {"Götasalen": ("Bio Göta Lejon", "Götasalen")}
# "Sjöängen, Stora salongen": cinema, hall.
_HALL = re.compile(r"(?P<name>.+?),\s*(?P<hall>[^,]*(?:salong\w*|sal|salen))", re.IGNORECASE)


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()

    resp = session.get(_API, timeout=30)
    resp.raise_for_status()
    for item in _parse_payload(resp.json()):
        yield _films.register(item, session=session) if isinstance(item, Film) else item


def _text(raw: str | None) -> str:
    """Plain text from an HTML fragment."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw or "")).split())


def _field(text: str, labels: str) -> str:
    """Value after the first of *labels* in a description, up to the next label or sentence end."""
    m = re.search(rf"\b(?:{labels})\s*:\s*(.*?){_FIELD_END}", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _runtime(text: str) -> int | None:
    """Minutes stated as "Speltid: 96 minuter", "Längd: 122 min" or "Speltid: 2h 30m".

    The API's playTimeInMinutes is the booked slot, rounded and padded, so it is not used.
    """
    value = _field(text, "speltid|längd|runtime")
    hours = re.search(r"(\d+)\s*(?:h\b|tim)", value)
    minutes = re.search(r"(\d+)\s*m(?:in|\b)", value)
    if not hours and not minutes:
        minutes = re.match(r"(\d+)", value)
    total = (int(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)
    return total or None


def _genres(text: str) -> list[str]:
    """Genres under "Genre:", else under "Bio:" as some organizers label them."""
    value = _field(text, "genre") or _field(text, "bio")
    return [
        g[:1].upper() + g[1:]
        for g in (p.strip() for p in re.split(r"[/,]|\s+och\s+", value))
        if g and g.casefold() not in _NOT_GENRES
    ]


def _title(raw: str) -> tuple[str, tuple[str, ...]]:
    """(film title, removed event labels) from an event title."""
    title = raw.strip()
    labels: list[str] = []
    if m := _PREFIX.match(title):
        labels.append(m.group("label") or m.group("word"))
        title = title[m.end() :]
    stripped = True
    while stripped:
        stripped = False
        for pattern in _SUFFIXES:
            if m := pattern.search(title):
                labels.append(m.group("label"))
                title = title[: m.start()]
                stripped = True
    return title.strip(), tuple(labels)


def _film(event: dict, title: str) -> Film:
    """Film metadata carried by one event, under its title without version tags.

    The API exposes no poster: its images are 16:9 event banners.
    """
    text = _text(event.get("description"))
    spoken, _ = _version.from_text(text)
    original = _field(text, "originaltitel")
    return _films.make(
        _SOURCE,
        title,
        title_original="" if original == title else original,
        overview=text or _text(event.get("shortDescription")),
        runtime=_runtime(text),
        genres=_genres(text),
        age_rating=_field(text, "åldersgräns|age rating"),
        url=event.get("link") or "",
        # Dubbed speech names the screening's audio, not the film's.
        original_languages=frozenset() if _DUBBED.search(text) else _version.languages(spoken),
    )


def _merge(old: Film, new: Film) -> Film:
    """Fill the fields *old* lacks from *new* — the same film under two organizers."""
    filled = {
        f.name: getattr(new, f.name)
        for f in dataclasses.fields(old)
        if not getattr(old, f.name) and getattr(new, f.name)
    }
    return dataclasses.replace(old, **filled) if filled else old


def _city(show: dict) -> str:
    raw = show.get("arenaCity") or ""
    # API sometimes returns city in ALL-CAPS (e.g. "ELLÖS")
    return raw.title() if raw == raw.upper() else raw


def _arena(show: dict) -> tuple[str, str]:
    """(cinema, hall) for a show's arena name."""
    name = (show.get("arenaName") or "").strip()
    if name in _ARENAS:
        return _ARENAS[name]
    if m := _HALL.fullmatch(name):
        return m.group("name").strip(), m.group("hall").strip()
    return name, ""


def _cinema_names(events: list[dict]) -> dict[tuple[object, str, str], str]:
    """Canonical cinema per (organizer, city, arena name).

    Organizers spell one cinema several ways ("Folkets Hus Ulricehamn", "Folketshus");
    the name on most shows wins, the longest on a tie.
    """
    counts: dict[tuple[object, str], Counter[str]] = {}
    for event in events:
        for show in event.get("shows") or []:
            name, _ = _arena(show)
            if name:
                counts.setdefault((event.get("organizerId"), _city(show)), Counter())[name] += 1
    names: dict[tuple[object, str, str], str] = {}
    for (organizer, city), counter in counts.items():
        best = max(counter, key=lambda n: (counter[n], len(n)))
        for name in counter:
            names[(organizer, city, name)] = best if organizer is not None else name
    return names


def _is_screening(event: dict, broadcasters: set[object]) -> bool:
    if not event.get("title") or _PACKAGE.search(event["title"]):
        return False
    if event.get("category") in _CATEGORIES:
        return True
    return event.get("category") == "Opera" and event.get("organizerId") in broadcasters


def _broadcasts(event: dict) -> bool:
    arenas = " ".join(s.get("arenaName") or "" for s in event.get("shows") or [])
    return bool(_BROADCAST.search(f"{event.get('title', '')} {_text(event.get('description'))} {arenas}"))


def _parse_payload(data: dict) -> Iterator[Screening | Venue | Film]:
    # An organizer showing one broadcast opera shows its other operas the same way.
    broadcasters = {e.get("organizerId") for e in data["events"] if e.get("category") == "Opera" and _broadcasts(e)}
    broadcasters.discard(None)
    bio_events = [e for e in data["events"] if _is_screening(e, broadcasters)]
    log.info("nortic.se: %d bio events", len(bio_events))

    versioned = []
    for event in bio_events:
        title, labels = _title(event["title"])
        if event.get("category") == "Opera":
            title = _COMPOSER.sub("", title)
        versioned.append((event, labels, _version.split_title(title)))
    # "Simson & Delila" joins "Simson och Delila" when another event spells it so.
    keys = {film_key(_SOURCE, title) for _, _, (title, *_) in versioned}
    for i, (event, labels, (title, *rest)) in enumerate(versioned):
        spelled = re.sub(r"\s+&\s+", " och ", title)
        if spelled != title and film_key(_SOURCE, spelled) in keys:
            versioned[i] = (event, labels, (spelled, *rest))
    films: dict[str, Film] = {}
    for event, _, (title, *_) in versioned:
        film = _film(event, title)
        films[film.key] = _merge(films[film.key], film) if film.key in films else film
    yield from films.values()

    names = _cinema_names(bio_events)
    seen_venues: set[tuple[str, str]] = set()

    for event, labels, (film_title, fmt, _language, subtitles) in versioned:
        text = _text(event.get("description"))
        # Description language describes the film; title suffixes describe this screening.
        spoken, stated_subtitles = _version.from_text(text)
        dubbed = bool(_DUBBED.search(text))
        stated = dubbed or bool(_SPEECH.search(text))
        tmdb_id = _tmdb(film_title)
        key = film_key(_SOURCE, film_title)

        count = 0
        for show in event.get("shows") or []:
            arena, screen = _arena(show)
            city = _city(show)
            cinema_name = names.get((event.get("organizerId"), city, arena), arena)
            address = show.get("arenaAddress") or ""
            ticket_url = show.get("link") or ""
            raw_dt = show.get("startDate") or ""

            if not cinema_name or not raw_dt or not ticket_url:
                continue

            venue_key = (cinema_name, city)
            if venue_key not in seen_venues:
                seen_venues.add(venue_key)
                yield Venue(name=cinema_name, city=city, address=address)

            try:
                date_str, time_str = raw_dt.split(" ", 1)
                h, m = time_str.split(":")
                dt_date = date.fromisoformat(date_str)
                dt_time = time(int(h), int(m))
            except (ValueError, AttributeError):
                log.warning("bad startDate %r for %r", raw_dt, film_title)
                continue

            yield Screening(
                tmdb_id=tmdb_id,
                title=film_title,
                date=dt_date,
                time=dt_time,
                cinema_name=cinema_name,
                city=city,
                screen=screen,
                ticket_url=ticket_url,
                **_version.screening_facts(
                    format=fmt,
                    language=spoken if stated else "",
                    subtitles=subtitles or stated_subtitles,
                    audio_role_text="dubbat" if dubbed else "",
                    source_texts=(*_version.title_suffixes(event.get("title", "")), *labels),
                    raw_attributes=labels,
                ),
                film_key=key,
            )
            count += 1

        if count:
            log.info("  %s: %d screenings", film_title, count)
