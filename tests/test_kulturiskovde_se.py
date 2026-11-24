from datetime import date, time

import requests

from parse.parsers.kulturiskovde_se import parse
from store import Film, Screening, Venue


def test_odeon_publishes_only_public_film_series_rows(monkeypatch):
    base = "https://tix.se/sv/skovde/buyingflow/tickets/"
    children = """<table>
    <tr class="event-select" data-pro="Sk&#246;vde Kulturhus">
      <td class="name">Bajsfilmen </td><td class="location">Odeon</td>
      <td class="date">fre 20 nov 2026</td><td class="time">10:00</td></tr>
    <tr class="event-select" data-pro="Sk&#246;vde Kulturhus">
      <td class="name">Konsert</td><td class="location">Valhall</td>
      <td class="date">fre 20 nov 2026</td><td class="time">19:00</td></tr>
    <tr class="event-select" data-pro="Skövde Filmstudio">
      <td class="name">Christy</td><td class="location">Odeon</td>
      <td class="date">lör 21 nov 2026</td><td class="time">15:00</td></tr>
    </table>"""
    day = """<table><tr class="event-select" data-pro="Sk&#246;vde Kulturhus">
      <td class="name">Diktatorns tårta</td><td class="location">Odeon</td>
      <td class="date">tis 24 nov 2026</td><td class="time">14:00</td></tr></table>"""
    pages = {base + "31841/": children, base + "31784/": day}

    def get(session, url, *, timeout):
        response = requests.Response()
        response.status_code = 200
        response._content = pages[url].encode()
        return response

    monkeypatch.setattr(requests.Session, "get", get)

    items = list(parse())
    venue = next(item for item in items if isinstance(item, Venue))
    assert (venue.city, venue.name) == ("Skövde", "Biograf Odeon")
    assert {item.title for item in items if isinstance(item, Film)} == {"Bajsfilmen", "Diktatorns tårta"}
    shows = [item for item in items if isinstance(item, Screening)]
    assert [(s.title, s.date, s.time, s.screen, s.ticket_url) for s in shows] == [
        ("Bajsfilmen", date(2026, 11, 20), time(10), "Odeon", base + "31841/"),
        ("Diktatorns tårta", date(2026, 11, 24), time(14), "Odeon", base + "31784/"),
    ]
