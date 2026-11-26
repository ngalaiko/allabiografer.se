"""Capture the bio.se venues and programmes assigned to it in Stockholm."""

from allabiografer.sources.bio_se.site import _API, _OTHER_PROGRAMME_IDS, _venue

from ...schedule import checked
from .._shared import capture_json

DISTRICTS = {"Älvsjö", "Årsta", "Bromma", "Hägersten", "Johanneshov", "Kista", "Skärholmen"}
OTHER_PROGRAMME_IDS = _OTHER_PROGRAMME_IDS | {2407, 2411, 2065}  # Bio Roy, Vingen, and Spegeln.


def programme_city(venue):
    if venue.city in {"Angered", "Torslanda", "Västra Frölunda"}:
        return "Göteborg"
    return "Stockholm" if venue.city in DISTRICTS else venue.city


def venue_id(cinema_id):
    return str(cinema_id)


def fetch_pages(session, inputs, today, *, selectors=None):
    session.headers["Accept"] = "application/json"
    payload = capture_json(session, f"{_API}/cinemas", inputs / "cinemas.json")
    checked(selectors, {venue_id(cinema["id"]) for cinema in payload["cinemas"]})
    for cinema in payload["cinemas"]:
        if selectors is not None and venue_id(cinema["id"]) not in selectors:
            continue
        venue = _venue(cinema)
        if (
            venue is None
            or cinema["id"] in OTHER_PROGRAMME_IDS
            or venue.name in {"Stockholm Bio Aspen", "Stockholm Bio Fågel Blå", "Stockholm Bio Rio", "Biocafé Tellus"}
        ):
            continue
        capture_json(
            session, f"{_API}/cinemas/films", inputs / f"programme-{cinema['id']}.json", body={"cinemaId": cinema["id"]}
        )
