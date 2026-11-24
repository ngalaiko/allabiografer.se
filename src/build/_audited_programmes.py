"""Operator corrections for audited programmes that the booking feeds do not carry."""

from collections import defaultdict
from dataclasses import replace
from datetime import date, time
from typing import TYPE_CHECKING

from store import Venue
from store.version import (
    AccessibilityFeature,
    AudioKind,
    AudioVersion,
    AuditoriumAttribute,
    Language,
    ProjectionAttribute,
    SubtitleVersion,
)

if TYPE_CHECKING:
    from build import SiteData
    from store import Screening

_BIO = "https://bio.se/bokning/cinemaId/"
_HYPNOS = _BIO + "31791/sessionId/"
_SWEDISH = frozenset({Language.SWEDISH})
_ENGLISH = frozenset({Language.ENGLISH})
_ELEKTRA = "Västerås Folkets Bio Elektra"
_UMEA = _BIO + "13192/sessionId/"
_CNEMA = _BIO + "5/sessionId/"
_KINO = "https://www.tickster.com/sv/events/"
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
            (show.city, show.cinema_name, show.film_key)
            == ("Ystad", "Biografteatern Scala", "bioguiden_se:a talent for murder")
            and show.date in {date(2026, 11, 25), date(2026, 11, 26)}
            and show.time == time(19)
            and ticket
            == "https://www.bioguiden.se/biografer.aspx?cityid=121&theatreid=06162d84-474a-4f9a-abc5-c7ce7b7a79aa"
        ):
            show = replace(show, ticket_url="https://bioscala.se/bokning?id=519")

        if (show.source, show.city, show.cinema_name, show.screen) == (
            "filmstaden_se",
            "Norrtälje",
            "Royal Norrtälje",
            "Salong 2",
        ):
            # Royal's programme identifies Salong 2 as its VIP auditorium.
            show = replace(
                show,
                presentation=replace(
                    show.presentation, auditorium=show.presentation.auditorium | {AuditoriumAttribute.VIP}
                ),
            )

        if show.source == "filmstaden_se" and "Syntolkning via app" in show.raw_attributes:
            features = show.accessibility.features - {AccessibilityFeature.AUDIO_DESCRIPTION}
            show = replace(
                show,
                accessibility=replace(
                    show.accessibility, features=features | {AccessibilityFeature.AUDIO_DESCRIPTION_VIA_APP}
                ),
            )

        if date(2026, 11, 19) <= show.date <= date(2026, 11, 21):
            if ticket in _AUDITED_RUNTIMES:
                show = replace(show, runtime=_AUDITED_RUNTIMES[ticket])
            if (
                show.film_key == "filmstaden_se:bts world tour arirang in kaohsiung live viewing"
                and show.city in {"Karlstad", "Luleå", "Växjö"}
                and show.date == date(2026, 11, 21)
                and show.time in {time(11, 45), time(16)}
            ):
                version = replace(version, audio=replace(version.audio, kind=AudioKind.ORIGINAL))
            if ticket == _BIO + "5570/sessionId/1991" and show.film_key == "bio_se:donnie darko":
                show = replace(show, runtime=133)
                version = replace(version, edition="Director's Cut", subtitles=SubtitleVersion(frozenset()))
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
                venue = sd.venues.get(_ERSBODA) or Venue(city=show.city, name=show.cinema_name)
                sd.venues[_ERSBODA] = replace(venue, address="Byttgränd 13, Umeå")

        if film and film.key == "biorodakvarn_se:citizen kane" and "otextad 4k-kopia" in film.overview.casefold():
            show = replace(
                show,
                presentation=replace(
                    show.presentation, projection=show.presentation.projection | {ProjectionAttribute.K4}
                ),
            )

        if (
            show.cinema_name == _ELEKTRA
            and date(2026, 11, 19) <= show.date <= date(2026, 11, 21)
            and ticket == _BIO + "41855/sessionId/2113"
        ):
            version = replace(version, edition="Del II")

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
        if version != show.version:
            show = replace(show, version=version)
        corrected.append(show)
    sd.screenings = corrected
