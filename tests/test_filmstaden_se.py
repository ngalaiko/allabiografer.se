"""filmstaden.se show mapping."""

import json
from datetime import date, time
from pathlib import Path

from parse.parsers.filmstaden_se import _film, _screening
from store.version import AudioKind, Dimension, Language, PresentationSystem, ProjectionMedium

_FIXTURES = Path(__file__).parent / "fixtures" / "filmstaden_se"
_SHOWS = json.loads((_FIXTURES / "shows.json").read_text())["items"]
_MOVIE = json.loads((_FIXTURES / "movie.json").read_text())


def _map(show):
    return _screening(show, tmdb_id=None, cinema_name="Filmstaden Bergakungen", city="Göteborg")


def test_dubbed_and_subtitled_versions_are_distinguishable():
    dubbed, original = (_map(s) for s in sorted(_SHOWS, key=lambda s: s["time"], reverse=True))

    assert dubbed.version.audio.languages == frozenset({Language.SWEDISH})
    assert original.version.audio.languages == frozenset({Language.ENGLISH})
    assert dubbed.version.subtitles.languages == original.version.subtitles.languages == frozenset({Language.SWEDISH})


def test_show_fields():
    screening = _map(_SHOWS[0])

    assert screening.title == "Bortglömda ön"
    assert screening.date == date(2026, 9, 26)
    assert screening.time == time(15, 45)
    assert screening.screen == "Salong 5"
    assert screening.presentation.experiences == frozenset()
    assert screening.ticket_url == "https://www.filmstaden.se/bokning/kop/18198ee1-3600-49c5-b213-9dfc1f13529b/"


def test_format_comes_from_attributes_and_version_title():
    show = _SHOWS[0] | {
        "attributes": [{"alias": "IMAX", "displayName": "IMAX"}, {"alias": "7.1", "displayName": "7.1"}],
        "movieVersion": _SHOWS[0]["movieVersion"] | {"title": "Bortglömda ön - 70mm"},
    }
    screening = _map(show)
    assert screening.presentation.experiences == frozenset({PresentationSystem.IMAX})
    assert screening.presentation.medium is ProjectionMedium.MM_70
    assert screening.raw_attributes[:2] == ("IMAX", "7.1")


def test_version_structured_attributes_and_language_lists_are_preserved():
    show = _SHOWS[0] | {
        "attributes": [],
        "movieVersion": _SHOWS[0]["movieVersion"]
        | {
            "attributes": [{"displayName": "Dolby Cinema"}, {"displayName": "3D"}],
            "audioLanguages": [{"displayName": "Svenska", "description": "Svenskt tal (dubbat)"}],
            "subtitlesLanguageInfo": {"displayName": "Ej textad", "description": ""},
        },
    }

    screening = _map(show)
    assert screening.presentation.experiences == frozenset({PresentationSystem.DOLBY_CINEMA})
    assert screening.presentation.dimension is Dimension.THREE_D
    assert screening.version.audio.kind is AudioKind.DUBBED
    assert screening.version.audio.languages == frozenset({Language.SWEDISH})
    assert screening.version.subtitles.languages == frozenset()
    assert "Svenskt tal (dubbat)" in screening.raw_attributes
    assert "Svenska" in screening.raw_attributes


def test_structured_audio_language_wins_over_description_prose():
    show = _SHOWS[0] | {
        "movieVersion": _SHOWS[0]["movieVersion"]
        | {
            "audioLanguages": [
                {
                    "displayName": "Spanska",
                    "alias": "es",
                    "description": "Spanskt tal,\\nHablar en español",
                }
            ],
        },
    }

    screening = _map(show)

    assert screening.version.audio.languages == frozenset({Language.SPANISH})
    assert any("Hablar en español" in value for value in screening.raw_attributes)


def test_structured_presentation_wins_over_conflicting_title_suffix():
    show = _SHOWS[0] | {
        "attributes": [{"displayName": "2D"}, {"displayName": "Digital"}],
        "movieVersion": _SHOWS[0]["movieVersion"] | {"title": "Film 3D 70mm"},
    }

    screening = _map(show)

    assert screening.presentation.dimension is Dimension.TWO_D
    assert screening.presentation.medium is ProjectionMedium.DIGITAL


def test_film_metadata_comes_from_show_and_detail():
    film = _film(_SHOWS[0]["movie"], _MOVIE)

    assert film.key == "filmstaden_se:bortglömda ön"
    assert film.title == "Bortglömda ön"
    assert film.title_original == "Forgotten Island"
    assert film.overview.startswith("Jo och Raissa har varit bästa vänner")
    assert film.runtime == 109
    assert film.genres == ["Äventyr", "Komedi", "Animerat", "Familj"]
    assert film.release_date == "2026-09-25"
    assert film.age_rating == "Från 7 år"
    assert film.url == "https://www.filmstaden.se/film/bortglomda-on/"


def test_poster_is_the_catalog_image_at_display_width():
    film = _film(_SHOWS[0]["movie"])

    assert film.poster_url == (
        "https://catalog.cinema-api.com/cf/images/ncg-images/"
        "59510c056e2445acb50003de1379a263.jpg?w=800&version=F488890EA42856B4EA0930C804BC11BD"
    )


def test_screenings_carry_the_film_key():
    film = _film(_SHOWS[0]["movie"], _MOVIE)
    screening = _screening(
        _SHOWS[0], tmdb_id=None, cinema_name="Filmstaden Bergakungen", city="Göteborg", film_key=film.key
    )

    assert screening.film_key == film.key


def test_unrated_films_have_no_age_rating():
    movie = dict(_SHOWS[0]["movie"], rating={"displayName": "Åldersgräns ej bestämd"})

    assert _film(movie).age_rating == ""


def test_titles_are_trimmed():
    show = _SHOWS[0] | {"movie": _SHOWS[0]["movie"] | {"title": "Bortglömda ön "}}
    assert _map(show).title == "Bortglömda ön"
    assert _film(show["movie"]).title == "Bortglömda ön"


_CLASSIC = json.loads((_FIXTURES / "classic.json").read_text())


def test_original_languages_come_from_detail():
    assert _film(_CLASSIC["movie"], _CLASSIC["detail"]).original_languages == frozenset({Language.ENGLISH})
    detail = _CLASSIC["detail"] | {"originalLanguages": [], "originalLanguage": "sv-SE"}
    assert _film(_CLASSIC["movie"], detail).original_languages == frozenset({Language.SWEDISH})


def test_overview_prefers_long_description_as_text():
    film = _film(_CLASSIC["movie"], _CLASSIC["detail"])
    assert film.overview.startswith("Henry Hill drömmer")
    assert film.overview.endswith("sätts både vänskap och lojalitet på prov.")
    assert "<p>" not in film.overview


def test_programme_suffix_is_stripped_from_titles():
    film = _film(_CLASSIC["movie"], _CLASSIC["detail"])
    assert film.title == "Goodfellas"
    assert film.key == "filmstaden_se:goodfellas"
    assert film.title_original == ""
    show = _SHOWS[0] | {"movie": _SHOWS[0]["movie"] | {"title": "Fjord - med samtal på Victoria"}}
    screening = _map(show)
    assert screening.title == "Fjord"
    assert "med samtal på Victoria" in screening.raw_attributes
    assert _film(show["movie"]).key == "filmstaden_se:fjord"


def test_rereleases_carry_the_production_year():
    assert _film(_CLASSIC["movie"], _CLASSIC["detail"]).release_date == "1990"
    recent = _CLASSIC["detail"] | {"productionYear": 2026}
    assert _film(_CLASSIC["movie"], recent).release_date == "2027-02-09"


def test_english_subtitles_attribute_sets_subtitles():
    show = _SHOWS[0] | {"attributes": [{"alias": "English subtitles", "displayName": "English subtitles"}]}
    assert _map(show).version.subtitles.languages == frozenset({Language.ENGLISH})
    show["movieVersion"] = _SHOWS[0]["movieVersion"] | {"subtitlesLanguageInfo": None}
    assert _map(show).version.subtitles.languages == frozenset({Language.ENGLISH})


def test_programme_suffixes_leave_original_titles_and_club_screenings():
    movie = _CLASSIC["movie"] | {"title": "Palestina 36 - med samtal på Victoria"}
    detail = _CLASSIC["detail"] | {"originalTitle": "Palestina 36 - med samtal på Victoria"}
    assert (_film(movie, detail).title, _film(movie, detail).title_original) == ("Palestina 36", "")
    movie = _CLASSIC["movie"] | {"title": "Paraplyerna i Cherbourg- Everdahl & Karlssons Filmklubb"}
    assert _film(movie).title == "Paraplyerna i Cherbourg"


def test_raw_attributes_skip_empties_and_duplicates():
    show = _SHOWS[0] | {
        "attributes": [{"displayName": "Klassiker"}],
        "movieVersion": _SHOWS[0]["movieVersion"] | {"attributes": [{"displayName": "Klassiker"}]},
    }
    attrs = _map(show).raw_attributes
    assert "" not in attrs
    assert len(attrs) == len(set(attrs))
    assert attrs[0] == "Klassiker"


def test_titles_collapse_inner_whitespace():
    show = _SHOWS[0] | {"movie": _SHOWS[0]["movie"] | {"title": "Gabbys dockskåp:  Filmen"}}
    assert _map(show).title == "Gabbys dockskåp: Filmen"
    assert _film(show["movie"]).title == "Gabbys dockskåp: Filmen"


def test_original_title_differing_only_in_punctuation_is_dropped():
    movie = _CLASSIC["movie"] | {"title": "Blir du ledsen om jag dör?"}
    detail = _CLASSIC["detail"] | {"originalTitle": "Blir du ledsen om jag dör"}
    assert _film(movie, detail).title_original == ""


def test_programme_labels_in_version_titles_become_raw_attributes():
    for version_title, label in (
        ("Arkipelag - Q&A med Alex Schulman och Fredrik Wikingson", "Q&A med Alex Schulman och Fredrik Wikingson"),
        ("Arkipelag - Smygpremiär - Rigoletto", "Smygpremiär"),
        ("Kärlek över Tanger - Med besök", "Med besök"),
        ("Fjord - pensionärsbio", "pensionärsbio"),
        ("Arkipelag - Stickbio ", "Stickbio"),
        ("Arkipelag - regissörsbesök", "regissörsbesök"),
    ):
        show = _SHOWS[0] | {"movieVersion": _SHOWS[0]["movieVersion"] | {"title": version_title}}
        assert label in _map(show).raw_attributes, version_title
    show = _SHOWS[0] | {"movieVersion": _SHOWS[0]["movieVersion"] | {"title": "Fjord - Drömland"}}
    assert "Drömland" not in _map(show).raw_attributes


def test_programme_labels_repeating_an_attribute_are_dropped():
    show = _SHOWS[0] | {
        "attributes": [{"displayName": "Smygpremiär"}],
        "movieVersion": _SHOWS[0]["movieVersion"] | {"title": "Arkipelag - smygpremiär"},
    }
    attrs = _map(show).raw_attributes
    assert "Smygpremiär" in attrs
    assert "smygpremiär" not in attrs


def test_genres_drop_noise_and_read_family_category():
    movie = _SHOWS[0]["movie"] | {
        "genres": [{"name": "Drama"}, {"name": "FLC"}],
        "categories": [{"displayName": "Barn och Familj"}, {"displayName": "Möten och Events filmlista"}],
    }
    assert _film(movie).genres == ["Drama", "Familj"]
