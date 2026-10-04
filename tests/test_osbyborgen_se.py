"""osbyborgen.se session blob and film page extraction."""

from pathlib import Path

from parse.parsers.osbyborgen_se import _detail, _film, _label_facts, _runtime, _sessions
from store.version import Language

_FIXTURES = Path(__file__).parent / "fixtures" / "osbyborgen_se"
_INDEX = (_FIXTURES / "index.html").read_text()
_LABELS = (_FIXTURES / "labels.html").read_text()
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
    assert _runtime("1 tim 30 min") == 90
    assert _runtime("2 h inkl p") == 120
    assert _runtime("1 h 45 min") == 105
    assert _runtime("105 min") == 105
    assert _runtime(111) == 111
    assert _runtime(0) is None
    assert _runtime("") is None


def test_detail_returns_nothing_for_a_page_without_the_blob():
    assert _detail("<html></html>") == {}


def test_sessions_skip_live_events():
    titles = [s["f_title"] for s in _sessions(_LABELS)]
    assert "Kvinnor och äppelträd" not in titles
    assert "A night at the movies" not in titles
    assert "Julkonsert" not in titles
    # Recorded concerts are listed as films.
    assert any(t.startswith("André Rieu") for t in titles)


def _facts(title: str) -> dict:
    sess = next(s for s in _sessions(_LABELS) if s["f_title"] == title)
    return _label_facts(sess.get("f_label"))


def test_label_language_sets_audio():
    assert _facts("Bortglömda ön")["version"].audio.languages == {Language.SWEDISH}
    assert _facts("Kärlek över Tanger")["version"].audio.languages == {Language.SPANISH}
    assert _facts("Min kära")["version"].audio.languages == {Language.NORWEGIAN}


def test_label_is_kept_as_raw_attribute():
    assert _facts("Kärlek över Tanger")["raw_attributes"] == ("dagbio på spanska",)
    assert _facts("Resan till Piemonte")["raw_attributes"] == ("Biopasset",)
    assert _facts("Sense and Sensibility")["raw_attributes"] == ()
    assert not _facts("Resan till Piemonte")["version"].audio.languages


def test_label_drops_schedule_notes():
    assert _facts("Fåret Shaun och monstret på bondgården")["raw_attributes"] == ()


_SHAUN = (
    "<p>I den tredje biofilmen om f&aring;ret Shaun.</p>\r\n"
    "<p>N&auml;r Shaun <em>f&ouml;rvandlas</em> g&aring;r det fort.</p>\r\n"
    "<p>Pressansvarig och kontakt f&ouml;r materialfr&aring;gor: Mona Holmquist MonaH@scanbox.com 0701-857612.</p>\r\n"
    "<p>Distributionsansvarig (kontakt f&ouml;r filmbokning) Andreas Degerhammar "
    "andreasd@scanbox.com 070-761 38 05.</p>"
)


def test_overview_keeps_paragraphs_and_stops_at_distributor_contacts():
    film = _film(_sessions(_INDEX)[0], {"f_synopsis": _SHAUN})
    assert film.overview == "I den tredje biofilmen om fåret Shaun.\n\nNär Shaun förvandlas går det fort."


def test_overview_drops_a_trailing_contact_line():
    film = _film(_sessions(_INDEX)[0], _detail(_FILM))
    assert "Distributionsansvarig" not in film.overview


def test_genres_drop_the_catch_all_and_nationality():
    sess = _sessions(_INDEX)[0]
    assert _film(sess, {"f_genre": "Film"}).genres == []
    assert _film(sess, {"f_genre": "Spanskt drama"}).genres == ["Drama"]
    assert _film(sess, {"f_genre": "Norskt Drama"}).genres == ["Drama"]
    assert _film(sess, {"f_genre": "Romantisk komedi"}).genres == ["Romantisk komedi"]


def test_film_page_label_supplies_the_language_a_schedule_note_lacks():
    facts = _label_facts("Ny tid<br>\nkl 11.00", "på svenska")
    assert facts["version"].audio.languages == {Language.SWEDISH}
    assert facts["raw_attributes"] == ()
    assert _label_facts("dagbio<br>på spanska", "på svenska")["version"].audio.languages == {Language.SPANISH}
