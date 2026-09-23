"""Import festival programmes into the store."""

import argparse
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from store import Festival, FestivalScreening, read_festivals, write_festival

STOCKHOLM = "https://www.stockholmfilmfestival.se/"
PRISMA = "https://program.goteborgfilmfestival.se/"
PRISMA_API = "https://api.goteborgfilmfestival.se/api/"
CATEGORIES = {"Fiction": "Spelfilm", "Documentary": "Dokumentär"}
TZ = ZoneInfo("Europe/Stockholm")
FESTIVALS = [
    Festival(
        slug="stockholms-filmfestival",
        year=2026,
        name="Stockholms filmfestival",
        city="Stockholm",
        start="2026-11-11",
        end="2026-11-22",
        url=STOCKHOLM,
        source="stockholm",
    ),
    Festival(
        slug="goteborg-film-festival-prisma",
        year=2026,
        name="Göteborg Film Festival Prisma",
        city="Göteborg",
        start="2026-10-23",
        end="2026-10-31",
        url=PRISMA,
        source="prisma",
    ),
]
QUERY = """
query Programme($page: Int!) {
  products(search: "", pageSize: 100, currentPage: $page) {
    page_info { total_pages }
    items {
      uid name url_key url_suffix parent_url_key
      image { url }
      description { html }
      short_description { html }
      custom_attributes {
        attribute_metadata { code }
        entered_attribute_value { value }
        selected_attribute_options { attribute_option { label } }
      }
    }
  }
}
"""


def _attributes(product: dict) -> dict:
    attrs = {}
    for attr in product.get("custom_attributes", []):
        entered = (attr.get("entered_attribute_value") or {}).get("value")
        options = (attr.get("selected_attribute_options") or {}).get("attribute_option") or []
        attrs[attr["attribute_metadata"]["code"]] = entered or ", ".join(o["label"] for o in options)
    return attrs


def _text(value: dict | None) -> str:
    soup = BeautifulSoup((value or {}).get("html") or "", "html.parser")
    for element in soup(["style", "script"]):
        element.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def stockholm_screenings(products: list[dict], start: date, end: date) -> list[FestivalScreening]:
    screenings = {}
    by_key = {p["url_key"]: p for p in products}
    for product in products:
        attrs = _attributes(product)
        when = attrs.get("event_start_iso")
        # Festival sections distinguish programme screenings from other events.
        if not when or not attrs.get("sektion") or not product.get("parent_url_key"):
            continue
        begins = datetime.fromisoformat(when)
        begins = begins.replace(tzinfo=TZ) if begins.tzinfo is None else begins.astimezone(TZ)
        if not start <= begins.date() <= end:
            continue
        venue = attrs.get("event_location")
        if not venue:
            raise ValueError(f"Missing venue: {product['url_key']}")
        film = by_key.get(product["parent_url_key"], product)
        metadata = {**_attributes(film), **{key: value for key, value in attrs.items() if value}}
        runtime = int(metadata["length"]) if metadata.get("length") else None
        if runtime is not None and runtime <= 0:
            raise ValueError(f"Invalid runtime: {product['url_key']}")
        identifier = product["uid"]
        screenings[identifier] = {
            "id": identifier,
            "film_id": product["parent_url_key"],
            "title": attrs.get("filmtitle") or product["name"],
            "start": begins.isoformat(),
            "end": (begins + timedelta(minutes=runtime)).isoformat() if runtime else "",
            "venue": venue,
            "url": STOCKHOLM + product["url_key"] + (product.get("url_suffix") or ""),
            "language": attrs.get("language", ""),
            "subtitles": attrs.get("subtitles", ""),
            "film_url": STOCKHOLM + film["url_key"] + (film.get("url_suffix") or ""),
            "poster_url": (film.get("image") or {}).get("url", ""),
            "description": _text(film.get("description")) or _text(product.get("description")),
            "intro": _text(film.get("short_description")),
            "runtime": runtime,
            "genres": metadata.get("genre", ""),
            "sections": metadata.get("sektion", ""),
            "director": metadata.get("director", ""),
            "country": metadata.get("country", ""),
            "production_year": metadata.get("productionyear", ""),
        }
    return [FestivalScreening(**s) for s in sorted(screenings.values(), key=lambda s: (s["start"], s["id"]))]


def _markup(value: str | None) -> tuple[str, str]:
    """Split Prisma's mixed Markdown/HTML text into a bold lead and the rest."""
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value or "", flags=re.DOTALL)
    html = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", html)
    soup = BeautifulSoup(html, "html.parser")
    lead = soup.find(["b", "strong"])

    def text(node) -> str:
        return re.sub(r"\s+([.,;:!?])", r"\1", " ".join(node.get_text(" ", strip=True).split()))

    intro = ""
    if lead and not lead.find_previous(string=lambda t: t.strip()):
        intro = text(lead)
        lead.decompose()
    return intro, text(soup)


def _poster(images) -> str:
    if isinstance(images, str):
        images = json.loads(images) if images else {}
    images = images or {}
    return images.get("poster") or images.get("thumbnail") or ""


def _names(value) -> str:
    if isinstance(value, str):
        value = json.loads(value) if value.startswith("[") else [value]
    return ", ".join(v.title() for v in value or [] if v)


def prisma_screenings(
    documents: list[dict], details: dict[str, dict], start: date, end: date
) -> list[FestivalScreening]:
    """Film and short-film package screenings; details are keyed by event key."""
    screenings = {}
    for document in documents:
        # Happenings are workshops and events without film metadata.
        if document["type"] not in {"Movie", "Package"}:
            continue
        begins = datetime.fromisoformat(document["timeStart"]).astimezone(TZ)
        if not start <= begins.date() <= end:
            continue
        ends = datetime.fromisoformat(document["timeEnd"]).astimezone(TZ) if document.get("timeEnd") else None
        detail = details.get(document["eventKey"], {})
        intro, description = _markup(detail.get("description"))
        if document["type"] == "Movie":
            film_url = PRISMA + "program/" + document["uniqueTitle"]
        else:
            film_url = PRISMA + "paket/" + document["eventKey"]
        directors = [
            " ".join(filter(None, (c.get("firstname"), c.get("surname"))))
            for c in detail.get("crew") or []
            if c.get("crewType") == "director"
        ]
        category = detail.get("category") or ""
        package = document["type"] == "Package"
        identifier = str(document["id"])
        screenings[identifier] = {
            "id": identifier,
            "film_id": document["uniqueTitle"],
            "title": document["title"],
            "start": begins.isoformat(),
            "end": ends.isoformat() if ends and ends > begins else "",
            "venue": document["location"],
            "url": film_url,
            "language": _names(detail.get("language")),
            "subtitles": detail.get("subtitles") or "",
            "film_url": film_url,
            "poster_url": _poster(document.get("imageUrl")) or _poster(detail.get("imageUrl")),
            "description": description,
            "intro": intro,
            "runtime": document.get("length") or detail.get("length") or None,
            "genres": ", ".join(detail.get("genres") or []) or CATEGORIES.get(category, category),
            "sections": ", ".join(detail.get("sections") or []) or ("Kortfilmer" if package else ""),
            "director": ", ".join(directors),
            "country": _names(detail.get("originCountry")),
            "production_year": detail.get("releaseYear") or "",
        }
    return [FestivalScreening(**s) for s in sorted(screenings.values(), key=lambda s: (s["start"], s["id"]))]


def _get(session: requests.Session, url: str, **params):
    response = session.get(url, params=params, timeout=60)
    response.raise_for_status()
    result = response.json()
    if result.get("errors"):
        raise ValueError(result["errors"])
    return result["result"]


def fetch_stockholm(session: requests.Session, start: date, end: date) -> list[FestivalScreening]:
    products = []
    page = 1
    while True:
        response = session.get(
            STOCKHOLM + "graphql",
            params={"query": QUERY, "variables": json.dumps({"page": page})},
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errors"):
            raise ValueError(result["errors"])
        catalogue = result["data"]["products"]
        products.extend(catalogue["items"])
        if page >= catalogue["page_info"]["total_pages"]:
            break
        page += 1
    return stockholm_screenings(products, start, end)


def fetch_prisma(session: requests.Session, start: date, end: date) -> list[FestivalScreening]:
    documents = []
    for offset in range((end - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        documents.extend(
            _get(session, PRISMA + "api/tableau/schedule", dayOfSearch=day, offset=0, size=500)["documents"]
        )
    details = {}
    for document in documents:
        key = document["eventKey"]
        if key in details or document["type"] not in {"Movie", "Package"}:
            continue
        if document["type"] == "Movie":
            details[key] = _get(session, PRISMA_API + f"Movies/{key}")
        else:
            details[key] = _get(session, PRISMA_API + f"OccasionEvents/{key}")
    return prisma_screenings(documents, details, start, end)


SOURCES = {"stockholm": fetch_stockholm, "prisma": fetch_prisma}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", help="festival slugs; all when omitted")
    args = parser.parse_args()
    stored = {(f.slug, f.year): screenings for f, screenings in read_festivals()}
    with requests.Session() as session:
        for festival in FESTIVALS:
            if args.slugs and festival.slug not in args.slugs:
                continue
            screenings = SOURCES[festival.source](
                session, date.fromisoformat(festival.start), date.fromisoformat(festival.end)
            )
            if not screenings and stored.get((festival.slug, festival.year)):
                raise ValueError(f"{festival.name}: empty programme; preserving stored screenings")
            write_festival(festival, screenings)
            print(f"{festival.name} {festival.year}: {len(screenings)} screenings")


if __name__ == "__main__":
    main()
