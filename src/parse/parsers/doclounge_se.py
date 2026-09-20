"""doclounge.se — Doc Lounge documentary screenings, Next.js SSR with __NEXT_DATA__."""

import json
import logging
import re
from collections.abc import Iterator
from datetime import date, time
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup

from parse.parsers import _films
from parse.parsers._tmdb_cache import lookup as _tmdb
from store import Film, Screening, Venue

log = logging.getLogger(__name__)

_SOURCE = "doclounge_se"
_URL = "https://www.doclounge.se/events-screenings"
_FILM_URL = "https://www.doclounge.se/films/"

# Posters come from the WordPress media library at full size; the site's own
# Next.js image proxy scales them down.
_POSTER_PROXY = "https://www.doclounge.se/_next/image?url={url}&w=640&q=75"

# Doc Lounge screens documentaries only; the site tags topics, not genres.
_GENRES = ["Dokumentär"]

# Doc Lounge also operates in Finland, Norway and Denmark — those city terms are skipped.
_SWEDISH_CITIES = {
    "goteborg": "Göteborg",
    "helsingborg": "Helsingborg",
    "kalmar": "Kalmar",
    "landskrona": "Landskrona",
    "lund": "Lund",
    "malmo": "Malmö",
    "ostersund": "Östersund",
    "sjobo": "Sjöbo",
    "stockholm": "Stockholm",
    "sundsvall": "Sundsvall",
    "umea": "Umeå",
    "varberg": "Varberg",
    "vasteras": "Västerås",
    "vaxjo": "Växjö",
}

_CITY_NAMES = {name.casefold(): name for name in _SWEDISH_CITIES.values()}

# "Norra Parkgatan 2", "Karlsgatan 7", "Stora Varvsgatan 6A" — a street, not a venue.
_STREET = re.compile(r"^.*(?:gatan|gatu|vägen|väg|torget|plan|gränd)\s+\d+\w*$", re.IGNORECASE)


def _events(html: str) -> Iterator[tuple[str, date, time, str, str, str, str]]:
    """Yield (title, date, time, ticket_url, cinema_name, city, address)."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        raise ValueError("doclounge.se: no __NEXT_DATA__ found")

    data = json.loads(script.string)
    events = data["props"]["pageProps"]["events"]["nodes"]
    log.info("doclounge.se: %d events found", len(events))

    parsed = [row for row in (_row(event) for event in events) if row]
    venue_cities = {cinema.casefold(): city for _, _, _, _, cinema, city, _ in parsed if city}
    # The site spells a venue inconsistently across events ("Skeppet Gbg", "Skeppet GBG");
    # the first spelling seen wins, so newest events set the name.
    canonical: dict[tuple[str, str], str] = {}

    for title, d, t, ticket_url, cinema, city, address in parsed:
        city = city or venue_cities.get(cinema.casefold(), "") or _city_from_address(address)
        if not city:
            continue
        cinema = cinema or f"Doc Lounge {city}"
        cinema = canonical.setdefault((city, cinema.casefold()), cinema)
        yield title, d, t, ticket_url, cinema, city, address


def _row(event: dict) -> tuple[str, date, time, str, str, str, str] | None:
    content = event.get("gqlEventContent") or {}

    date_str = content.get("date", "")
    time_str = content.get("time", "")
    if not date_str or not time_str:
        return None

    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return None

    m = re.match(r"(\d{1,2})[:.](\d{2})", time_str)
    if not m:
        return None
    t = time(int(m.group(1)), int(m.group(2)))

    ticket_url = (content.get("goToEvent") or {}).get("url", "")
    if not ticket_url:
        return None

    movie = content.get("movie") or {}
    title = movie.get("title") or event.get("title", "")
    if not title:
        return None

    # Upcoming events usually carry no city term at all; those resolve from the venue.
    slugs = [node.get("slug", "") for node in event.get("cities", {}).get("nodes", [])]
    city = next((_SWEDISH_CITIES[s] for s in slugs if s in _SWEDISH_CITIES), "")
    if slugs and not city:
        return None  # tagged only with foreign cities

    cinema, address = _split_address(content.get("address", ""))
    return title, d, t, ticket_url, cinema, city, address


def _split_address(raw: str) -> tuple[str, str]:
    """Split "Venue, Street, City" into (venue, rest); a street-only address names no venue."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts or _STREET.match(parts[0]):
        return "", raw.strip()
    return parts[0], ", ".join(parts[1:])


def _city_from_address(address: str) -> str:
    for part in reversed([p.strip() for p in address.split(",")]):
        # Trailing postcodes: "214 36 Malmö".
        name = re.sub(r"^\d[\d\s]*", "", part).strip().casefold()
        if name in _CITY_NAMES:
            return _CITY_NAMES[name]
    return ""


def _film_slugs(html: str) -> dict[str, str]:
    """Map each event title to the slug of its film page, where the site has one."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}

    slugs: dict[str, str] = {}
    for event in json.loads(script.string)["props"]["pageProps"]["events"]["nodes"]:
        movie = (event.get("gqlEventContent") or {}).get("movie") or {}
        title = movie.get("title") or ""
        uri = movie.get("uri") or ""
        # Unpublished films link to a preview host instead of a path on the site.
        if title and uri.startswith("/"):
            slugs.setdefault(title, uri.strip("/"))
    return slugs


def _film_details(html: str) -> dict:
    """Poster, synopsis, runtime, original title and year from a film page."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}

    movie = json.loads(script.string)["props"]["pageProps"].get("movie") or {}
    content = movie.get("movieContent") or {}
    info = content.get("info") or {}
    hero = (movie.get("heroContent") or {}).get("hero") or {}
    year = next((node.get("name", "") for node in (movie.get("yearTax") or {}).get("nodes", [])), "")

    return {
        "poster_url": _poster_url((hero.get("thumbnail") or {}).get("mediaItemUrl") or ""),
        "overview": _synopsis(content.get("swedishSynopsis") or content.get("description") or ""),
        "runtime": info.get("time") or None,
        "genres": list(_GENRES),
        "title_original": info.get("originalTitle") or "",
        "release_date": year if re.fullmatch(r"\d{4}", year) else "",
    }


def _poster_url(url: str) -> str:
    if not url or urlparse(url).scheme not in ("http", "https"):
        return ""
    return _POSTER_PROXY.format(url=quote(url, safe=""))


def _synopsis(html: str) -> str:
    """Plain text of the leading paragraphs.

    The field mixes the synopsis with a trailing fact list bulleted with "➤"
    and with paragraphs that hold nothing but a trailer or ticket link.
    """
    paragraphs: list[str] = []
    for p in BeautifulSoup(html, "html.parser").find_all("p"):
        text = p.get_text(" ", strip=True).replace("\xa0", " ").strip()
        if "➤" in text:
            break
        link = p.find("a")
        if not text or (link and link.get_text(" ", strip=True) == text):
            continue
        paragraphs.append(text)
    return "\n\n".join(paragraphs)


def parse() -> Iterator[Screening | Venue | Film]:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bio-parser/1.0)"

    html = _fetch(session, _URL)

    events = list(_events(html))
    slugs = _film_slugs(html)

    films: dict[str, Film] = {}
    for title in dict.fromkeys(event[0] for event in events):
        slug = slugs.get(title, "")
        url = _FILM_URL + slug if slug else ""
        film = _films.make(_SOURCE, title, url=url, **(_details(session, url) if url else {}))
        films[title] = _films.register(film, session=session)
        yield films[title]

    yielded_venues: set[tuple[str, str]] = set()

    for title, d, t, ticket_url, cinema_name, city, address in events:
        if (city, cinema_name) not in yielded_venues:
            yielded_venues.add((city, cinema_name))
            yield Venue(name=cinema_name, city=city, address=address)

        yield Screening(
            tmdb_id=_tmdb(title),
            title=title,
            date=d,
            time=t,
            ticket_url=ticket_url,
            cinema_name=cinema_name,
            city=city,
            film_key=films[title].key,
        )


def _fetch(session: requests.Session, url: str) -> str:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def _details(session: requests.Session, url: str) -> dict:
    try:
        return _film_details(_fetch(session, url))
    except requests.RequestException as exc:
        log.warning("doclounge.se: film page %s failed: %s", url, exc)
        return {}
