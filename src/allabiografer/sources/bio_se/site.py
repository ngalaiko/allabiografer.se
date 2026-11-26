"""bio.se — JSON API, all cinemas in one pass."""

import html
import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time

from allabiografer import normalize as _version
from allabiografer.model import Film, Venue
from allabiografer.sources import _films

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
# Match the same physical cinemas published by Nortic and their own websites.
_CINEMA_NAMES = {2126: "Biocafé Tellus", 31791: "Hypnos Theatre", 50407: "Bio Göta Lejon"}
# Nortic owns Tellus and Ellös; Hypnos and Rio Tomelilla publish their own programmes.
_OTHER_PROGRAMME_IDS = {2126, 3070, 31791, 39360}


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
    overview = _text(movie.get("synopsis", ""))
    # An introductory identification states the original year, unlike plot or screening dates.
    year = re.match(r"^[^.?!]{1,120}\bär en (?:[\w-]+\s+){0,3}[\w-]*film från ((?:19|20)\d{2})\b", overview)
    runtime = _runtime(movie.get("run_time", ""))
    # Bio.se movie 42095 is Villeneuve's Dune: Part Three, not a 90-minute cut.
    if str(movie.get("id")) == "42095" and runtime == 90:
        runtime = None
    return _films.make(
        _SOURCE,
        title,
        overview=overview,
        release_date=year.group(1) if year else "",
        runtime=runtime,
        genres=genres,
        age_rating=_clean(movie.get("rating", "")),
        poster_url=_clean(movie.get("poster_url", "")),
        url=f"{_SITE}/movie/{movie['id']}" if movie.get("id") else "",
        original_languages=frozenset() if dubbed else _version.languages(language),
        trailers=[_clean(url) for url in movie.get("trailer_urls") or [] if url],
    )


def _venue(cinema: dict) -> Venue | None:
    """Venue for a cinema record, or None when the record carries no location."""
    name = _CINEMA_NAMES.get(cinema.get("id"), _clean(cinema.get("title", "")))
    city = _clean(cinema.get("city", ""))
    # Bagarmossen Folkets Hus: bio.se puts its phone number in the city field.
    if cinema.get("id") == 50606:
        city = "Stockholm"
    address = _clean(cinema.get("street_address", ""))
    # The operator lists Kino at Kyrkogatan 1; bio.se supplies Södran's address.
    if cinema.get("id") == 2040:
        address = "Kyrkogatan 1"
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
        boras_donnie = str(movie.get("id")) == "50054" and title_raw == "Throwback Thursday: Donnie Darko"
        if boras_donnie:
            title_raw = "Donnie Darko"
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
            # Borås Stad lists this exact session as a screening of the Director's Cut.
            if (
                boras_donnie
                and _ticket_url(sess.get("payment_link", "")) == f"{_SITE}/bokning/cinemaId/5570/sessionId/1991"
            ):
                format_raw = ""
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
