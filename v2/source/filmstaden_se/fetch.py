"""Capture the cinema API programme and film details for Stockholm."""

from parse.parsers.filmstaden_se import _API

from .._shared import capture_json, fetch_cities_main


def fetch_pages(session, inputs, cities):
    cinemas = capture_json(session, f"{_API}/cinema/sv/1/1024", inputs / "cinemas.json")
    films = set()
    for cinema in cinemas["items"]:
        city = ((cinema.get("address") or {}).get("city") or {}).get("name")
        if not city or (cities and city not in cities) or cinema["ncgId"] in {"NCG26999", "NCG12567"}:
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


if __name__ == "__main__":
    fetch_cities_main("filmstaden_se", fetch_pages)
