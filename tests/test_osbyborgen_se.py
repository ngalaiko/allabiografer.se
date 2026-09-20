"""osbyborgen.se session blob and film page extraction."""

from pathlib import Path

from parse.parsers.osbyborgen_se import _detail, _film, _runtime, _sessions

_FIXTURES = Path(__file__).parent / "fixtures" / "osbyborgen_se"
_INDEX = (_FIXTURES / "index.html").read_text()
_FILM = (_FIXTURES / "film-314.html").read_text()


def test_sessions_read_the_schedule_blob():
    sessions = _sessions(_INDEX)
    assert [s["f_title"] for s in sessions] == [
        "Fåret Shaun och monstret på bondgården",
        "STORA BIODAGEN",
        "Practical Magic: Family Legacy",
    ]


def test_film_merges_the_film_page_into_the_session():
    film = _film(_sessions(_INDEX)[0], _detail(_FILM))
    assert film.key == "osbyborgen_se:fåret shaun och monstret på bondgården"
    assert film.source == "osbyborgen_se"
    assert film.runtime == 81
    assert film.age_rating == "Barntillåten"
    assert film.genres == ["Animerad familjefilm"]
    assert film.overview.startswith("I den tredje biofilmen om fåret Shaun")
    assert "<p>" not in film.overview
    assert film.poster_url == "https://osbyborgen.se/km/file/_event/haunthesheep_1080x1350_some_se_1.jpg"
    assert film.url == "https://osbyborgen.se/?pg=6&film=314"


def test_film_falls_back_to_the_session_when_the_film_page_is_missing():
    film = _film(_sessions(_INDEX)[2], {})
    assert film.genres == ["Komedi", "Drama", "Romantik"]
    assert film.poster_url == "https://osbyborgen.se/km/file/_event_combinedImage/315.jpeg"
    assert (film.overview, film.runtime, film.age_rating) == ("", None, "")


def test_runtime_reads_both_length_formats():
    assert _runtime("1 tim 21") == 81
    assert _runtime("2:10") == 130
    assert _runtime("2 tim") == 120
    assert _runtime(0) is None
    assert _runtime("") is None


def test_detail_returns_nothing_for_a_page_without_the_blob():
    assert _detail("<html></html>") == {}
