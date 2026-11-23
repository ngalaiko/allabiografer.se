"""Operator corrections for audited programmes that the booking feeds do not carry."""

import re
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
_KINO = "https://www.tickster.com/sv/events/"
_FILMSTADEN = "https://www.filmstaden.se/bokning/kop/"
# Session IDs cross-checked against Svenska Bio's flyers, announcements and show feeds.
_SVENSKA_BIO_LABELS = {
    **dict.fromkeys(
        (
            "5ed6526b-f88d-4c2a-bdd4-37504f128e38",
            "9a4af386-925e-435a-9d50-672b838f8ee5",
            "17495b44-1cda-441e-8493-3f230e087982",
            "c86ebd7a-43b1-4570-b9bc-8f0d40a8c13e",
            "cc399238-b132-48de-b3ff-7ebd16cd55ad",
            "5bd92e16-a9db-4d76-b466-9dab29862a64",
            "9a336554-b81d-413b-9464-97aab8ffa54a",
            "91eef287-05f2-4923-a26e-714d714293c5",
            "f97571e0-df81-4f63-a6c3-44bb687d588b",
            "2d89a19b-50ad-4a60-a5fe-d3db952b8a2f",
            "ba9c98d5-3712-431e-a870-75fb34dd7c59",
            "0eec1c46-c9d9-40a4-b894-32af6d82b7f6",
            "610d620c-03fa-4530-a00e-c7d40ebfea5e",
            "92fb1bff-8a0e-4d13-9f8d-09404c92bbef",
            "527cf82e-c8e3-4c4b-a905-09abc4f08dbc",
            "6d82db33-574e-4be1-86ff-785f9aef9666",
            "2aa2146c-78df-4bcb-b343-c739f400004d",
            "8c1155a8-cd4d-447d-8a76-454a4ed71fca",
            "6b54c53f-6893-483e-91b3-a05c7ba38ebd",
            "946fe2d9-ec93-4fa5-aa19-a80b5c595812",
            "fd496037-3d3e-4455-88e6-888ccdeafc58",
            "d72a0422-2970-470f-843a-1145ba6ee2c5",
            "de9b16d7-68c0-4747-9190-b3f958194fbb",
        ),
        PresentationSystem.KNATTEBIO,
    ),
    **dict.fromkeys(
        (
            "9b900890-3c6b-4872-a76c-46f0abb2473b",
            "67d251da-b50d-4408-bda6-3f6cdf5e090a",
            "e3280a9f-fe89-460f-8999-2584ebb3cfe5",
            "07da3008-2701-45c4-8581-369729434874",
            "20516506-b756-46a7-ad39-3a07114b21b3",
            "f58a7533-db00-4bd7-bae0-3bb23232bd8f",
            "7cf1245e-96cd-4433-9c43-901a7b0b2004",
            "69ebb1ea-9f9b-487d-8c3b-85cb6089f730",
            "e25d786f-33f4-4e1c-8656-3196f3332d97",
            "bc888555-5796-48a5-96d0-7c058006da10",
            "fcb57d2c-d9f3-4f2d-848a-26e807d56a3e",
            "5d82b931-f503-4615-a23a-f0772ba20e4a",
            "110f9647-d89d-46aa-b670-11af1a5048e2",
            "b520dfde-8e7d-4848-ab15-448d306a637a",
            "309963ee-8d91-4b7c-88e4-4e9d9eb76211",
            "f12abf30-81db-4a82-b6a2-51d66335ce18",
            "e7f66aed-56d7-4247-9fc3-b9a2fc71da7b",
            "a9c014e3-d84c-4e63-9395-5bba2749c2f1",
            "ae893ee1-3731-4dfa-8275-4c8cf83a4b7b",
            "06fd4d27-07ed-49dc-b892-1388be88f8b9",
            "c53207c0-9a7f-4f7c-acda-c348bb48bd1f",
            "697d8ca9-6265-4d82-a8f1-c67e2f07bfe9",
            "12126eac-0c90-48ed-9ca5-b60f2548a183",
            "9eb5301b-918a-41c2-9ead-bfc920d49029",
        ),
        PresentationSystem.PREVIEW,
    ),
    "1abc0d00-35da-43a6-9ba0-72c136411e51": PresentationSystem.BIOPASSET,
    **dict.fromkeys(
        (
            "3d47ca48-41e7-4fd3-89a1-57df38ee9587",
            "cda1996a-63b0-4cc4-802e-d996e402ae00",
            "aeb8e06e-9bf1-41ac-9296-c28eea640cd9",
            "511a1735-8c9b-4dc3-a53b-01ab5dd8911d",
            "f934d2d8-f878-4c74-b485-40b36bff3d39",
            "ca8fa547-81a1-4bad-aa83-1f0f5c72f07b",
            "019e80b0-96d2-43dd-8b55-9269d3b3795c",
            "338d3930-2475-446f-a909-24b29c8540da",
            "1118bd62-5d56-49b3-ba3a-52939de6c7fb",
            "ef84004e-9857-4d3b-bbb9-fd8fbeeb59b9",
            "63a70f6e-db91-44db-b856-59970c4233b5",
            "1881f106-00d6-41fa-8a36-18dca8a4ec30",
        ),
        PresentationSystem.BIOPASSET,
    ),
    **dict.fromkeys(
        ("700215f6-999a-4941-8ed2-20a004c9294f", "4d0d68a5-f614-4f18-b1c6-dfae0bf78a14"),
        PresentationSystem.PREMIERE,
    ),
}
_SODRAN_TICKETS = {
    "bio_se:kärlek över tanger": "wfbe9evymvb25hz",
    "bio_se:de gaulle motståndets pris": "vbdtj7dl0u038bd",
}
_ERSBODA = ("Umeå", "Ersboda Folkets Hus")
_ERSBODA_LABAN = (
    "https://www.tickster.com/se/sv/events/cwct1wy22f2zgbg/2026-11-21/familjebio-lilla-spoket-laban-busar-vidare"
)
_VAXJO_STALE_SHOW = "https://www.filmstaden.se/bokning/kop/06d49d6a-e7aa-46f3-9693-de9df51e9013/"
# Bio 3:an's own programme gives runtimes for these Tickster sessions.
_PITEA_RUNTIMES = {
    **dict.fromkeys(
        (
            "PMT1ZHCKNJZA2UE",
            "K2G2MXLYP3F8TZH",
            "3GVL9L61UGVXY49",
            "GULKPXFWZ58NMED",
            "XHV53M7C6EFVFJ2",
            "EYXWX3WJCFFLJN4",
            "TY3DZ5A2NXK64FZ",
        ),
        100,
    ),
    **dict.fromkeys(("XXNR7KYKUK3XH62", "4HE27BTKVGW5X5F", "F9KCX6HXWKDJ1J3"), 108),
    **dict.fromkeys(("2E6AY9HBFEV3YEB", "NX3M27VC0A29712"), 75),
    **dict.fromkeys(("RD1XWA373CA2FCY", "2MLY6BYCE1V320P"), 118),
}
_AUDITED_RUNTIMES = {
    _BIO + "18048/sessionId/55387": 119,
    _BIO + "18048/sessionId/55425": 119,
    _BIO + "18048/sessionId/55373": 117,
    _UMEA + "13571": 157,
    _UMEA + "13114": 118,
    _UMEA + "13577": 118,
    _UMEA + "13583": 118,
    _UMEA + "13579": 108,
    _UMEA + "13586": 108,
    _CNEMA + "20773": 91,
    _BIO + "3214/sessionId/7553": 101,
    _BIO + "3214/sessionId/7554": 101,
    **{
        _KINO + code: minutes
        for code, minutes in {
            "J56K8U50G4FNY1D": 119,
            "PVDKV2MUN8AWFN3": 157,
            "9PZYY5VLGHLPRNG": 157,
            "71V6TLHHC1BWZU2": 118,
            "FTLW1RJ4JUAD24N": 118,
        }.items()
    },
}
_AUDITED_LABELS = {
    _UMEA + "13114": {PresentationSystem.BIOVINO, PresentationSystem.PREVIEW},
    _UMEA + "13450": {PresentationSystem.PREMIERE},
    _UMEA + "13451": {PresentationSystem.PAWLIKOWSKI_SERIES},
    _UMEA + "13582": {PresentationSystem.KNATTEBIO},
    _CNEMA + "20445": {PresentationSystem.PREVIEW},
    _CNEMA + "20629": {PresentationSystem.LIVE_ON_CINEMA},
    _BIO + "5318/sessionId/4368": {PresentationSystem.QA},
    _KINO + "AYEDGWRBVVE3AJB": {PresentationSystem.CLASSIC},
    _KINO + "7B34YFEK9K5KXAG": {PresentationSystem.FAMILY_CINEMA},
    _KINO + "PN21PFLV7X13JR0": {PresentationSystem.PREMIERE, PresentationSystem.FILM_INTRODUCTION},
    **dict.fromkeys(
        [
            _KINO + s
            for s in ("7FZHRUKFMEJA6JC", "DNWPBPFEW5LFWF0", "PEV9F94ATPD60DH", "EP9XFG26U68JT0F", "71V6TLHHC1BWZU2")
        ],
        frozenset({PresentationSystem.PREMIERE}),
    ),
    **dict.fromkeys(
        [_KINO + s for s in ("H80GWU116ML8PU0", "A6DA9ETP7VPXNLN", "MXKWN35X8J96NNP")],
        frozenset({PresentationSystem.CHILDRENS_CINEMA}),
    ),
    **dict.fromkeys(
        [_UMEA + s for s in ("13577", "13578", "13580")]
        + [_CNEMA + s for s in ("20446", "20617", "20618", "20619", "20690")],
        frozenset({PresentationSystem.PREMIERE}),
    ),
}


def apply_programme_corrections(sd: "SiteData") -> None:
    karlstad = ("Karlstad", "Filmstaden Karlstad")
    if (venue := sd.venues.get(karlstad)) and venue.address == "Drottningggatan 33":
        sd.venues[karlstad] = replace(venue, address="Drottninggatan 33")
    regina = ("Östersund", "Östersund Folkets Bio Regina")
    if (venue := sd.venues.get(regina)) and venue.address == "Prästgatan 56 Östersund":
        sd.venues[regina] = replace(venue, address="Prästgatan 56 B, Östersund")

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
        if (show.city, show.cinema_name) == ("Piteå", "Piteå Bio 3:an") and show.ticket_url.startswith(_KINO):
            code = show.ticket_url.removeprefix(_KINO)
            if code == "82J988MC1AJ6XXK" and show.screen == "Salongen":
                # Bio 3:an and Tickster both list this exact event in Saga.
                continue
            if code in _PITEA_RUNTIMES:
                show = replace(show, runtime=_PITEA_RUNTIMES[code])
        if show.ticket_url == _VAXJO_STALE_SHOW and show.date == date(2026, 11, 19):
            # Filmstaden no longer lists this exact 14:30 session in its Växjö programme.
            continue
        version = show.version
        ticket = show.ticket_url
        experiences = show.presentation.experiences
        film = sd.films.get(show.film_key)
        movie = sd.movies[show.tmdb_id]
        if show.film_key == "filmstaden_se:paw patrol dinosaurie filmen" and sd.tmdb_ids.get(show.tmdb_id) == 1185806:
            # Filmstaden publishes the Swedish classification as unrestricted.
            sd.movies[show.tmdb_id] = replace(movie, age_rating="Barntillåten")
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
        elif (show.cinema_name, show.date, show.time, show.film_key) == (
            "Kristianstad Filmmuseet",
            date(2026, 11, 21),
            time(14),
            "bioguiden_se:kärlek över tanger",
        ):
            # Regionmuseet sells tickets directly on the dated event page.
            show = replace(show, ticket_url="https://regionmuseet.se/kalender/karlek-over-tanger-2/")

        if (
            show.source == "filmstaden_se"
            and ticket.startswith(_FILMSTADEN)
            and (label := _SVENSKA_BIO_LABELS.get(ticket.removeprefix(_FILMSTADEN).rstrip("/")))
        ):
            experiences |= {label}

        if show.source == "filmstaden_se" and any(
            re.fullmatch(r"Biopasset(?: [0-9]+)?", attribute, re.IGNORECASE) for attribute in show.raw_attributes
        ):
            experiences |= {PresentationSystem.BIOPASSET}

        if date(2026, 11, 19) <= show.date <= date(2026, 11, 21):
            if ticket in _AUDITED_RUNTIMES:
                show = replace(show, runtime=_AUDITED_RUNTIMES[ticket])
            experiences |= _AUDITED_LABELS.get(ticket, frozenset())
            if (
                show.film_key == "filmstaden_se:bts world tour arirang in kaohsiung live viewing"
                and show.city in {"Karlstad", "Luleå", "Växjö"}
                and show.date == date(2026, 11, 21)
                and show.time in {time(11, 45), time(16)}
            ):
                # The distributor lists the Swedish 11:45 show live and the 16:00 show as an encore.
                version = replace(version, audio=replace(version.audio, kind=AudioKind.ORIGINAL))
                if show.time == time(11, 45):
                    experiences |= {PresentationSystem.LIVE_ON_CINEMA}
                else:
                    version = replace(version, edition="Inspelad repris")
            if ticket == _BIO + "5570/sessionId/1991" and show.film_key == "bio_se:donnie darko":
                show = replace(show, runtime=133)
                version = replace(version, edition="Director's Cut", subtitles=SubtitleVersion(frozenset()))
                experiences |= {PresentationSystem.CLASSIC, PresentationSystem.FILM_INTRODUCTION}
            elif ticket == _BIO + "42051/sessionId/162" and show.film_key == "bio_se:låt den rätte komma in":
                version = replace(version, subtitles=SubtitleVersion(_ENGLISH))
                show = replace(show, ticket_url="https://www.gavle.se/evenemang/bio-lat-den-ratte-komma-in/")
            elif (show.cinema_name, show.date, ticket) == ("Lund Södran", date(2026, 11, 21), "http://kino.nu"):
                if code := _SODRAN_TICKETS.get(show.film_key):
                    show = replace(show, ticket_url=f"https://secure.tickster.com/{code}")
            elif show.cinema_name == "Lund Kino" and ticket.startswith(_KINO):
                code = ticket.removeprefix(_KINO)
                if code == "J56K8U50G4FNY1D":
                    version = replace(
                        version, audio=replace(version.audio, languages=frozenset({Language.ARABIC, Language.ENGLISH}))
                    )
                elif code in {"DNWPBPFEW5LFWF0", "BRYKFR8ADTVF1YE"}:
                    version = replace(
                        version, audio=replace(version.audio, languages=frozenset({Language.CATALAN, Language.SPANISH}))
                    )
                elif code in {"LL0MPN6L73LL78B", "LZABNGRK3A98MHF"}:
                    version = replace(version, subtitles=SubtitleVersion(_SWEDISH))
                elif code in {"EP9XFG26U68JT0F", "DJ97XHE5X8LR0M3"}:
                    version = replace(version, subtitles=SubtitleVersion(frozenset()))
                elif code == "MXKWN35X8J96NNP":
                    version = replace(
                        version, audio=AudioVersion(AudioKind.DUBBED, _SWEDISH), subtitles=SubtitleVersion(_SWEDISH)
                    )
            if ticket == _UMEA + "13450" and (show.date, show.film_key) == (
                date(2026, 11, 21),
                "bio_se:you can see everything",
            ):
                # The operator moved this exact session 35 minutes.
                show = replace(show, time=time(17, 5))
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

        if (film and film.key in {"bio_se:palestina 36", "filmstaden_se:julkul med greta bioupplevelsen"}) or (
            film
            and film.key == "nfbio_se:julkul med greta gris"
            and movie.title_sv != "Julkul med Greta: Bioupplevelsen"
        ):
            sd.movies[show.tmdb_id] = replace(movie, title_sv=film.title)
        elif film and film.key == "filmstaden_se:hadoota" and movie.title_sv == "حدوتة":
            sd.movies[show.tmdb_id] = replace(movie, title_sv=film.title, title_original="حدوتة")

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
