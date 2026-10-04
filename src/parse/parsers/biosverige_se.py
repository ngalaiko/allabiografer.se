"""BioSverige (Videvox Cinecore) cinema sites — per-site schedule API."""

from collections.abc import Iterator
from dataclasses import dataclass

from parse import _http, _version
from parse.parsers import _biosverige_api, _films, _tickster
from store import Film, Screening, Venue

_SOURCE = "biosverige_se"


@dataclass(frozen=True)
class _Site:
    url: str
    name: str
    city: str
    address: str
    # The site's "@booking" setting: where its buy buttons lead.
    tickets: str
    # Tickster organiser listing with one event per showing.
    programme: str = ""


# Söderköping has its own parser; Vårgårda Rialto and Robertsfors are on bio.se.
_SITES = (
    _Site(
        "https://filipstad.biosverige.se",
        "Bio Monitor",
        "Filipstad",
        "Viktoriagatan 8",
        "https://secure.tickster.com/sv/y4vknkelzhvmpp6/",
        "https://www.tickster.com/se/sv/events/by/ukh54uat4kwp0b4/bio-monitor",
    ),
    _Site(
        "https://jarpen.biosverige.se",
        "Järpen Bion",
        "Järpen",
        "Strandvägen 22",
        "https://www.tickster.com/se/sv/events/by/t93wpddl1nc93uz/jarpen-bion",
        "https://www.tickster.com/se/sv/events/by/t93wpddl1nc93uz/jarpen-bion",
    ),
    _Site(
        "https://gislaved.biosverige.se",
        "Folkets Hus Gislaved",
        "Gislaved",
        "Danska vägen 6 A",
        "https://boka.folketshusgislaved.se/gislaved/resource/movies",
    ),
    _Site(
        "https://casablancabio.se",
        "Bio Casablanca",
        "Karlsborg",
        "Strandvägen 15",
        "https://secure.tickster.com/sv/eaukgpvmklav5gg",
        "https://www.tickster.com/se/sv/events/by/fer7uddjdxuaa8u/bio-casablanca",
    ),
    _Site(
        "https://mariannelundsbio.se",
        "Mariannelunds Bio",
        "Mariannelund",
        "Östra Storgatan 6",
        "https://secure.tickster.com/sv/fjnrhjm4dltbtfl",
        "https://www.tickster.com/se/sv/events/by/jdg9ek45zlh6xtu/mariannelunds-bio",
    ),
    # No "@booking" setting.
    _Site(
        "https://smedjebacken.biosverige.se",
        "Folkets Hus Smedjebacken",
        "Smedjebacken",
        "Vasagatan 11",
        "https://smedjebacken.biosverige.se",
    ),
)


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()
    films: dict[str, Film] = {}

    for site in _SITES:
        yield Venue(name=site.name, city=site.city, address=site.address)

        rows = list(_biosverige_api.showtimes(_biosverige_api.schedule(session, site.url)))
        programme = _tickster.Programme.fetch(site.programme, session) if rows and site.programme else None

        for title, d, t, screen, language, subtitles, movie, booking_url in rows:
            film = films.get(title)
            if film is None:
                slug = movie.get("slug") or ""
                film = _films.make(
                    _SOURCE,
                    title,
                    url=f"{site.url}/filmer/{slug}" if slug else "",
                    **(_biosverige_api.film_details(movie) if movie else {}),
                )
                film = films[title] = _films.register(film, session=session)
                yield film

            event, labels = None, ()
            if programme is not None:
                event, language, subtitles, labels = _biosverige_api.showing(
                    programme, title, d, t, language, subtitles
                )
            yield Screening(
                tmdb_id=_biosverige_api.tmdb_id(title, movie),
                title=title,
                date=d,
                time=t,
                ticket_url=booking_url or (event.url if event else site.tickets),
                cinema_name=site.name,
                city=site.city,
                screen=screen,
                **_version.screening_facts(language=language, subtitles=subtitles, raw_attributes=labels),
                film_key=film.key,
            )
