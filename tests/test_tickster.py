"""Tickster organiser listings, event pages and showing lookup."""

from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests

from parse.parsers import _tickster

_FIXTURES = Path(__file__).parent / "fixtures" / "tickster"
_ORGANISER = (_FIXTURES / "organiser.html").read_text()
_PAGE2 = (_FIXTURES / "organiser_page2.html").read_text()
_EVENT = (_FIXTURES / "event.html").read_text()
_MATINEE = (_FIXTURES / "event_matinee.html").read_text()
_EVENING = (_FIXTURES / "event_evening.html").read_text()

_TZ = ZoneInfo("Europe/Stockholm")
_BY = "https://www.tickster.com/se/sv/events/by/f1rd9l09v0b7xdv/soderkopings-bio"
_MATINEE_URL = "https://www.tickster.com/se/sv/events/c07puyr3fdybd2e/2026-10-07/resan-till-piemonte-dagbio-sv-txt"
_EVENING_URL = "https://www.tickster.com/se/sv/events/mynrz5ej8n8gpee/2026-10-07/resan-till-piemonte-sv-txt"


class _Session:
    """Serves fixture pages by URL; anything else fails like a dead link."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        if url not in self.pages:
            raise requests.ConnectionError(url)
        return SimpleNamespace(text=self.pages[url], raise_for_status=lambda: None)


def test_listing_reads_one_event_per_card_and_the_next_page():
    events, following = _tickster.listing(_ORGANISER)

    assert [(e.title, e.date, e.venue) for e in events] == [
        ("PROGRAM", date(2026, 4, 20), "Söderköpings Bio"),
        ("Avengers: Endgame Encore (Sv. txt)", date(2026, 10, 4), "Söderköpings Bio"),
        ("Resan till Piemonte (Dagbio) (Sv. txt)", date(2026, 10, 7), "Söderköpings Bio"),
        ("Tony (Dagbio) (Sv. txt)", date(2026, 10, 7), "Söderköpings Bio"),
        ("Resan till Piemonte (Sv. txt)", date(2026, 10, 7), "Söderköpings Bio"),
    ]
    assert events[2].url == _MATINEE_URL
    assert events[2].start is None
    assert following == _BY + "?skip=24&take=24"


def test_listing_venue_drops_the_city():
    events, following = _tickster.listing(_PAGE2)

    assert events[0].venue == "Hallunda Folkets Hus - Brage"
    assert following == ""


def test_event_page_carries_start_title_and_venue():
    event = _tickster.event(_EVENT)

    assert event == _tickster.Event(
        url="https://www.tickster.com/se/sv/events/yv4regw62zvaunz/2026-10-14/digger-tal-engelska-text-svenska",
        title="Digger (Tal: Engelska) (Text: Svenska)",
        date=date(2026, 10, 14),
        venue="Hallunda Folkets Hus - Brage",
        start=datetime(2026, 10, 14, 13, 0, tzinfo=_TZ),
    )


def test_version_reads_spoken_and_subtitle_tags():
    assert _tickster.version("Digger (Tal: Engelska) (Text: Svenska)") == ("Digger", "Engelskt tal", "Svensk text")
    assert _tickster.version("Fjord (Sv. txt)") == ("Fjord", "", "Svensk text")
    assert _tickster.version("Bortglömda ön (Sv. tal)") == ("Bortglömda ön", "Svenskt tal", "")


def test_version_reads_tags_cut_off_by_the_title_limit():
    assert _tickster.version("Sense and Sensibility  (Tal: Engelska) (Text: Sven") == (
        "Sense and Sensibility",
        "Engelskt tal",
        "Svensk text",
    )


def test_programme_follows_pages():
    session = _Session({_BY: _ORGANISER, _BY + "?skip=24&take=24": _PAGE2})

    programme = _tickster.Programme.fetch(_BY, session)

    assert len(programme.events) == 6


def test_programme_lookup_failure_leaves_it_empty():
    programme = _tickster.Programme.fetch(_BY, _Session({}))

    assert programme.events == []
    assert programme.find("Tony", date(2026, 10, 7), time(15, 30)) is None


def test_find_matches_a_lone_showing_by_date_and_title():
    session = _Session({})
    programme = _tickster.Programme(_tickster.listing(_ORGANISER)[0], session)

    found = programme.find("Avengers: Endgame Encore", date(2026, 10, 4), time(14, 0))

    assert found.url.endswith("/94djmvtwe7g13mp/2026-10-04/avengers-endgame-encore-sv-txt")
    assert session.requested == []


def test_find_ignores_other_dates_and_titles():
    programme = _tickster.Programme(_tickster.listing(_ORGANISER)[0], _Session({}))

    assert programme.find("Avengers: Endgame Encore", date(2026, 10, 5), time(14, 0)) is None
    assert programme.find("Fjord", date(2026, 10, 4), time(18, 30)) is None


def test_find_reads_start_times_to_tell_same_day_showings_apart():
    session = _Session({_MATINEE_URL: _MATINEE, _EVENING_URL: _EVENING})
    programme = _tickster.Programme(_tickster.listing(_ORGANISER)[0], session)

    evening = programme.find("Resan till Piemonte", date(2026, 10, 7), time(18, 30))
    matinee = programme.find("Resan till Piemonte", date(2026, 10, 7), time(13, 0))

    assert evening.url == _EVENING_URL
    assert matinee.url == _MATINEE_URL
    assert sorted(session.requested) == sorted([_MATINEE_URL, _EVENING_URL])


def test_find_gives_up_when_start_times_are_unreadable():
    programme = _tickster.Programme(_tickster.listing(_ORGANISER)[0], _Session({}))

    assert programme.find("Resan till Piemonte", date(2026, 10, 7), time(18, 30)) is None


def test_find_matches_titles_tickster_extends_or_capitalises_differently():
    events = [
        _tickster.Event(
            url="https://www.tickster.com/se/sv/events/370ycv26ht5bcbb/2026-10-17/macbeth",
            title="Macbeth - Live på bio från Metropolitan",
            date=date(2026, 10, 17),
            venue="",
        )
    ]
    programme = _tickster.Programme(events, _Session({}))

    assert programme.find("MACBETH", date(2026, 10, 17), time(19, 0)) == events[0]


def test_fetch_event_failure_is_none():
    assert _tickster.fetch_event(_EVENING_URL, _Session({})) is None
    assert _tickster.fetch_event(_EVENING_URL, _Session({_EVENING_URL: _EVENING})).start == datetime(
        2026, 10, 7, 18, 30, tzinfo=_TZ
    )


def test_find_matches_titles_tickster_cut_mid_word():
    events = [
        _tickster.Event(
            url="https://www.tickster.com/se/sv/events/abc/2026-10-25/lilla-spoket-laban",
            title="Lilla spöket Laban och den förtrollade borgens hemlig",
            date=date(2026, 10, 25),
            venue="",
        )
    ]
    programme = _tickster.Programme(events, _Session({}))

    assert (
        programme.find("Lilla spöket Laban och den förtrollade borgens hemligheter", date(2026, 10, 25), time(14, 0))
        == events[0]
    )
    assert programme.find("Lilla spöket Laban", date(2026, 10, 25), time(14, 0)) == events[0]
    assert programme.find("Lilla spöket", date(2026, 10, 25), time(14, 0)) == events[0]


def test_find_ignores_short_titles_that_merely_share_a_word_stem():
    events = [_tickster.Event(url="u", title="Tony (Sv. txt)", date=date(2026, 10, 7), venue="")]
    programme = _tickster.Programme(events, _Session({}))

    assert programme.find("Tonya", date(2026, 10, 7), time(15, 30)) is None


def test_labels_are_the_programme_tags_besides_the_version():
    assert _tickster.labels("Resan till Piemonte (Dagbio) (Sv. txt)") == ("Dagbio",)
    assert _tickster.labels("Digger (Tal: Engelska) (Text: Svenska)") == ()
    assert _tickster.labels("Sense and Sensibility  (Tal: Engelska) (Text: Sven") == ()
