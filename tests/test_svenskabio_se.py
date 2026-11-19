from types import SimpleNamespace

import pytest

from parse.parsers import svenskabio_se
from store import Film, Screening
from store.version import Language


def _card(id, day, hall):
    c = "em-block-showtime-movie-card"
    return f'''<article class="{c}" data-showtime-id="{id}_sv">
      <a class="{c}__card-link" href="https://svenskabio.se/secure-redirect/?url=https://biljetter.svenskabio.se/seat-plan/{id}"></a>
      <time class="{c}__time" datetime="{day}T18:30:00+01:00">18:30</time>
      <span class="{c}__screen">{hall}</span>
      <h2 class="{c}__title"><a href="https://svenskabio.se/filmer/example/">Example</a></h2>
      <span class="{c}__meta-item">1:47</span>
      <span class="{c}__label"><span class="screen-reader-text">Tal:</span>
        <span class="{c}__label-text">En</span></span>
      <span class="{c}__label"><span class="screen-reader-text">Text:</span>
        <span class="{c}__label-text">Sv</span></span>
      <div class="{c}__availability"><span>Slutsålt</span></div>
    </article>'''


def test_operator_programme_walks_dates_and_keeps_simultaneous_shows(monkeypatch):
    first, second = "2026-11-19", "2026-11-21"
    responses = {
        "all": {
            "date": first,
            "dateOptions": [{"value": x} for x in ("all", first, second)],
            "html": _card(3145, first, "Salong 2") + _card(3146, first, "Salong 7"),
        },
        second: {"date": second, "html": _card(3314, second, "Salong 8")},
    }

    programmes = {
        (4, 3): responses,
        (5, 4): {"all": {"date": second, "dateOptions": [{"value": second}], "html": _card(4120, second, "Salong 6")}},
    }

    def get(_url, *, params, timeout):
        payload = programmes[params["cityId"], params["cinemaIds"]][params["date"]]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr(svenskabio_se._http, "session", lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(svenskabio_se, "lookup", lambda *args, **kwargs: None)
    rows = list(svenskabio_se.parse())
    shows = [row for row in rows if isinstance(row, Screening)]
    assert [(s.cinema_name, str(s.date), s.screen, s.ticket_url) for s in shows] == [
        ("Biostaden Eskilstuna", first, "Salong 2", "https://biljetter.svenskabio.se/seat-plan/3145"),
        ("Biostaden Eskilstuna", first, "Salong 7", "https://biljetter.svenskabio.se/seat-plan/3146"),
        ("Biostaden Eskilstuna", second, "Salong 8", "https://biljetter.svenskabio.se/seat-plan/3314"),
        ("Biostaden Uddevalla", second, "Salong 6", "https://biljetter.svenskabio.se/seat-plan/4120"),
    ]
    assert shows[0].version.audio.languages == {Language.ENGLISH}
    assert shows[0].version.subtitles.languages == {Language.SWEDISH}
    assert shows[0].raw_attributes == ("Slutsålt",)
    (film,) = [row for row in rows if isinstance(row, Film)]
    assert film.runtime == 107

    responses[second]["date"] = first
    with pytest.raises(ValueError, match="missing advertised programme"):
        list(svenskabio_se.parse())
