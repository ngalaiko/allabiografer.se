"""bio.se cinema records and session payloads."""

import json
from datetime import date, time
from pathlib import Path

from parse import _version
from parse.parsers import _films as _films_mod
from parse.parsers.bio_se import _cinema_url, _merge, _showtimes, _ticket_url, _venue
from store import Venue
from store.version import AudioKind, Language

_FIXTURES = Path(__file__).parent / "fixtures" / "bio_se"
_CINEMAS = {c["title"]: c for c in json.loads((_FIXTURES / "cinemas.json").read_text())["cinemas"]}


def _films(name: str) -> dict:
    return json.loads((_FIXTURES / f"{name}-films.json").read_text())


def test_venue_trims_padded_city_and_address():
    assert _venue(_CINEMAS["Alvesta Bio Thalia"]) == Venue(
        name="Alvesta Bio Thalia", city="Alvesta", address="Allbogatan 17"
    )
    assert _venue(_CINEMAS["Falköping Cosmorama"]) == Venue(
        name="Falköping Cosmorama", city="Falköping", address="Sankt Olofsgatan 20"
    )


def test_venue_skips_records_without_a_location():
    assert _venue(_CINEMAS["Enter Details"]) is None
    assert _venue(_CINEMAS["Gåxsjö Bio"]) is None


def _rows(name: str) -> list[tuple]:
    return [tuple((f.title, *rest)[:8]) for f, *rest in _showtimes(_films(name))]


def test_showtimes_unescape_entities_in_titles():
    titles = {t for t, *_ in _rows("falkoping-cosmorama")}
    assert "Minioner & Monster" in titles


def test_showtimes_read_session_fields():
    assert _rows("falkoping-cosmorama") == [
        (
            "Spider-Man: Brand New Day",
            date(2026, 9, 22),
            time(18, 30),
            "https://www.eurostar.se/Boka/f284624",
            "Screen 1",
            "",
            "Engelska",
            "Svensk text",
        ),
        (
            "Spider-Man: Brand New Day",
            date(2026, 10, 9),
            time(19, 15),
            "https://www.eurostar.se/Boka/f285137",
            "Screen 3",
            "",
            "Engelska",
            "Svensk text",
        ),
        (
            "Minioner & Monster",
            date(2026, 10, 4),
            time(17, 0),
            "https://www.eurostar.se/Boka/f285109",
            "Screen 2",
            "",
            "Svenskt tal",
            "",
        ),
    ]


def test_showtimes_normalise_languages():
    assert _rows("stockholm-bio-aspen") == [
        (
            "The Lost Boys",
            date(2026, 10, 31),
            time(20, 15),
            "https://biljetter.bioaspen.se/#/book/57503",
            "Aspen",
            "",
            "Eng.",
            "Svensk text",
        )
    ]


def test_ticket_url_absolutises_site_relative_payment_links():
    assert _ticket_url("/bokning/cinemaId/5/sessionId/20077") == "https://bio.se/bokning/cinemaId/5/sessionId/20077"
    assert _ticket_url("https://www.eurostar.se/Boka/f284624") == "https://www.eurostar.se/Boka/f284624"
    assert _ticket_url("") == ""


def test_film_reads_metadata_and_strips_escaped_markup():
    film, *_ = next(iter(_showtimes(_films("falkoping-cosmorama"))))
    assert film.key == "bio_se:spider man brand new day"
    assert film.source == "bio_se"
    assert film.overview.startswith("Efter rekordsuccén inleder Spider-Man: Brand New Day")
    assert "<br>" not in film.overview
    assert film.runtime == 150
    assert film.genres == ["Adventure", "Action"]
    assert film.age_rating == "Från 11 år"
    assert film.url == "https://bio.se/movie/42156"
    assert film.poster_url.endswith("spider-man-brandnewday_reflection_144")
    assert {language.value for language in film.original_languages} == {"Engelska"}


def test_film_leaves_unstated_fields_empty():
    films = {f.title: f for f, *_ in _showtimes(_films("falkoping-cosmorama"))}
    film = films["Minioner & Monster"]
    assert (film.overview, film.runtime, film.genres, film.age_rating, film.poster_url) == ("", None, [], "", "")


def test_film_normalises_abbreviated_ratings():
    film, *_ = next(iter(_showtimes(_films("stockholm-bio-aspen"))))
    assert film.age_rating == "Barntillåten"


def test_screenings_share_their_film_key():
    keys = {f.key for f, *_ in _showtimes(_films("falkoping-cosmorama"))}
    assert keys == {"bio_se:spider man brand new day", "bio_se:minioner monster"}


def test_version_tags_move_from_title_to_session_fields():
    payload = {
        "movies": [
            {
                "movie": {"id": 1, "title": "Bortglömda ön eng. tal ATMOS"},
                "sessions": [
                    {
                        "show_date_time": "2026-10-01T18:00:00",
                        "payment_link": "https://example.se/1",
                        "screen_name": "Salong 1",
                        "format": "2D Digital",
                        "language": "",
                        "text": "Svenska",
                    }
                ],
            },
            {
                "movie": {"id": 2, "title": "Avengers: Endgame Encore"},
                "sessions": [
                    {
                        "show_date_time": "2026-10-01T20:00:00",
                        "payment_link": "https://example.se/2",
                        "screen_name": "Salong 2",
                        "format": "IMAX",
                        "language": "Engelska",
                        "text": "Svenska",
                    }
                ],
            },
        ]
    }
    assert [row[4:] for row in (tuple(r) for r in _showtimes(payload))] == [
        (
            "Salong 1",
            "Dolby Atmos",
            "Engelskt tal",
            "Svensk text",
            ("2D Digital", " eng. tal", " ATMOS"),
            ("2D Digital",),
        ),
        ("Salong 2", "IMAX", "Engelska", "Svensk text", ("IMAX",), ("IMAX",)),
    ]
    assert [f.title for f, *_ in _showtimes(payload)] == ["Bortglömda ön", "Avengers: Endgame Encore"]


def _session(**fields) -> dict:
    return {
        "show_date_time": "2026-10-01T18:00:00",
        "payment_link": "https://example.se/1",
        "screen_name": "Salong 1",
        "format": "",
        "language": "",
        "text": "",
        "session_attributes_names": {"reserved": None, "custom": None},
    } | fields


def _payload(movie: dict, *sessions: dict) -> dict:
    return {"movies": [{"movie": {"id": 1, "title": "Film"} | movie, "sessions": list(sessions)}]}


def _facts(row: tuple) -> dict:
    _, _, _, _, _, fmt, language, subtitles, source_texts, raw_attributes = row
    return _version.screening_facts(
        format=fmt, language=language, subtitles=subtitles, source_texts=source_texts, raw_attributes=raw_attributes
    )


def test_dubbed_sessions_keep_their_audio_role():
    payload = _payload({"language": "Svenska (dubbad)"}, _session(language="Svenska (dubbad)", text="Svenska"))
    [row] = _showtimes(payload)
    facts = _facts(row)
    assert facts["version"].audio.kind is AudioKind.DUBBED
    assert facts["version"].audio.languages == frozenset({Language.SWEDISH})
    assert row[0].original_languages == frozenset()


def test_session_language_matching_the_movie_still_sets_audio():
    [row, *_] = _showtimes(_films("falkoping-cosmorama"))
    assert _facts(row)["version"].audio.languages == frozenset({Language.ENGLISH})


def test_swedish_title_tag_with_swedish_listing_reads_as_swedish():
    # Other listings' non-Swedish languages override it on merge.
    [row] = list(_showtimes(_films("falkoping-cosmorama")))[2:]
    assert row[0].title == "Minioner & Monster"
    assert row[0].original_languages == frozenset({Language.SWEDISH})


def test_sessions_without_payment_link_fall_back_to_the_cinema_page():
    payload = _payload({}, _session(payment_link=""))
    [row] = _showtimes(payload, fallback_url="https://bio.se/biografer/stockholm-bio-aspen")
    assert row[3] == "https://bio.se/biografer/stockholm-bio-aspen"
    assert list(_showtimes(payload)) == []


def test_cinema_url_uses_the_slug():
    assert _cinema_url(_CINEMAS["Falköping Cosmorama"]).startswith("https://bio.se/biografer/")
    assert _cinema_url({"slug": ""}) == ""


def test_custom_labels_feed_versions_and_raw_attributes():
    payload = _payload(
        {"language": "Ukrainska"},
        _session(
            language="Ukrainska",
            format="2D Digital",
            session_attributes_names={"reserved": ["onlineköp"], "custom": ["English subtitles", "+ Q & A"]},
        ),
        _session(language="Franska", text="Svenska", session_attributes_names={"custom": ["Eng text"]}),
    )
    subtitled, labelled = _showtimes(payload)
    facts = _facts(subtitled)
    assert facts["version"].subtitles.languages == frozenset({Language.ENGLISH})
    assert facts["raw_attributes"] == ("2D Digital", "English subtitles", "+ Q & A")
    # The session's text field wins over custom labels.
    assert _facts(labelled)["version"].subtitles.languages == frozenset({Language.SWEDISH})


def test_merge_fills_fields_missing_from_the_first_entry():
    first = _films_mod.make("bio_se", "Film", url="https://bio.se/movie/1")
    later = _films_mod.make(
        "bio_se",
        "Film",
        overview="Synopsis",
        age_rating="11",
        runtime=90,
        original_languages=frozenset({Language.ENGLISH}),
        url="https://bio.se/movie/2",
    )
    merged = _merge(first, later)
    assert (merged.overview, merged.age_rating, merged.runtime) == ("Synopsis", "Från 11 år", 90)
    assert merged.original_languages == frozenset({Language.ENGLISH})
    assert merged.url == "https://bio.se/movie/1"


def test_merge_prefers_non_swedish_original_languages():
    swedish = _films_mod.make("bio_se", "Hexe", original_languages=frozenset({Language.SWEDISH}))
    english = _films_mod.make("bio_se", "Hexe", original_languages=frozenset({Language.ENGLISH}))
    assert _merge(swedish, english).original_languages == frozenset({Language.ENGLISH})
    assert _merge(english, swedish).original_languages == frozenset({Language.ENGLISH})
    assert _merge(swedish, _films_mod.make("bio_se", "Hexe")).original_languages == frozenset({Language.SWEDISH})


def test_english_subtitles_label_overrides_the_text_field():
    payload = _payload(
        {"language": "Japanska"}, _session(text="Sv.", session_attributes_names={"custom": ["English subtitles"]})
    )
    [row] = _showtimes(payload)
    assert _facts(row)["version"].subtitles.languages == frozenset({Language.ENGLISH})


def test_swedish_title_tag_keeps_a_swedish_listed_language():
    payload = _payload({"title": "Flyg! sa Alfons Åberg (Sv. tal)", "language": "Sv."}, _session())
    [row] = _showtimes(payload)
    assert row[0].original_languages == frozenset({Language.SWEDISH})


def test_non_film_sessions_are_dropped_unless_broadcast():
    payload = {
        "movies": [
            {
                "movie": {"id": 1, "title": "Melodikrysset", "genre": "Unknown"},
                "sessions": [_session(format="Inte en film")],
            },
            {
                "movie": {"id": 2, "title": "Otello", "genre": "Opera", "label": "Live på bio"},
                "sessions": [_session(format="Inte en film")],
            },
            {
                "movie": {"id": 3, "title": "Così fan tutte", "genre": "Opera"},
                "sessions": [_session(format="Inte en film")],
            },
            {"movie": {"id": 4, "title": "Film", "label": "Klassiker"}, "sessions": [_session(format="2D Digital")]},
        ]
    }
    assert [f.title for f, *_ in _showtimes(payload)] == ["Otello", "Così fan tutte", "Film"]


def test_movie_label_and_short_session_info_become_raw_attributes():
    payload = _payload(
        {"label": "Klassiker"},
        _session(format="2D Digital", sessionInfoText="Barnvagnsbio"),
        _session(sessionInfoText="ONUMRERADE PLATSER\r\n\r\nFrån och med maj 2026 är platserna onumrerade i salongen."),
    )
    short, prose = _showtimes(payload)
    assert short[-1] == ("2D Digital", "Klassiker", "Barnvagnsbio")
    assert prose[-1] == ("Klassiker",)


def test_noise_genres_are_dropped():
    [row] = _showtimes(_payload({"genre": "Unknown,Drama,Film,Event,Alternative Content"}, _session()))
    assert row[0].genres == ["Drama"]


def test_overview_unescapes_nested_entities():
    [row] = _showtimes(
        _payload({"synopsis": "Teater &amp;amp;quot;bäst&amp;amp;quot;&lt;br&gt;Marilyn &amp;amp; Edith"}, _session())
    )
    assert row[0].overview == 'Teater "bäst" Marilyn & Edith'
