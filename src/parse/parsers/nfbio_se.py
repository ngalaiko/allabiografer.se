"""nfbio.se — Nordisk Film Bio (Uppsala + Malmö), Drupal cinema listing pages."""

import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time

import requests
from bs4 import BeautifulSoup

from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "nfbio_se"
_BASE = "https://www.nfbio.se"
_CINEMAS = [
    {
        "city": "Uppsala",
        "name": "Nordisk Film Bio Uppsala",
        "url": "/biograf/uppsala?city=uppsala",
        "address": "Vaksalagatan 3",
    },
    {
        "city": "Malmö",
        "name": "Nordisk Film Bio Mobilia",
        "url": "/biograf/malmo?city=malmo",
        "address": "Per Albin Hanssons väg 40",
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
# Censorship labels that carry no rating.
_UNRATED = {"Åldergräns ej granskad", "Åldersgräns ej granskad"}


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
    return ", ".join(labels), language, subtitles


def _parse_duration(text: str) -> int | None:
    """Runtime in minutes from "Speltid: 1 timme 46 min"."""
    hours = _HOURS.search(text)
    minutes = _MINUTES.search(text)
    if not hours and not minutes:
        return None
    return int(hours.group(1) if hours else 0) * 60 + int(minutes.group(1) if minutes else 0)


def _parse_time(text: str) -> time | None:
    m = re.match(r"(\d{1,2})[.:](\d{2})", text.strip())
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _absolute(href: str) -> str:
    """Absolute nfbio.se URL from a possibly relative href.

    Image style derivatives need their ``itok`` query to be generated on demand.
    """
    if not href:
        return ""
    return href if href.startswith("http") else _BASE + href


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
        age_rating="" if age_rating in _UNRATED else age_rating,
        poster_url=_absolute(poster_el.get("src", "")) if poster_el else "",
        # Film pages render their content only for the ?city= the listing links carry.
        url=_absolute(link_el.get("href", "")) if link_el else "",
    )


def _enrich(film: Film, html: str) -> Film:
    """Fill in what only the film's own page carries: synopsis, genres, dates."""
    node = BeautifulSoup(html, "html.parser").select_one("article.node--type-movie")
    if node is None:
        return film

    body = node.select_one(".field--name-body")
    premiere = node.select_one(".field--name-field-premiere-date time[datetime]")
    original = node.select_one(".field--name-field-original-title .field__item")
    poster = node.select_one(".field--name-field-image img[src]")
    return replace(
        film,
        overview=body.get_text(" ", strip=True) if body else "",
        genres=[i.get_text(strip=True) for i in node.select(".field--name-field-genre .field__item")],
        release_date=(premiere.get("datetime", "") or "")[:10],
        title_original=original.get_text(strip=True) if original else "",
        # The film page renders the poster at 336px; the listing only at 230px.
        poster_url=_absolute(poster.get("src", "")) if poster else film.poster_url,
    )


def _parse_listing(html: str, cinema_name: str, city: str) -> Iterator[Screening | Film]:
    """Yield every showtime rendered on a cinema listing page, and its film."""
    soup = BeautifulSoup(html, "html.parser")

    for article in soup.select("article.node--type-movie"):
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
                t = _parse_time(time_el.get_text(strip=True)) if time_el else None
                if not t:
                    continue
                seen.add(href)

                room_el = btn.select_one(".room")
                version_el = btn.select_one(".version")
                version = " ".join(version_el.get_text(" ", strip=True).split()) if version_el else ""
                fmt, language, subtitles = _parse_version(version)

                yield Screening(
                    tmdb_id=tmdb_id,
                    title=film_title,
                    date=d,
                    time=t,
                    ticket_url=href if href.startswith("http") else _BASE + href,
                    cinema_name=cinema_name,
                    city=city,
                    screen=room_el.get_text(strip=True) if room_el else "",
                    format=fmt,
                    language=language,
                    subtitles=subtitles,
                    film_key=film.key,
                )


def parse() -> Iterator[Screening | Venue | Film]:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    seen_films: set[str] = set()
    for cinema in _CINEMAS:
        city = cinema["city"]
        name = cinema["name"]

        yield Venue(name=name, city=city, address=cinema.get("address", ""))

        resp = session.get(_BASE + cinema["url"], timeout=30)
        resp.raise_for_status()

        count = 0
        for item in _parse_listing(resp.text, name, city):
            if isinstance(item, Film):
                # Both cinemas list most of the same films; fetch each page once.
                if item.key in seen_films:
                    continue
                seen_films.add(item.key)
                yield _films.register(_fetch_film(session, item), session=session)
                continue
            yield item
            count += 1

        log.info("  %s: %d screenings", name, count)


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
