"""Operator corrections for audited programmes that the booking feeds do not carry."""

from collections import defaultdict
from dataclasses import replace
from datetime import date, time
from typing import TYPE_CHECKING

from store import Venue
from store.version import AudioKind, AudioVersion, Language, PresentationSystem, ProjectionAttribute, SubtitleVersion

if TYPE_CHECKING:
    from build import SiteData
    from store import Screening

_BIO = "https://bio.se/bokning/cinemaId/"
_HYPNOS = _BIO + "31791/sessionId/"
_SWEDISH = frozenset({Language.SWEDISH})
_ENGLISH = frozenset({Language.ENGLISH})
_ELEKTRA = "Västerås Folkets Bio Elektra"
_NORDISK_LABELS = {
    "Knattebio": PresentationSystem.KNATTEBIO,
    "Bokklubb": PresentationSystem.BOOK_CLUB,
    "Biopasset": PresentationSystem.BIOPASSET,
}
_BIOPASSET = {
    (19, "13:00"),
    (19, "13:15"),
    (20, "13:15"),
    (20, "15:30"),
    (20, "19:30"),
    (20, "20:00"),
    (21, "15:40"),
    (21, "17:45"),
    (21, "20:00"),
}
_UMEA = _BIO + "13192/sessionId/"
_CNEMA = _BIO + "5/sessionId/"
_ERSBODA = ("Umeå", "Ersboda Folkets Hus")
_ERSBODA_LABAN = (
    "https://www.tickster.com/se/sv/events/cwct1wy22f2zgbg/2026-11-21/familjebio-lilla-spoket-laban-busar-vidare"
)
_AUDITED_RUNTIMES = {
    _UMEA + "13571": 157,
    _UMEA + "13114": 118,
    _UMEA + "13577": 118,
    _UMEA + "13583": 118,
    _UMEA + "13579": 108,
    _UMEA + "13586": 108,
    _CNEMA + "20773": 91,
}
_AUDITED_LABELS = {
    _UMEA + "13114": {PresentationSystem.BIOVINO, PresentationSystem.PREVIEW},
    _UMEA + "13450": {PresentationSystem.PREMIERE},
    _UMEA + "13451": {PresentationSystem.PAWLIKOWSKI_SERIES},
    _UMEA + "13582": {PresentationSystem.KNATTEBIO},
    _CNEMA + "20445": {PresentationSystem.PREVIEW},
    _CNEMA + "20629": {PresentationSystem.LIVE_ON_CINEMA},
    **dict.fromkeys(
        [_UMEA + s for s in ("13577", "13578", "13580")]
        + [_CNEMA + s for s in ("20446", "20617", "20618", "20619", "20690")],
        frozenset({PresentationSystem.PREMIERE}),
    ),
}


def apply_programme_corrections(sd: "SiteData") -> None:
    slots: dict[tuple, list[Screening]] = defaultdict(list)
    for show in sd.screenings:
        if (show.city, show.cinema_name) == ("Malmö", "Hypnos Theatre"):
            slots[show.tmdb_id, show.date, show.time].append(show)

    links = {}
    for slot in slots.values():
        operator = [s for s in slot if s.source == "hypnostheatre_com"]
        broker = [s for s in slot if s.source == "bio_se" and s.ticket_url.startswith(_HYPNOS)]
        # Borrow only the booking URL, and only for an unambiguous same-film slot.
        if len(slot) == 2 and len(operator) == len(broker) == 1:
            a, b = operator[0], broker[0]
            if a.ticket_url in ("https://bio.se/biografer/hypnos", b.ticket_url) and (
                not a.screen or not b.screen or a.screen == b.screen
            ):
                links[a] = b.ticket_url

    corrected = []
    for show in sd.screenings:
        # Hypnos owns the calendar. The ticket broker never adds showtimes.
        if (show.city, show.cinema_name, show.source) == ("Malmö", "Hypnos Theatre", "bio_se"):
            continue
        version = show.version
        ticket = show.ticket_url
        experiences = show.presentation.experiences
        film = sd.films.get(show.film_key)
        movie = sd.movies[show.tmdb_id]
        if show in links:
            show = replace(show, ticket_url=links[show])
        if show.film_key == "hypnostheatre_com:la chimera" and show.ticket_url in {_HYPNOS + "77", _HYPNOS + "78"}:
            # The operator explicitly advertises English subtitles for these sessions.
            version = replace(version, subtitles=SubtitleVersion(_ENGLISH))
        elif ticket == _BIO + "2128/sessionId/1300" and show.film_key == "bio_se:donnie darko":
            version = replace(version, edition="Director's Cut", subtitles=SubtitleVersion(frozenset()))
        elif (
            ticket == _BIO + "2128/sessionId/1272"
            and show.film_key == "bio_se:arabisk afton den syriska förlovningsringen"
        ):
            version = replace(
                version, audio=AudioVersion(languages=frozenset({Language.ARABIC})), subtitles=SubtitleVersion(_SWEDISH)
            )
        elif (show.cinema_name, show.date, show.time, show.film_key) == (
            "Malmö Panora",
            date(2026, 11, 19),
            time(18),
            "bio_se:freak show",
        ):
            experiences |= {PresentationSystem.DIRECTOR_QA}
        elif ticket == _BIO + "7/sessionId/15990" and show.film_key == "bio_se:lilla amélie eller tecknet för regn":
            version = replace(
                version, audio=AudioVersion(AudioKind.DUBBED, _SWEDISH), subtitles=SubtitleVersion(_SWEDISH)
            )
        elif ticket == _BIO + "41855/sessionId/2041" and show.film_key == "bio_se:asea nostalgi" and film:
            sd.films[film.key] = replace(film, runtime=90)
            sd.movies[show.tmdb_id] = replace(movie, runtime=90)
            version = replace(version, audio=AudioVersion(languages=_SWEDISH))
        elif ticket == _BIO + "16/sessionId/7668" and show.film_key == "bio_se:kvinnohuset" and film:
            # Bio Roxy's municipal programme gives 80 minutes and Swedish audio.
            sd.films[film.key] = replace(film, runtime=80)
            sd.movies[show.tmdb_id] = replace(movie, runtime=80)
            version = replace(version, audio=AudioVersion(languages=_SWEDISH))

        if date(2026, 11, 19) <= show.date <= date(2026, 11, 21):
            if ticket in _AUDITED_RUNTIMES:
                show = replace(show, runtime=_AUDITED_RUNTIMES[ticket])
            experiences |= _AUDITED_LABELS.get(ticket, frozenset())
            if ticket == _UMEA + "13450" and (show.date, show.film_key) == (
                date(2026, 11, 21),
                "bio_se:you can see everything",
            ):
                # The operator moved this exact session 35 minutes and marked it full.
                show = replace(
                    show,
                    time=time(17, 5),
                    raw_attributes=(*show.raw_attributes, "Slutsålt"),
                )
            elif ticket == _UMEA + "13573":
                version = replace(version, subtitles=SubtitleVersion(_ENGLISH))
            elif ticket in {_UMEA + "13578", _UMEA + "13588"}:
                version = replace(version, subtitles=SubtitleVersion(frozenset()))
            elif ticket == _UMEA + "13582":
                version = replace(version, audio=AudioVersion(languages=_SWEDISH), subtitles=SubtitleVersion(_SWEDISH))
            elif (show.city, show.cinema_name) == _ERSBODA and ticket == _ERSBODA_LABAN:
                show = replace(show, runtime=62, ticket_url="https://secure.tickster.com/cwct1wy22f2zgbg")
                experiences |= {PresentationSystem.FAMILY_CINEMA}
                venue = sd.venues.get(_ERSBODA) or Venue(city=show.city, name=show.cinema_name)
                sd.venues[_ERSBODA] = replace(venue, address="Byttgränd 13, Umeå")

        if film and film.key == "biorodakvarn_se:citizen kane" and "otextad 4k-kopia" in film.overview.casefold():
            show = replace(
                show,
                presentation=replace(
                    show.presentation, projection=show.presentation.projection | {ProjectionAttribute.K4}
                ),
            )

        if show.cinema_name == _ELEKTRA and date(2026, 11, 19) <= show.date <= date(2026, 11, 21):
            if (show.date.day, show.time.strftime("%H:%M")) in _BIOPASSET:
                experiences |= {PresentationSystem.BIOPASSET}
            if ticket == _BIO + "41855/sessionId/2112":
                experiences |= {PresentationSystem.NEW_FINNISH_FILM}
            if ticket == _BIO + "41855/sessionId/2113":
                version = replace(version, edition="Del II")

        if show.source == "nfbio_se":
            experiences |= frozenset(_NORDISK_LABELS[a] for a in show.raw_attributes if a in _NORDISK_LABELS)
        if (
            show.source == "bio_se"
            and show.cinema_name in {_ELEKTRA, "Uppsala Fyrisbiografen"}
            and "Föreställning där Cineville-kortet gäller" in show.raw_attributes
        ):
            experiences |= {PresentationSystem.CINEVILLE}

        if film and film.key in {"bio_se:palestina 36", "nfbio_se:julkul med greta gris"}:
            sd.movies[show.tmdb_id] = replace(movie, title_sv=film.title)

        if show.source == "doclounge_se" and (show.date, show.time, show.cinema_name, show.film_key, ticket) == (
            date(2026, 11, 23),
            time(18, 30),
            "Moriska Paviljongen",
            "doclounge_se:cambodian beer dreams",
            "https://billetto.se/e/doc-lounge-pres-cambodian-beer-dreams-biljetter-1980606",
        ):
            show = replace(show, time=time(19))
        if (version, experiences) != (show.version, show.presentation.experiences):
            show = replace(show, version=version, presentation=replace(show.presentation, experiences=experiences))
        corrected.append(show)
    sd.screenings = corrected
