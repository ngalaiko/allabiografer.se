"""Verified Göteborg programme metadata not represented by the source feeds."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from store.version import AgeRating, Language, ProjectionAttribute, ProjectionMedium

if TYPE_CHECKING:
    from build import SiteData
    from store import Screening

_SWEDISH = frozenset({Language.SWEDISH})
_FLIRT_AUDIO = frozenset({Language.ENGLISH, Language.GERMAN, Language.JAPANESE})
_FLIRT_PRODUCTION = "https://www.capitolgbg.se/produktion/cinemateket-flirt/"
_FLIRT_TICKET = "https://capitolgbg.internetbokningen.com/chap/api/tomovie@salongnr=3&tid=14:00&datum=2026-11-21"
# These individual checkouts explicitly say Swedish audio and Swedish subtitles.
_SANKT_JORGEN = {
    "l7rbgcf7g54a45x": "jävla karlar",
    "w3e8r5yj7x22lun": "arkipelag",
    "3jv58r59hdlwhvw": "jävla karlar",
    "4mp6tr9k0d7tw23": "arkipelag",
    "rwa5wyg22xwyx1y": "jävla karlar",
}


def _language(show: Screening, audio: frozenset[Language], *, fallback: bool = False) -> Screening:
    version = show.version
    return replace(
        show,
        version=replace(
            version,
            audio=replace(version.audio, languages=(version.audio.languages if fallback else None) or audio),
            subtitles=replace(
                version.subtitles,
                languages=_SWEDISH if version.subtitles.languages is None else version.subtitles.languages,
            ),
        ),
    )


def apply_metadata(sd: SiteData) -> None:
    """Correct published facts without changing source rows, film identities, or URLs."""
    for index, show in enumerate(sd.screenings):
        if show.city != "Göteborg":
            continue
        film = sd.films.get(show.film_key)
        movie = sd.movies[show.tmdb_id]
        tmdb_id = sd.tmdb_ids[show.tmdb_id]
        key = (show.cinema_name, show.source, show.film_key)
        presentation = show.presentation

        if key == ("Capitol", "wp_theatre", "wp_theatre:sheep in the box") and tmdb_id == 1553969 and film:
            # Capitol and Filmstaden advertise the same work as Sheep in the Box.
            sd.movies[show.tmdb_id] = replace(movie, title_sv=film.title)
        elif (
            key == ("Capitol", "wp_theatre", "wp_theatre:flirt")
            and show.screen == "Cinemateket"
            and show.ticket_url == _FLIRT_TICKET
            and film
            and film.url == _FLIRT_PRODUCTION
        ):
            # SFI's listing for this exact session: filmId=14132&cityId=2.
            sd.films[film.key] = replace(
                film,
                runtime=85,
                release_date="1995",
                age_rating=AgeRating.FROM_11,
                directors=["Hal Hartley"],
                original_languages=_FLIRT_AUDIO,
            )
            sd.movies[show.tmdb_id] = replace(
                movie,
                runtime=85,
                release_date="1995",
                age_rating=AgeRating.FROM_11,
                directors=["Hal Hartley"],
            )
            show = _language(show, _FLIRT_AUDIO, fallback=True)
            show = replace(show, presentation=replace(presentation, medium=ProjectionMedium.MM_35))
        elif show.cinema_name == "Bio Roy" and show.source == "folkets_hus_och_parker":
            synopsis = film.overview.casefold() if film else ""
            projection = presentation.projection
            if show.film_key == "bioroy_se:citizen kane" and tmdb_id == 15 and film:
                sd.movies[show.tmdb_id] = replace(movie, title_sv=film.title)
                if "vi visar" in synopsis and "4k-kopia" in synopsis:
                    projection |= {ProjectionAttribute.K4}
            show = replace(show, presentation=replace(presentation, projection=projection))
        elif (
            key == ("Göteborg Hagabion", "bio_se", "bio_se:silent friend")
            and show.ticket_url == "https://bio.se/bokning/cinemaId/17705/sessionId/14092"
            and show.version.audio.languages == {Language.GERMAN}
        ):
            # Hagabion's own film listing includes all three spoken languages.
            show = _language(show, frozenset({Language.GERMAN, Language.ENGLISH, Language.CANTONESE}))
        elif show.cinema_name == "Sankt Jörgen Park Biografen" and show.source == "bioguiden_se":
            event = show.ticket_url.removeprefix("https://secure.tickster.com/")
            if event in _SANKT_JORGEN and show.film_key == f"bioguiden_se:{_SANKT_JORGEN[event]}":
                show = _language(show, _SWEDISH, fallback=True)

        sd.screenings[index] = show
