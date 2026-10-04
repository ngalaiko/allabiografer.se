"""bio.se — JSON API, all cinemas in one pass."""

import dataclasses
import html
import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time

from parse import _http, _version
from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue
from store.version import Language

log = logging.getLogger(__name__)

_SOURCE = "bio_se"
_SITE = "https://bio.se"
_API = f"{_SITE}/api"

# Site taxonomy placeholders, not genres.
_NOISE_GENRES = {"Unknown", "Film", "Event", "Alternative Content"}
# Session labels that override the session's subtitle field.
_SUBTITLE_ATTRIBUTES = {"English subtitles": "Engelska"}
# Session format of concerts, theatre and other non-screenings.
_NOT_A_FILM = "Inte en film"
# Session info texts up to this length are labels; longer ones are notices.
_LABEL_MAX = 40


def _ticket_url(payment_link: str) -> str:
    """Build a ticket URL from the API's payment_link field."""
    if not payment_link:
        return ""
    if payment_link.startswith(("http://", "https://")):
        return payment_link
    return f"{_SITE}{payment_link}"


def _cinema_url(cinema: dict) -> str:
    """Cinema page on bio.se; sessions without a payment link book from there."""
    slug = _clean(cinema.get("slug", ""))
    return f"{_SITE}/biografer/{slug}" if slug else ""


def _unescape(text: str) -> str:
    """Decode HTML entities, repeatedly: synopses arrive escaped up to three times."""
    while (decoded := html.unescape(text)) != text:
        text = decoded
    return text


def _clean(text: str) -> str:
    """Decode HTML entities and collapse whitespace; API fields carry both."""
    return " ".join(_unescape(text or "").split())


def _text(raw: str) -> str:
    """Plain text from a field whose markup arrives entity-escaped."""
    return _clean(re.sub(r"<[^>]+>", " ", _unescape(raw or "")))


def _runtime(raw: str) -> int | None:
    """Minutes from the run_time field; zero and blanks mean unknown."""
    digits = _clean(raw)
    return int(digits) or None if digits.isdigit() else None


def _film(movie: dict, title: str) -> Film:
    """Film metadata from an API movie record, under its title without version tags."""
    genres = [
        g for g in (_clean(part) for part in (movie.get("genre") or "").split(",")) if g and g not in _NOISE_GENRES
    ]
    language = _clean(movie.get("language", ""))
    # The language field names the listed version: "Svenska (dubbad)" is no original.
    # Swedish behind a "sv. tal" title tag stays: Swedish originals list so too, and _merge prefers other languages.
    dubbed = "dubb" in language.casefold()
    return _films.make(
        _SOURCE,
        title,
        overview=_text(movie.get("synopsis", "")),
        runtime=_runtime(movie.get("run_time", "")),
        genres=genres,
        age_rating=_clean(movie.get("rating", "")),
        poster_url=_clean(movie.get("poster_url", "")),
        url=f"{_SITE}/movie/{movie['id']}" if movie.get("id") else "",
        original_languages=frozenset() if dubbed else _version.languages(language),
    )


def _merge(film: Film, other: Film) -> Film:
    """*film* with its empty fields filled from *other*, a later entry under the same key.

    Original languages combine; Swedish counts only when no entry names another, since
    Swedish listings of foreign films are dubs.
    """
    filled = {
        f.name: getattr(other, f.name)
        for f in dataclasses.fields(film)
        if not getattr(film, f.name) and getattr(other, f.name)
    }
    languages = film.original_languages | other.original_languages
    filled["original_languages"] = languages - {Language.SWEDISH} or languages
    return dataclasses.replace(film, **filled)


def _venue(cinema: dict) -> Venue | None:
    """Venue for a cinema record, or None when the record carries no location."""
    name = _clean(cinema.get("title", ""))
    city = _clean(cinema.get("city", ""))
    address = _clean(cinema.get("street_address", ""))
    if not city and not address:
        return None
    return Venue(name=name, city=city or name.split()[0], address=address)


def _showtimes(
    payload: dict, fallback_url: str = ""
) -> Iterator[tuple[Film, date, time, str, str, str, str, str, tuple[str, ...], tuple[str, ...], bool]]:
    """Yield showtime fields, version source texts, raw attributes and whether the session is a broadcast.

    Sessions without a payment link get *fallback_url*, or are skipped without one.
    """
    for entry in payload["movies"]:
        movie = entry.get("movie", {})
        # Versions ride in titles: "Bortglömda ön eng. tal ATMOS".
        title_raw = _clean(movie.get("title", ""))
        title, fmt, language, subtitles = _version.split_title(title_raw)
        film = _film(movie, title)
        if not film.title:
            continue
        movie_label = _clean(movie.get("label") or "")
        # Broadcasts carry the non-film format too: Met operas under "Live på bio", some only under Opera.
        broadcast = movie_label == "Live på bio" or "Opera" in film.genres
        for sess in entry.get("sessions") or []:
            raw = sess.get("show_date_time", "")
            if not raw:
                continue
            format_raw = _clean(sess.get("format", ""))
            if format_raw == _NOT_A_FILM and not broadcast:
                continue
            url = _ticket_url(sess.get("payment_link", "")) or fallback_url
            if not url:
                continue
            try:
                when = datetime.fromisoformat(raw)
            except ValueError:
                log.warning("bio.se: %s: bad session time %r", film.title, raw)
                continue
            # Free-form labels: "English subtitles", "Svenskt tal", "+ Q & A".
            custom = tuple(
                label
                for label in (_clean(c) for c in (sess.get("session_attributes_names") or {}).get("custom") or [])
                if label
            )
            info = _clean(sess.get("sessionInfoText") or "")
            info = info if len(info) <= _LABEL_MAX else ""
            yield (
                film,
                when.date(),
                when.time(),
                url,
                _clean(sess.get("screen_name", "")),
                _version.formats(format_raw, fmt),
                language or _clean(sess.get("language", "")),
                next(
                    (_version.subtitles(_SUBTITLE_ATTRIBUTES[c]) for c in custom if c in _SUBTITLE_ATTRIBUTES),
                    _version.subtitles(sess.get("text", "")) or subtitles,
                ),
                (format_raw, *_version.title_suffixes(title_raw), *custom),
                tuple(dict.fromkeys(a for a in (format_raw, *custom, movie_label, info) if a)),
                broadcast,
            )


def parse() -> Iterator[Screening | Venue | Film]:
    films: dict[str, Film] = {}
    session = _http.session()
    session.headers["Accept"] = "application/json"

    resp = session.get(f"{_API}/cinemas", timeout=30)
    resp.raise_for_status()
    cinemas = resp.json()["cinemas"]
    log.info("bio.se: %d cinemas", len(cinemas))

    for cinema in cinemas:
        venue = _venue(cinema)
        if venue is None:
            log.info("  skipping %s: no city or address", cinema.get("title", ""))
            continue

        yield venue

        resp = session.post(f"{_API}/cinemas/films", json={"cinemaId": cinema["id"]}, timeout=15)
        resp.raise_for_status()
        payload = resp.json()

        # Malformed data skips the cinema; HTTP failures above abort the run.
        try:
            rows = list(_showtimes(payload, _cinema_url(cinema)))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.warning("bio.se: %s: malformed films payload: %s", venue.name, exc)
            continue

        count = 0
        for film, d, t, url, screen, fmt, language, subtitles, source_texts, raw_attributes, broadcast in rows:
            films[film.key] = _merge(films[film.key], film) if film.key in films else film
            yield Screening(
                # Broadcasts match only same-year TMDB entries, not older films of the same work.
                tmdb_id=_tmdb(film.title, year=d.year) if broadcast else _tmdb(film.title),
                title=film.title,
                film_key=film.key,
                date=d,
                time=t,
                cinema_name=venue.name,
                city=venue.city,
                **_version.screening_facts(
                    format=fmt,
                    language=language,
                    subtitles=subtitles,
                    source_texts=source_texts,
                    raw_attributes=raw_attributes,
                ),
                screen=screen,
                ticket_url=url,
            )
            count += 1

        if count:
            log.info("  %s (%s): %d screenings", venue.name, venue.city, count)

    # Entries of one film differ in completeness across cinemas.
    for film in films.values():
        yield _films.register(film)
