"""doclounge.se — Doc Lounge documentary screenings, Next.js SSR with __NEXT_DATA__."""

import itertools
import json
import logging
import re
from collections.abc import Iterator
from datetime import date, time
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import ImageFile

from parse import _http, _version
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

# Longer event info is prose, not a programme label.
_MAX_INFO = 40
_DASH = re.compile(r"\s+[–—-]\s+")

# "Norra Parkgatan 2", "Karlsgatan 7", "Stora Varvsgatan 6A" — a street, not a venue.
_STREET = re.compile(r"^.*(?:gatan|gatu|vägen|väg|torget|plan|gränd)\s+\d+\w*$", re.IGNORECASE)
# The last word of a street and its number: "Södra Storgatan 39A" and "Storgatan 39a" share "storgatan 39a".
_STREET_KEY = re.compile(r"([^\W\d_]+(?:gatan|gatu|vägen|väg|torget|plan|gränd))\s+(\d+)\s?([a-z]?)\b", re.IGNORECASE)

# "The Beauty of Errors (Det finaste av Finland)": the Swedish title trails in parentheses.
_ALT_TITLE = re.compile(r"\s*\((?=[^()]*[^\W\d_])[^()]+\)$")

# A "Synopsis" heading or label opens the synopsis proper.
_SYNOPSIS = re.compile(r"^synopsis\b\s*:?\s*", re.IGNORECASE)
# A short paragraph ending in a colon heads the next section: "Directors statement:".
_HEADING = re.compile(r".{1,40}:")
# Screening lists and booking lines: "25/1 Världspremiär…", "Bokning: maja@doclounge.se".
_LISTING = re.compile(r"\bvisning|\bbokning|biljett|premiär|klicka här|@|\b\d{1,2}/\d{1,2}\b", re.IGNORECASE)
_MAX_LISTING = 200
_AGE_LIMIT = re.compile(r"Åldersgräns\s*:\s*(\w+)", re.IGNORECASE)

# Image header bytes read to learn an image's size.
_MAX_HEADER = 1024 * 1024


Event = tuple[str, date, time, str, str, str, str, tuple[str, ...]]


def _events(html: str) -> Iterator[Event]:
    """Yield (title, date, time, ticket_url, cinema_name, city, address, raw_attributes)."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        raise ValueError("doclounge.se: no __NEXT_DATA__ found")

    data = json.loads(script.string)
    events = data["props"]["pageProps"]["events"]["nodes"]
    log.info("doclounge.se: %d events found", len(events))

    parsed = [row for row in (_row(event) for event in events) if row]
    venue_cities = {cinema.casefold(): city for _, _, _, _, cinema, city, _, _ in parsed if city}
    located: list[Event] = []
    for title, d, t, ticket_url, cinema, city, address, raw in parsed:
        city = city or venue_cities.get(cinema.casefold(), "") or _city_from_address(address)
        if city:
            located.append((title, d, t, ticket_url, cinema, city, address, raw))
    # A street-only address takes the name of a venue seen at the same street.
    named: dict[tuple[str, str], str] = {}
    for _, _, _, _, cinema, city, address, _ in located:
        if cinema and (street := _street_key(address)):
            named.setdefault((city, street), cinema)
    # The site spells a venue inconsistently across events ("Skeppet Gbg", "Skeppet GBG");
    # the first spelling seen wins, so newest events set the name.
    canonical: dict[tuple[str, str], str] = {}

    for title, d, t, ticket_url, cinema, city, address, raw in located:
        if not cinema:
            street = address.split(",")[0].strip()
            cinema = named.get((city, _street_key(address))) or street or f"Doc Lounge {city}"
        cinema = canonical.setdefault((city, cinema.casefold()), cinema)
        yield title, d, t, ticket_url, cinema, city, address, raw


def _street_key(address: str) -> str:
    m = _STREET_KEY.search(address)
    return " ".join(m.group(1, 2)).casefold() + m.group(3).casefold() if m else ""


def _title(raw: str) -> str:
    return _ALT_TITLE.sub("", raw).strip() or raw.strip()


def _row(event: dict) -> Event | None:
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
    title = _title(movie.get("title") or event.get("title") or "")
    if not title:
        return None

    # Upcoming events usually carry no city term at all; those resolve from the venue.
    slugs = [node.get("slug", "") for node in event.get("cities", {}).get("nodes", [])]
    city = next((_SWEDISH_CITIES[s] for s in slugs if s in _SWEDISH_CITIES), "")
    if slugs and not city:
        return None  # tagged only with foreign cities

    cinema, address = _split_address(content.get("address", ""))
    return title, d, t, ticket_url, cinema, city, address, _raw_attributes(title, event, content)


def _raw_attributes(title: str, event: dict, content: dict) -> tuple[str, ...]:
    """Programme labels: an event title's suffix ("HEX – Halloweenspecial") and a short info line."""
    raw: list[str] = []
    event_title = event.get("title") or ""
    if event_title.casefold().startswith(title.casefold()):
        m = re.match(r"\s*[–—-]\s*(.+)", event_title[len(title) :])
        if m and m.group(1).strip().casefold() not in _CITY_NAMES:
            raw.append(m.group(1).strip())
    info = BeautifulSoup(content.get("info") or "", "html.parser").get_text(" ", strip=True)
    # "The Beauty of Errors - Filmvisning + Regissörsbesök" repeats the film title.
    head, *tail = _DASH.split(info, maxsplit=1)
    if tail and title.casefold().startswith(head.casefold()):
        info = tail[0].strip()
    if info and len(info) <= _MAX_INFO and info not in raw:
        raw.append(info)
    return tuple(raw)


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
        title = _title(movie.get("title") or "")
        uri = movie.get("uri") or ""
        # Unpublished films link to a preview host instead of a path on the site.
        if title and uri.startswith("/"):
            slugs.setdefault(title, uri.strip("/"))
    return slugs


def _listed_details(html: str) -> dict[str, dict]:
    """Poster candidates and genres per event title from the events page, for films without a published page."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}

    details: dict[str, dict] = {}
    for event in json.loads(script.string)["props"]["pageProps"]["events"]["nodes"]:
        movie = (event.get("gqlEventContent") or {}).get("movie") or {}
        hero = (movie.get("GQLMovieHeroContent") or {}).get("hero") or {}
        images = [(hero.get(key) or {}).get("mediaItemUrl") or "" for key in ("thumbnail", "heroImage")]
        if movie.get("title"):
            details.setdefault(
                _title(movie["title"]), {"posters": list(dict.fromkeys(filter(None, images))), "genres": list(_GENRES)}
            )
    return details


def _film_details(html: str) -> dict:
    """Poster, synopsis, runtime, original title, year, age limit and languages from a film page."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}

    movie = json.loads(script.string)["props"]["pageProps"].get("movie") or {}
    content = movie.get("movieContent") or {}
    info = content.get("info") or {}
    hero = (movie.get("heroContent") or {}).get("hero") or {}
    year = next((node.get("name", "") for node in (movie.get("yearTax") or {}).get("nodes", [])), "")
    body = content.get("swedishSynopsis") or content.get("description") or ""
    # Languages and age limit ride in the synopsis' "➤" fact list.
    facts = BeautifulSoup(body, "html.parser").get_text(" ")
    language, subtitles = _version.from_text(facts)
    age = _AGE_LIMIT.search(facts)

    return {
        "poster_url": _poster_url((hero.get("thumbnail") or {}).get("mediaItemUrl") or ""),
        "overview": _synopsis(body),
        "runtime": info.get("time") or None,
        "genres": list(_GENRES),
        "title_original": (info.get("originalTitle") or "").strip(),
        "release_date": year if re.fullmatch(r"\d{4}", year) else "",
        "age_rating": age.group(1) if age else "",
        "original_languages": _version.languages(language),
        "language_label": language,
        "subtitle_label": subtitles,
    }


def _poster_url(url: str) -> str:
    if not url or urlparse(url).scheme not in ("http", "https"):
        return ""
    return _POSTER_PROXY.format(url=quote(url, safe=""))


def _synopsis(html: str) -> str:
    """Plain text of the synopsis.

    The field mixes the synopsis with screening lists, booking details, a
    trailing fact list bulleted with "➤" and paragraphs that hold nothing but
    a trailer or ticket link.  A "Synopsis" heading, where present, opens the
    synopsis and the next heading ends it.
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
    start = next((i for i, text in enumerate(paragraphs) if _SYNOPSIS.match(text)), None)
    if start is not None:
        head = _SYNOPSIS.sub("", paragraphs[start], count=1)
        rest = ([head] if head else []) + paragraphs[start + 1 :]
        paragraphs = list(itertools.takewhile(lambda text: not _HEADING.fullmatch(text), rest))
    return "\n\n".join(text for text in paragraphs if not _listing(text))


def _listing(text: str) -> bool:
    """A screening list or booking line: "GÖTEBORG:", "1/4 Visning + samtal…"."""
    return len(text) <= _MAX_LISTING and (text.isupper() or bool(_LISTING.search(text)))


def parse() -> Iterator[Screening | Venue | Film]:
    session = _http.session()

    html = _fetch(session, _URL)

    events = list(_events(html))
    slugs = _film_slugs(html)
    listed = _listed_details(html)

    films: dict[str, Film] = {}
    languages: dict[str, str] = {}
    subtitles: dict[str, str] = {}
    for title in dict.fromkeys(event[0] for event in events):
        slug = slugs.get(title, "")
        url = _FILM_URL + slug if slug else ""
        details = _details(session, url) if url else {}
        # Documentaries are screened in their original language.
        languages[title] = details.pop("language_label", "")
        subtitles[title] = details.pop("subtitle_label", "")
        candidates = listed.get(title, {}).get("posters", [])
        details = {k: v for k, v in listed.get(title, {}).items() if k != "posters"} | {
            k: v for k, v in details.items() if v
        }
        if not details.get("poster_url"):
            details["poster_url"] = _portrait_poster(session, candidates)
        film = _films.make(_SOURCE, title, url=url, **details)
        films[title] = _films.register(film, session=session)
        yield films[title]

    yielded_venues: set[tuple[str, str]] = set()

    for title, d, t, ticket_url, cinema_name, city, address, raw in events:
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
            **_version.screening_facts(
                language=languages.get(title, ""), subtitles=subtitles.get(title, ""), raw_attributes=raw
            ),
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


def _portrait_poster(session: requests.Session, urls: list[str]) -> str:
    """The first portrait image; event images are often landscape stills."""
    for url in urls:
        size = _image_size(session, url)
        if size and size[1] > size[0]:
            return _poster_url(url)
    return ""


def _image_size(session: requests.Session, url: str) -> tuple[int, int] | None:
    """Width and height from the image's leading bytes."""
    parser = ImageFile.Parser()
    try:
        with session.get(url, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            read = 0
            for chunk in resp.iter_content(64 * 1024):
                parser.feed(chunk)
                read += len(chunk)
                if parser.image or read >= _MAX_HEADER:
                    break
    except (requests.RequestException, OSError) as exc:
        log.warning("doclounge.se: image %s failed: %s", url, exc)
        return None
    return parser.image.size if parser.image else None
