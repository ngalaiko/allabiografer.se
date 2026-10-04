"""palladiumbio.se title annotations and program rows."""

from datetime import date, time
from pathlib import Path

import pytest

from parse.parsers.palladiumbio_se import _hero, _overview, _parse_title, _poster, _posters, _showtimes

pytestmark = pytest.mark.usefixtures("parser_clock")

_FIXTURES = Path(__file__).parent / "fixtures" / "palladiumbio_se"
_HTML = (_FIXTURES / "program.html").read_text()


def test_parse_title_reads_txt_abbreviation_for_subtitles():
    assert _parse_title("Practical Magic: Family Legacy  (Tal: Eng)(Txt:Sv)") == (
        "Practical Magic: Family Legacy",
        "Engelskt tal",
        "Svensk text",
    )


def test_parse_title_reads_tal_and_text_variants():
    assert _parse_title("Superhunden Charlie  (Tal: Sve)(Text:Sve)") == (
        "Superhunden Charlie",
        "Svenskt tal",
        "Svensk text",
    )
    assert _parse_title("BIODLAREN (Tal:Sv) (Tex:Sv)") == ("BIODLAREN", "Svenskt tal", "Svensk text")
    assert _parse_title("Köln 75  (Tal: Svenska (dubbat))") == ("Köln 75", "Svenskt tal", "")


def test_showtimes_read_rows_under_each_date_header():
    assert [(f.title, *rest) for f, *rest in _showtimes(_HTML)] == [
        (
            "Bortglömda ön",
            date(2026, 9, 20),
            time(16, 30),
            "https://secure.tickster.com/ncz24uvkek7dwtf",
            "Salong 1",
            "Svenskt tal",
            "Svensk text",
            ("SMYGPREMIÄR!", "(Tal: Sve)", "(Text: Sve)"),
        ),
        (
            "Superhunden Charlie",
            date(2026, 9, 20),
            time(16, 45),
            "https://secure.tickster.com/dj1t13vvferte1v",
            "Salong 2",
            "Svenskt tal",
            "Svensk text",
            ("(Tal: Sve)", "(Text:Sve)"),
        ),
        (
            "Practical Magic: Family Legacy",
            date(2026, 9, 20),
            time(19, 0),
            "https://secure.tickster.com/ycryyrnewwt7hna",
            "Salong 2",
            "Engelskt tal",
            "Svensk text",
            ("(Tal: Eng)", "(Txt:Sv)"),
        ),
        (
            "Heart of the Beast",
            date(2026, 9, 20),
            time(19, 15),
            "https://secure.tickster.com/tpp9nuxffryy72t",
            "Salong 1",
            "Engelskt tal",
            "Svensk text",
            ("SMYGPREMIÄR", "(Tal: Eng)", "(Text: Sve)"),
        ),
    ]


def test_showtimes_link_each_row_to_its_event_page():
    film = next(f for f, *_ in _showtimes(_HTML))
    assert film.key == "palladiumbio_se:bortglömda ön"
    assert film.source == "palladiumbio_se"
    assert film.url == "https://palladiumbio.se/film.html?event=ncz24uvkek7dwtf"
    # The program carries no poster, length, genre or rating.
    assert (film.poster_url, film.runtime, film.genres, film.age_rating) == ("", None, [], "")


def test_screenings_share_their_film_key():
    assert len({f.key for f, *_ in _showtimes(_HTML)}) == 4


def test_overview_reads_the_event_page_paragraphs():
    assert _overview((_FIXTURES / "film.html").read_text()) == (
        "Din bästa vän är värd att kämpa för. "
        "Från DreamWorks Animation kommer en glittrande och känslosam berättelse om två livslånga bästa vänner."
    )


@pytest.mark.parametrize(
    ("raw", "title"),
    [
        ("SMYGPREMIÄR! Bortglömda ön (Tal: Sve)", "Bortglömda ön"),
        ("SMYGPREMIÄRHeart of the Beast(Tal: Eng)", "Heart of the Beast"),
        ("Förhandsvisning: Tony (Tal: Eng)", "Tony"),
        ("BIO PASSET Digger (Tal: Eng)", "Digger"),
        ("BIODLAREN (Tal:Sv) (Tex:Sv)", "BIODLAREN"),
        ("Premiärdansen (Tal: Sve)", "Premiärdansen"),
        ("PREMIÄRDANSEN (Tal: Sve)", "PREMIÄRDANSEN"),
    ],
)
def test_parse_title_strips_programme_prefix(raw, title):
    assert _parse_title(raw)[0] == title


def test_carousel_posters_match_by_normalised_title():
    posters = _posters(_HTML)
    cache = "https://palladiumbio.se/assets/components/phpthumbof/cache/"
    assert (
        _poster(posters, "Bortglömda ön")
        == cache + "bortglomda-on-trio-digitalaffisch-1440x2160.39ff576fa2030515fbd6d88420f6038c.jpg"
    )
    assert _poster(posters, "Heart of the Beast").startswith(cache + "hotb-")
    # "DIGGER:BIO PASSET" carries a programme label after the colon.
    assert _poster(posters, "Digger").startswith(cache + "se-digger-")
    assert _poster(posters, "Nelly Rapp: Porten till underjorden").startswith(cache + "nellyrapp-")
    assert _poster(posters, "Practical Magic: Family Legacy") == ""


def test_hero_image_from_event_page():
    assert _hero((_FIXTURES / "film.html").read_text()) == (
        "https://palladiumbio.se/assets/components/tickster/cache/eventImages/ncz24uvkek7dwtf.jpg"
    )
