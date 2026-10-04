"""soderkopingsbio.se — BioSverige schedule API; tickets per showing on Tickster."""

from collections.abc import Iterator

from parse import _http, _version
from parse.parsers import _biosverige_api, _films, _tickster
from store import Film, Screening, Venue

_SOURCE = "soderkopingsbio_se"
_SITE = "https://soderkopingsbio.se"
_MOVIE_PAGE = "https://soderkopingsbio.se/filmer/"
_TICKSTER = "https://www.tickster.com/se/sv/events/by/f1rd9l09v0b7xdv/soderkopings-bio"
# The Tickster "PROGRAM" event the site links every showing to.
_TICKETS = "https://secure.tickster.com/d8fnyrrcl72fv8p"
_CINEMA = "Söderköpings Bio"
_CITY = "Söderköping"
_ADDRESS = "Ringvägen 45 A"


def parse() -> Iterator[Screening | Venue | Film]:
    yield Venue(name=_CINEMA, city=_CITY, address=_ADDRESS)

    session = _http.session()
    rows = list(_biosverige_api.showtimes(_biosverige_api.schedule(session, _SITE)))
    if not rows:
        return

    programme = _tickster.Programme.fetch(_TICKSTER, session)

    films: dict[str, Film] = {}
    for title, d, t, screen, language, subtitles, movie, booking_url in rows:
        film = films.get(title)
        if film is None:
            slug = movie.get("slug") or ""
            film = _films.make(
                _SOURCE,
                title,
                url=_MOVIE_PAGE + slug if slug else "",
                **(_biosverige_api.film_details(movie) if movie else {}),
            )
            film = films[title] = _films.register(film, session=session)
            yield film

        event, language, subtitles, labels = _biosverige_api.showing(programme, title, d, t, language, subtitles)
        yield Screening(
            tmdb_id=_biosverige_api.tmdb_id(title, movie),
            title=title,
            date=d,
            time=t,
            ticket_url=booking_url or (event.url if event else _TICKETS),
            cinema_name=_CINEMA,
            city=_CITY,
            screen=screen,
            **_version.screening_facts(language=language, subtitles=subtitles, raw_attributes=labels),
            film_key=film.key,
        )
