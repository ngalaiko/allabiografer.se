"""hallundafolketshus.se CaféBio event extraction."""

from datetime import date, time
from pathlib import Path

from parse.parsers import _films
from parse.parsers.hallundafolketshus_se import _SOURCE, _details, _events

_FIXTURES = Path(__file__).parent / "fixtures" / "hallundafolketshus_se"
_HTML = (_FIXTURES / "index.html").read_text()
_EVENT = (_FIXTURES / "event.html").read_text()
_UNRATED = (_FIXTURES / "event_unrated.html").read_text()


def test_events_link_to_their_own_event_page():
    events = list(_events(_HTML))

    assert events == [
        (
            "Autofiktion",
            date(2026, 9, 22),
            time(13, 0),
            "https://www.hallundafolketshus.se/events/autofiktion",
        ),
        (
            "Resan till Piemonte",
            date(2026, 9, 29),
            time(13, 0),
            "https://www.hallundafolketshus.se/events/resan-till-piemonte",
        ),
    ]


def test_event_page_carries_poster_genres_runtime_and_synopsis():
    details = _details(_EVENT)

    assert details["poster_url"] == (
        "https://www-static.hallundafolketshus.se/wp-content/uploads/2026/08/"
        "2026-09-22-Autofiktion_SE_1080x1920_Reviews-scaled.jpg"
    )
    assert details["genres"] == ["Drama"]
    assert details["runtime"] == 111
    assert details["overview"].startswith("Oscarsbelönade Pedro Almodóvar")


def test_details_make_a_film_the_screenings_key_matches():
    film = _films.make(
        _SOURCE, "Autofiktion", url="https://www.hallundafolketshus.se/events/autofiktion", **_details(_EVENT)
    )

    assert film.key == "hallundafolketshus_se:autofiktion"
    assert film.runtime == 111
    assert film.poster_url.endswith(".jpg")
    assert film.url == "https://www.hallundafolketshus.se/events/autofiktion"


def test_unset_age_rating_is_not_mistaken_for_metadata():
    details = _details(_UNRATED)

    assert details["age_rating"] == ""
    assert details["runtime"] is None
    assert details["genres"] == ["Drama", "Komedi", "Romantik"]
    assert details["overview"].startswith("Fyra vänner")
