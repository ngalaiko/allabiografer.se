"""Build data loading."""

from datetime import datetime, time, timedelta

import pytest
from bs4 import BeautifulSoup

import build
from build import SWEDEN_TZ
from store import (
    Film,
    Movie,
    Screening,
    film_key,
    poster_key_for_film,
    write_films,
    write_movie,
    write_poster,
    write_screenings,
)
from store.version import (
    AudioKind,
    AudioVersion,
    ContentVersion,
    Language,
    Presentation,
    PresentationSystem,
    SubtitleVersion,
)

# sha256("okänd film 4")[:8] exceeds 2**63, so its negated synthetic id
# falls outside SQLite's signed 64-bit INTEGER range.
UNTITLED = "Okänd film 4"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(build, "DB_FILE", path)
    return path


def screening(**kwargs) -> Screening:
    defaults = {
        "tmdb_id": None,
        "date": datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=30),
        "time": time(18, 30),
        "ticket_url": "https://example.com/1",
        "cinema_name": "Bio",
        "city": "Stockholm",
    }
    return Screening(**{**defaults, **kwargs})


def movie(tmdb_id: int) -> Movie:
    return Movie.from_dict({"tmdb_id": tmdb_id, "title_sv": "Filmen"})


def test_load_data_ignores_synthetic_ids(db, tmp_path):
    write_screenings(
        [
            screening(title=UNTITLED, ticket_url="https://example.com/a"),
            screening(tmdb_id=42, ticket_url="https://example.com/b"),
        ],
        path=db,
    )
    write_movie(movie(42), path=db)

    sd = build._load_data(tmp_path / "out")

    assert len(sd.screenings) == 2
    assert sd.movies[42].title_sv == "Filmen"
    synthetic = [m for tmdb_id, m in sd.movies.items() if tmdb_id < 0]
    assert len(synthetic) == 1
    assert synthetic[0].title_sv == UNTITLED


def film(title: str, **kwargs) -> Film:
    defaults = {
        "key": film_key("bio_se", title),
        "source": "bio_se",
        "title": title,
        "overview": "Handling från biografen.",
        "runtime": 95,
        "poster_url": "https://bio.se/p.jpg",
    }
    return Film(**{**defaults, **kwargs})


def test_site_film_fills_title_only_screening(db, tmp_path):
    f = film(UNTITLED)
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"img", "image/jpeg", path=db)
    write_screenings([screening(title=UNTITLED, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert neg_id < 0
    assert sd.movies[neg_id].overview_sv == "Handling från biografen."
    assert sd.movies[neg_id].runtime == 95
    assert sd.poster_keys[neg_id] == poster_key_for_film(f.key)


def test_site_film_fills_gaps_in_tmdb_movie(db, tmp_path):
    f = film("Filmen")
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"img", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert sd.movies[42].overview_sv == "Handling från biografen."
    assert sd.movies[42].runtime == 95
    assert sd.poster_keys[42] == poster_key_for_film(f.key)


def test_tmdb_poster_wins_over_site_poster(db, tmp_path):
    f = film("Filmen")
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"site", "image/jpeg", path=db)
    write_poster(42, b"tmdb", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert sd.poster_keys[42] == "42"


def test_poster_url_skips_undecodable_image(db, tmp_path):
    f = film("Filmen")
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"not an image", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert build._poster_url(sd, 42) is None


def other_film(title: str, **kwargs) -> Film:
    return film(title, key=film_key("filmstaden_se", title), source="filmstaden_se", **kwargs)


def test_other_source_film_fills_title_only_screening(db, tmp_path):
    a = film(UNTITLED, overview="", runtime=None)
    b = other_film(UNTITLED, overview="Handling från annan kedja.")
    write_films([a, b], path=db)
    write_poster(poster_key_for_film(b.key), b"img", "image/jpeg", path=db)
    write_screenings([screening(title=UNTITLED, film_key=a.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].overview_sv == "Handling från annan kedja."
    assert sd.poster_keys[neg_id] == poster_key_for_film(b.key)


def test_other_source_film_supplies_poster_for_tmdb_movie(db, tmp_path):
    a = film("Filmen")
    b = other_film("Filmen")
    write_films([a, b], path=db)
    write_poster(poster_key_for_film(b.key), b"img", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, film_key=a.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert sd.poster_keys[42] == poster_key_for_film(b.key)


def test_tmdb_metadata_wins_over_pooled_films(db, tmp_path):
    a = film("Filmen", overview="Handling från biografen.")
    write_films([a], path=db)
    write_poster(poster_key_for_film(a.key), b"site", "image/jpeg", path=db)
    write_poster(42, b"tmdb", "image/jpeg", path=db)
    write_movie(
        Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "overview_sv": "Handling från TMDB."}),
        path=db,
    )
    write_screenings([screening(tmdb_id=42, film_key=a.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert sd.movies[42].overview_sv == "Handling från TMDB."
    assert sd.poster_keys[42] == "42"


def test_title_only_screening_without_film_key_matches_by_title(db, tmp_path):
    f = film(UNTITLED)
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"img", "image/jpeg", path=db)
    write_screenings([screening(title=UNTITLED)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].overview_sv == "Handling från biografen."
    assert sd.poster_keys[neg_id] == poster_key_for_film(f.key)


def test_source_with_more_showings_supplies_metadata(db, tmp_path):
    own = film(
        "Heart of the beast",
        key=film_key("nortic_se", "Heart of the beast"),
        source="nortic_se",
        overview="Eventuellt kvarvarande biljetter säljs vid entrén. Serviceavgift 15kr.",
    )
    other = other_film("Heart of the Beast", overview="Handling från distributören.")
    write_films([own, other], path=db)
    write_screenings([screening(title="Heart of the beast", film_key=own.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].title_sv == own.title
    assert sd.movies[neg_id].overview_sv == own.overview


def test_source_with_showings_outranks_unused_source(db, tmp_path):
    own = film(
        UNTITLED,
        key=film_key("zzz_se", UNTITLED),
        source="zzz_se",
        overview="Handling från egen källa.",
    )
    other = film(
        UNTITLED,
        key=film_key("aaa_se", UNTITLED),
        source="aaa_se",
        overview="Handling från annan källa.",
    )
    write_films([own, other], path=db)
    write_screenings([screening(title=UNTITLED, film_key=own.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].overview_sv == "Handling från egen källa."


def test_programme_synopsis_has_expand_toggle(db, tmp_path):
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "overview_sv": "Handling."}), path=db)
    write_screenings(
        [screening(tmdb_id=42, date=datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1))],
        path=db,
    )
    sd = build._load_data(tmp_path / "out")
    out = tmp_path / "out" / "index.html"
    build._write_programme(build._make_env(), sd, sd.screenings, title="T", breadcrumbs="", out_path=out, canonical="/")
    html = out.read_text()
    assert 'class="synopsis" id="synopsis-filmen"' in html
    assert 'data-more="filmen" aria-controls="synopsis-filmen"' in html
    assert "/i/synopsis.js?v=" in html


@pytest.mark.parametrize("cinema_count", [0, 1, 2])
def test_city_film_description_uses_local_schedule(db, tmp_path, cinema_count):
    synopsis = "En berättelse om en familj."
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "overview_sv": synopsis}), path=db)
    today = datetime.now(tz=SWEDEN_TZ).date()
    write_screenings(
        [
            screening(
                tmdb_id=42,
                cinema_name=f"Bio {i}",
                date=today + timedelta(days=1),
                ticket_url=f"https://example.com/{i}/{j}",
                time=time(18 + j),
            )
            for i in range(cinema_count)
            for j in range(2)
        ]
        + [screening(tmdb_id=42, cinema_name="Senare bio", date=today + timedelta(days=14))],
        path=db,
    )
    out = tmp_path / "out"
    sd = build._load_data(out)
    build._build_programme_pages(build._make_env(), sd)

    city_page = BeautifulSoup((out / "stad/stockholm/film/filmen/index.html").read_text(), "html.parser")
    description = city_page.find("meta", attrs={"name": "description"})["content"]
    assert "Filmen" in description
    assert "Stockholm" in description
    assert synopsis not in description
    if cinema_count:
        assert (
            f"Visas på {cinema_count} {'biograf' if cinema_count == 1 else 'biografer'} de närmaste två veckorna"
            in description
        )
        assert synopsis in city_page.get_text()
    else:
        assert "Inga visningar de närmaste två veckorna" in description
    assert city_page.find("meta", property="og:description")["content"] == description

    nationwide_page = BeautifulSoup((out / "film/filmen/index.html").read_text(), "html.parser")
    assert nationwide_page.find("meta", attrs={"name": "description"})["content"] == synopsis


def _blocks(db, tmp_path, screenings):
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen"}), path=db)
    write_screenings(screenings, path=db)
    sd = build._load_data(tmp_path / "out")
    days = build._compute_days(sd.screenings)
    return build._prepare_programme_blocks(sd, sd.screenings, days, city="Stockholm")


def test_formats_split_a_film_into_variant_blocks(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(tmdb_id=42, date=day, ticket_url="https://example.com/a"),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/b",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/c",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
        ],
    )
    assert {(b["film_title"], b["variant"]) for b in blocks} == {
        ("Filmen", "IMAX"),
        ("Filmen", ""),
    }
    assert len({b["film_id"] for b in blocks}) == 2


def test_language_labels_only_films_playing_in_several(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/a",
                version=ContentVersion(audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
            ),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/b",
                version=ContentVersion(audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
            ),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/c",
                version=ContentVersion(audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH}))),
            ),
        ],
    )
    assert {b["variant"]: b["mi"] for b in blocks} == {
        "Svenskt tal": "Svenskt tal",
        "Originalversion · Engelskt tal": "Engelskt tal",
    }


def test_language_and_subtitles_go_in_the_details_line(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/a",
                version=ContentVersion(
                    audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH})),
                    subtitles=SubtitleVersion(frozenset({Language.SWEDISH})),
                ),
            ),
            # Unknown language joins the film's only known one.
            screening(tmdb_id=42, date=day, ticket_url="https://example.com/b"),
        ],
    )
    assert [(b["variant"], b["mi"]) for b in blocks] == [("", "Engelskt tal • Svensk text")]


def test_variant_is_shown_beside_the_title(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen"}), path=db)
    write_screenings(
        [screening(tmdb_id=42, date=day, presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})))],
        path=db,
    )
    sd = build._load_data(tmp_path / "out")
    out = tmp_path / "out" / "index.html"
    build._write_programme(build._make_env(), sd, sd.screenings, title="T", breadcrumbs="", out_path=out, canonical="/")
    assert '<a href="/film/filmen/" title="Filmen">Filmen</a> <span class="film-variant">(IMAX)</span>' in (
        out.read_text()
    )


def test_variants_of_a_film_are_adjacent(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    write_movie(Movie.from_dict({"tmdb_id": 7, "title_sv": "Annan"}), path=db)
    blocks = _blocks(
        db,
        tmp_path,
        [
            *(screening(tmdb_id=42, date=day, ticket_url=f"https://example.com/a{i}") for i in range(3)),
            *(screening(tmdb_id=7, date=day, ticket_url=f"https://example.com/b{i}") for i in range(2)),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/c",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
        ],
    )
    assert [b["film_title"] for b in blocks] == ["Filmen", "Filmen", "Annan"]
    assert {b["variant"] for b in blocks[:2]} == {"", "IMAX"}


def test_unsubtitled_reads_ej_textad(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(
                tmdb_id=42,
                date=day,
                version=ContentVersion(
                    audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH})),
                    subtitles=SubtitleVersion(frozenset()),
                ),
            )
        ],
    )
    assert blocks[0]["mi"] == "Engelskt tal • Ej textad"
