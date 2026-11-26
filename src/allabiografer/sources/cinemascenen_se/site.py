"""cinemascenen.se — five cinemas with dated programme rows."""

import logging
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time
from itertools import pairwise
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from allabiografer import normalize as _version
from allabiografer.model import Film, Screening
from allabiografer.sources import _films

log = logging.getLogger(__name__)

_SOURCE = "cinemascenen_se"
_URL = "https://www.cinemascenen.se/"
_SITES = (
    ("ystad", "Ystad", "Björnstjernegatan 3"),
    ("katrineholm", "Katrineholm", "Drottninggatan 19"),
    ("strangnas", "Strängnäs", "Regementsgatan 3"),
    ("soderhamn", "Söderhamn", "Köpmangatan 2"),
    ("hudiksvall", "Hudiksvall", "Drottninggatan 1"),
)
_RUNTIME = re.compile(r"(?:(\d+)\s*tim\s*)?(\d+)\s*min\b", re.IGNORECASE)
_RATING = re.compile(r"\b(?:\d+\s*år|barntillåten|btl)\b", re.IGNORECASE)


def _text(node, selector: str) -> str:
    el = node.select_one(selector)
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _upper(node, selector: str) -> str:
    """Programme text, which the site uppercases for ASCII letters only."""
    return _text(node, selector).upper()


def _href(node, selector: str) -> str:
    el = node.select_one(selector)
    return urljoin(_URL, el["href"]) if el and el.get("href") else ""


def _showtimes(html: str, city: str) -> Iterator[tuple[Film, Screening]]:
    soup = BeautifulSoup(html, "html.parser")
    for day in soup.select(".event-day[data-date]"):
        try:
            d = date.fromisoformat(day["data-date"])
        except ValueError:
            log.warning("invalid programme date %r", day["data-date"])
            continue
        for row in day.select(".movie-row"):
            raw_title = _upper(row, ".movie-row__title")
            title, fmt, language, subtitles = _version.split_title(raw_title)
            if not title:
                continue
            try:
                t = time.fromisoformat(_text(row, ".movie-row__time"))
            except ValueError:
                continue
            url = _href(row, ".movie-row__button--more")
            ticket = _href(row, ".movie-row__button--ticket") or url
            if not ticket:
                continue
            meta = _text(row, ".movie-row__meta")
            runtime = _RUNTIME.search(meta)
            rating = _RATING.search(meta)
            film = _films.make(
                _SOURCE,
                title,
                url=url,
                runtime=int(runtime[1] or 0) * 60 + int(runtime[2]) if runtime else None,
                age_rating=rating[0] if rating else "",
            )
            attributes = (*_version.title_suffixes(raw_title), *((meta,) if meta else ()))
            yield (
                film,
                Screening(
                    tmdb_id=None,
                    title=title,
                    film_key=film.key,
                    date=d,
                    time=t,
                    ticket_url=ticket,
                    cinema_name="Cinemascenen",
                    city=city,
                    screen=_upper(row, ".movie-row__venue").split(",")[0].strip(),
                    **_version.screening_facts(
                        format=fmt,
                        language=language or ("Svenskt tal" if re.search(r"\bsv\s+tal\b", meta, re.IGNORECASE) else ""),
                        subtitles=subtitles,
                        source_texts=attributes,
                        raw_attributes=attributes,
                    ),
                ),
            )


def _details(html: str, film: Film) -> Film:
    """Title and metadata within the film's Elementor section, excluding recommendation cards."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h2.elementor-heading-title")
    section = heading.find_parent(class_="e-parent") if heading else None
    if section is None:
        return film
    # Standard pages put the synopsis before "Premiär"; event pages put it
    # after the runtime/price line, immediately before the credits accordion.
    overview = ""
    for prev, widget in pairwise(section.select(".elementor-widget")):
        if (
            widget.get_text(strip=True) == "Premiär" or "elementor-widget-n-accordion" in widget.get("class", [])
        ) and "elementor-widget-text-editor" in prev.get("class", []):
            overview = " ".join(prev.get_text(" ", strip=True).split())
            break
    directors = next(
        (
            widget.get_text(" ", strip=True)
            for label, widget in pairwise(section.select(".elementor-widget"))
            if label.get_text(strip=True) == "Regi" and "elementor-widget-text-editor" in widget.get("class", [])
        ),
        "",
    )
    poster = section.select_one(".elementor-widget-image img[src]")
    return replace(
        film,
        title=" ".join(heading.get_text(" ", strip=True).split()) or film.title,
        overview=overview,
        poster_url=urljoin(_URL, poster["src"]) if poster else "",
        directors=[name.strip() for name in directors.split(",") if name.strip()],
    )
