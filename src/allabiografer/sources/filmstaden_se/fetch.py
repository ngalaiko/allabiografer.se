"""Capture the cinema API programme and film details for Stockholm."""

from allabiografer.sources.filmstaden_se.site import _API

from ...schedule import checked
from .._shared import capture_json


def venue_id(ncg_id):
    return ncg_id.lower()


def fetch_pages(session, inputs, today, *, selectors=None):
    cinemas = capture_json(session, f"{_API}/cinema/sv/1/1024", inputs / "cinemas.json")
    films = set()
    checked(selectors, {venue_id(cinema["ncgId"]) for cinema in cinemas["items"]})
    for cinema in cinemas["items"]:
        if selectors is not None and venue_id(cinema["ncgId"]) not in selectors:
            continue
        city = ((cinema.get("address") or {}).get("city") or {}).get("name")
        if not city or cinema["ncgId"] in {"NCG26999", "NCG12567"}:
            continue
        cinema_id = cinema["ncgId"]
        page = 1
        while True:
            result = capture_json(
                session,
                f"{_API}/show/sv/{page}/1024",
                inputs / f"shows-{cinema_id}-{page}.json",
                params={"CinemaNcgId": cinema_id},
            )
            films.update(m["ncgId"] for s in result["items"] if (m := s.get("movie")) and m.get("ncgId"))
            if len(result["items"]) < 1024 or page * 1024 >= result["totalNbrOfItems"]:
                break
            page += 1
    for movie in sorted(films):
        capture_json(session, f"{_API}/movie/sv/{movie}", inputs / f"movie-{movie}.json")
