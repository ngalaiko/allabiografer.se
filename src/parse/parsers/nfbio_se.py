"""nfbio.se — Nordisk Film Bio (Uppsala + Malmö), Drupal cinema listing pages."""

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time, timedelta

import requests
from bs4 import BeautifulSoup

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue
from store.version import Language

log = logging.getLogger(__name__)

_SOURCE = "nfbio_se"
_BASE = "https://www.nfbio.se"
_CINEMAS = [
    {
        "city": "Uppsala",
        "name": "Nordisk Film Bio Uppsala",
        "url": "/biograf/uppsala?city=uppsala",
        "address": "Marknadsgatan 1",
    },
    {
        "city": "Malmö",
        "name": "Nordisk Film Bio Mobilia",
        "url": "/biograf/malmo?city=malmo",
        "address": "Per Albin Hanssons väg 38C",
    },
]

# "(Eng. tal)", "(ES)" — spoken language.
_LANGUAGE = re.compile(r"^\((.+?)(?:\s+tal)?\)$")
# "(Sv.text)" — subtitles.
_SUBTITLES = re.compile(r"^\((.+?)\.?text\)$")
# "ES", "IT" — spoken language as a bare code.
_LANGUAGE_CODE = re.compile(r"^[A-Z]{2}$")
# "Speltid: 1 timme 46 min"
_HOURS = re.compile(r"(\d+)\s*timm")
_MINUTES = re.compile(r"(\d+)\s*min")
# Genre placeholder for films without one.
_NO_GENRE = "Ej angivet"
# "Dune: Part Three (Wb/Legendary)" — trailing distributor tag.
_TRAILING_TAG = re.compile(r"\s*\(([^()]+)\)$")
# Unreleased films carry a one-minute placeholder runtime; nothing sold as a screening is this short.
_MIN_RUNTIME = 5


def _parse_version(text: str) -> tuple[str, str, str]:
    """Split "2D, (Eng. tal), (Sv.text), Biodagen" into format, language, subtitles."""
    language = subtitles = ""
    labels: list[str] = []
    for raw in (p.strip() for p in text.split(",")):
        part = raw
        if not part:
            continue
        # A parenthesised value may itself contain the comma that split it.
        if part.startswith("(") and not part.endswith(")"):
            part += ")"
        elif part.endswith(")") and not part.startswith("("):
            part = "(" + part
        if m := _SUBTITLES.match(part):
            subtitles = m.group(1).rstrip(".") + "."
        elif m := _LANGUAGE.match(part):
            language = m.group(1)
        elif _LANGUAGE_CODE.match(part):
            language = part
        elif part == "Otextad":
            subtitles = part
        else:
            labels.append(part)
    return _version.formats(*labels), _version.language(language), _version.subtitles(subtitles)


def _parse_duration(text: str) -> int | None:
    """Runtime in minutes from "Speltid: 1 timme 46 min"; None for placeholders."""
    hours = _HOURS.search(text)
    minutes = _MINUTES.search(text)
    if not hours and not minutes:
        return None
    runtime = int(hours.group(1) if hours else 0) * 60 + int(minutes.group(1) if minutes else 0)
    return runtime if runtime >= _MIN_RUNTIME else None


def _parse_time(text: str) -> tuple[int, time] | None:
    """(days after the listed date, time) from "13.00"; "24.00" is midnight after it."""
    m = re.match(r"(\d{1,2})[.:](\d{2})", text.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if minute > 59:
        return None
    return divmod(hour, 24)[0], time(hour % 24, minute)


def _absolute(href: str) -> str:
    """Absolute nfbio.se URL from a possibly relative href.

    Image style derivatives need their ``itok`` query to be generated on demand.
    """
    if not href:
        return ""
    return href if href.startswith("http") else _BASE + href


def _versions(article) -> list[str]:
    return [" ".join(el.get_text(" ", strip=True).split()) for el in article.select(".version")]


def _screened_originals(versions: list[str]) -> frozenset[Language]:
    """Non-Swedish audio languages screened: Swedish cinemas dub only into Swedish."""
    found: set[Language] = set()
    for version in versions:
        found |= _version.languages(_parse_version(version)[1])
    return frozenset(found - {Language.SWEDISH})


def _listing_film(article, title: str) -> Film:
    """Film metadata an article on a cinema listing page carries."""
    duration_el = article.select_one(".duration")
    censorship_el = article.select_one(".censorship")
    age_rating = censorship_el.get_text(" ", strip=True).removeprefix("Åldersgräns:").strip() if censorship_el else ""
    link_el = article.select_one(".movie-poster a[href]") or article.select_one(".node-title a[href]")
    poster_el = article.select_one(".movie-poster img[src]")
    return _films.make(
        _SOURCE,
        title,
        runtime=_parse_duration(duration_el.get_text(" ", strip=True)) if duration_el else None,
        age_rating=age_rating,
        poster_url=_absolute(poster_el.get("src", "")) if poster_el else "",
        original_languages=_screened_originals(_versions(article)),
        # Film pages render their content only for the ?city= the listing links carry.
        url=_absolute(link_el.get("href", "")) if link_el else "",
    )


def _poster(soup: BeautifulSoup) -> str:
    """Full-size poster from the page's JSON-LD Movie."""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        for item in data.get("@graph", [data]) if isinstance(data, dict) else []:
            image = item.get("image") if isinstance(item, dict) else None
            url = image.get("url") if isinstance(image, dict) else image
            if isinstance(url, str) and url:
                return _absolute(url)
    return ""


def _items(node, field: str) -> list[str]:
    return [i.get_text(strip=True) for i in node.select(f".field--name-field-{field} .field__item")]


def _title_original(node) -> str:
    """Original title without a trailing distributor tag: "(Wb/Legendary)", "(Warner Bros.)"."""
    title = next(iter(_items(node, "original-title")), "")
    distributors = " ".join(_items(node, "copyright")).casefold()
    m = _TRAILING_TAG.search(title)
    if m and ("/" in m.group(1) or m.group(1).casefold().rstrip(".") in distributors):
        return title[: m.start()]
    return title


def _original_languages(film: Film, node, title_original: str) -> frozenset[Language]:
    """The page's language, which names the Swedish dub of imported family films.

    Swedish counts only for a film shown in no other language under its original title
    and credited with no Swedish voice cast.
    """
    stated = frozenset().union(*(_version.languages(i) for i in _items(node, "language")))
    retitled = bool(title_original) and title_original.casefold() != film.title.casefold()
    dubbed = "svenska röster" in (a.casefold() for a in _items(node, "actors"))
    if Language.SWEDISH in stated and (film.original_languages or retitled or dubbed):
        stated -= {Language.SWEDISH}
    return film.original_languages | stated


def _enrich(film: Film, html: str) -> Film:
    """Fill in what only the film's own page carries: synopsis, genres, dates, language."""
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("article.node--type-movie")
    if node is None:
        return film

    body = node.select_one(".field--name-body")
    premiere = node.select_one(".field--name-field-premiere-date time[datetime]")
    poster = node.select_one(".field--name-field-image img[src]")
    title_original = _title_original(node)
    return replace(
        film,
        overview=body.get_text(" ", strip=True) if body else "",
        genres=[g for g in _items(node, "genre") if g != _NO_GENRE],
        release_date=(premiere.get("datetime", "") or "")[:10],
        title_original=title_original,
        original_languages=_original_languages(film, node, title_original),
        # JSON-LD links the original; the page renders it at 336px, the listing at 230px.
        poster_url=_poster(soup) or (_absolute(poster.get("src", "")) if poster else film.poster_url),
    )


def _parse_listing(html: str, cinema_name: str, city: str) -> Iterator[Screening | Film]:
    """Yield every showtime rendered on a cinema listing page, and its film."""
    soup = BeautifulSoup(html, "html.parser")

    articles = soup.select("article.node--type-movie")
    if not articles:
        log.warning("%s: no films on listing page", cinema_name)
    for article in articles:
        title_el = article.select_one(".node-title .field--name-title") or article.select_one(".node-title")
        film_title = title_el.get_text(strip=True) if title_el else ""
        if not film_title:
            continue
        film = _listing_film(article, film_title)
        yield film
        tmdb_id = _tmdb(film_title, runtime=film.runtime)

        seen: set[str] = set()
        for slide in article.select(".slick__slide"):
            day_el = slide.select_one("time[datetime]")
            if not day_el:
                continue
            try:
                d = date.fromisoformat(day_el.get("datetime", ""))
            except ValueError:
                log.warning("bad slide date %r for %r", day_el.get("datetime"), film_title)
                continue

            for btn in slide.select(".movies-screenings-button-link"):
                href = btn.get("href", "")
                if not href or href in seen:
                    continue

                time_el = btn.select_one(".time")
                raw_time = time_el.get_text(strip=True) if time_el else ""
                parsed = _parse_time(raw_time)
                if not parsed:
                    log.warning("bad time %r for %r", raw_time, film_title)
                    continue
                days, t = parsed
                seen.add(href)

                room_el = btn.select_one(".room")
                version_el = btn.select_one(".version")
                version = " ".join(version_el.get_text(" ", strip=True).split()) if version_el else ""
                # Programme labels (Biopasset, Knattebio, Förhandsvisning…) stay as raw parts.
                parts = tuple(p for p in (p.strip() for p in version.split(",")) if p)
                _fmt, language, subtitles = _parse_version(version)

                yield Screening(
                    tmdb_id=tmdb_id,
                    title=film_title,
                    date=d + timedelta(days=days),
                    time=t,
                    ticket_url=href if href.startswith("http") else _BASE + href,
                    cinema_name=cinema_name,
                    city=city,
                    screen=room_el.get_text(strip=True) if room_el else "",
                    **_version.screening_facts(
                        format=version,
                        language=language,
                        subtitles=subtitles,
                        source_texts=(version,),
                        raw_attributes=parts,
                    ),
                    film_key=film.key,
                )


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()

    listings: list[tuple[str, list[Screening]]] = []
    films: dict[str, Film] = {}
    for cinema in _CINEMAS:
        city = cinema["city"]
        name = cinema["name"]

        yield Venue(name=name, city=city, address=cinema.get("address", ""))

        resp = session.get(_BASE + cinema["url"], timeout=30)
        resp.raise_for_status()

        screenings: list[Screening] = []
        for item in _parse_listing(resp.text, name, city):
            if not isinstance(item, Film):
                screenings.append(item)
            elif first := films.get(item.key):
                # Each cinema screens its own versions; the first listing keeps its URL.
                films[item.key] = replace(first, original_languages=first.original_languages | item.original_languages)
            else:
                films[item.key] = item
        listings.append((name, screenings))

    # Both cinemas list most of the same films; fetch each page once.
    for film in films.values():
        yield _films.register(_fetch_film(session, film), session=session)
    for name, screenings in listings:
        yield from screenings
        log.info("  %s: %d screenings", name, len(screenings))


def _fetch_film(session: requests.Session, film: Film) -> Film:
    if not film.url:
        return film
    try:
        resp = session.get(film.url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("failed to fetch film page %s: %s", film.url, exc)
        return film
    return _enrich(film, resp.text)
