"""palladiumbio.se title annotations and program rows."""

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from parse.parsers import palladiumbio_se
from parse.parsers.palladiumbio_se import _hero, _overview, _parse_title, _poster, _posters, _showtimes
from store import Film, Screening
from store.version import Language

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


_CARDS = """<div class="multiCarousel">{}</div>"""
_CARD = """<div class="card"><img src="/{src}.jpg"><p class="card-title">{title}</p></div>"""


def _cards(*titles: str):
    return _posters(_CARDS.format("".join(_CARD.format(src=t.lower(), title=t) for t in titles)))


def test_carousel_poster_matches_title_before_colon():
    posters = _cards("SMÅSTADSLIV")
    title = "Småstadsliv: Mellan himmel och körtburkar"
    assert _poster(posters, title, [title]) == "https://palladiumbio.se/småstadsliv.jpg"


def test_title_before_colon_shared_by_two_films_matches_neither():
    posters = _cards("SPIDER-MAN")
    titles = ["Spider-Man: Brand New Day", "Spider-Man: Across the Spider-Verse"]
    assert [_poster(posters, t, titles) for t in titles] == ["", ""]


def test_title_before_colon_does_not_match_another_cards_prefix():
    # "NELLY RAPP:PORTEN TILL UNDERJORDEN" names one sequel, not the series.
    title = "Nelly Rapp: Spökagenten"
    assert _poster(_cards("NELLY RAPP:PORTEN TILL UNDERJORDEN"), title, [title]) == ""


def test_exact_match_wins_over_title_before_colon():
    posters = _cards("DUNE", "DUNE: PART THREE")
    title = "Dune: Part Three"
    assert _poster(posters, title, [title]) == "https://palladiumbio.se/dune: part three.jpg"


class _Session:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=self.pages[url], ok=True, raise_for_status=lambda: None)


def _parse(monkeypatch, pages: dict[str, str]) -> list:
    monkeypatch.setattr(palladiumbio_se._http, "session", lambda *a: _Session(pages))
    monkeypatch.setattr(palladiumbio_se._films, "register", lambda film, session=None: film)
    monkeypatch.setattr(palladiumbio_se, "_tmdb", lambda title: None)
    return list(palladiumbio_se.parse())


def test_film_page_failure_skips_only_its_details(monkeypatch):
    film_page = (_FIXTURES / "film.html").read_text()
    items = _parse(
        monkeypatch, {palladiumbio_se._URL: _HTML, "https://palladiumbio.se/film.html?event=ycryyrnewwt7hna": film_page}
    )
    films = {f.title: f for f in items if isinstance(f, Film)}
    assert len(films) == 4
    assert films["Practical Magic: Family Legacy"].overview.startswith("Din bästa vän")
    assert films["Bortglömda ön"].overview == ""
    assert len([i for i in items if isinstance(i, Screening)]) == 4


def test_non_swedish_audio_is_original_language(monkeypatch):
    films = {f.title: f for f in _parse(monkeypatch, {palladiumbio_se._URL: _HTML}) if isinstance(f, Film)}
    assert films["Practical Magic: Family Legacy"].original_languages == frozenset({Language.ENGLISH})
    assert films["Heart of the Beast"].original_languages == frozenset({Language.ENGLISH})
    # Swedish audio alone may be a dub.
    assert films["Bortglömda ön"].original_languages == frozenset()


def test_rows_under_an_invalid_date_are_skipped(caplog):
    html = _HTML.replace("Söndag 20 september", "Torsdag 31 september")
    assert list(_showtimes(html)) == []
    assert "31 september" in caplog.text


_BUY = (
    '<a class="btn btn-primary btn-sm" href="https://secure.tickster.com/dj1t13vvferte1v"'
    ' rel="noopener" target="_blank">\n      <i class="fa-solid fa-ticket pe-1">\n      </i>'
    "\n      Biljetter\n     </a>"
)


def test_row_without_a_buy_button_links_its_event_page():
    assert _BUY in _HTML
    rows = {f.title: rest for f, *rest in _showtimes(_HTML.replace(_BUY, ""))}
    assert len(rows) == 4
    assert rows["Superhunden Charlie"][2] == "https://palladiumbio.se/film.html?event=dj1t13vvferte1v"
