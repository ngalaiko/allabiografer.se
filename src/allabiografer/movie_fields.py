"""Schema.org Movie fields from source metadata, in one vocabulary.

Every source Movie passes through `normalise`: properties outside `PROPERTIES` drop,
genres map onto `GENRES`, age ratings onto `AgeRating`, languages onto BCP 47 tags,
runtimes onto ISO 8601 minutes and people onto `Person` lists.
"""

import re
import unicodedata
from typing import TYPE_CHECKING

from allabiografer.model.version import Language
from allabiografer.normalize import languages as _spoken
from allabiografer.rating import age_rating

if TYPE_CHECKING:
    from collections.abc import Iterable

    from allabiografer.model import Film

# Schema.org Movie properties sources may state; the merge owns identifier, url and sameAs.
PROPERTIES = (
    "name",
    "alternateName",
    "url",
    "sameAs",
    "description",
    "duration",
    "datePublished",
    "genre",
    "contentRating",
    "inLanguage",
    "image",
    "director",
    "actor",
    "trailer",
    "version",
)

# Genres, Swedish, as TMDB's Swedish names where it has one; performances are genres too.
GENRES = (
    "Action",
    "Animerat",
    "Balett",
    "Barnfilm",
    "Biografi",
    "Dans",
    "Dokumentär",
    "Drama",
    "Familj",
    "Fantasy",
    "Feelgood",
    "Historia",
    "Komedi",
    "Konsert",
    "Krig",
    "Kriminal",
    "Musik",
    "Musikal",
    "Mysterium",
    "Opera",
    "Romantik",
    "Science fiction",
    "Skräck",
    "Sport",
    "Svart komedi",
    "Teater",
    "Thriller",
    "Uppväxtskildring",
    "Västern",
    "Äventyr",
)

# Source spellings, casefolded, to genres. Unlisted labels (seasons, series, event
# names such as "Live på bio" or "Jul") are programme labels and drop.
_SPELLINGS: dict[str, tuple[str, ...]] = {
    **{genre.casefold(): (genre,) for genre in GENRES},
    "adventure": ("Äventyr",),
    "animerad": ("Animerat",),
    "animerad film": ("Animerat",),
    "animation": ("Animerat",),
    "anime": ("Animerat",),
    "animerad familjefilm": ("Animerat", "Familj"),
    "animerad barnfilm": ("Animerat", "Barnfilm"),
    "barn": ("Barnfilm",),
    "knattebio": ("Barnfilm",),
    "ballet": ("Balett",),
    "biography": ("Biografi",),
    "comedy": ("Komedi",),
    "coming-of-age": ("Uppväxtskildring",),
    "coming of age": ("Uppväxtskildring",),
    "concert": ("Konsert",),
    "live concert": ("Konsert",),
    "crime": ("Kriminal",),
    "krim": ("Kriminal",),
    "dans och musik": ("Dans", "Musik"),
    "documentary": ("Dokumentär",),
    "familjefilm": ("Familj",),
    "family": ("Familj",),
    "feel-good": ("Feelgood",),
    "historisk": ("Historia",),
    "history": ("Historia",),
    "period drama": ("Historia", "Drama"),
    "horror": ("Skräck",),
    "krigsfilm": ("Krig",),
    "war": ("Krig",),
    "live theatre": ("Teater",),
    "mörk komedi": ("Svart komedi",),
    "music": ("Musik",),
    "musical": ("Musikal",),
    "mystery": ("Mysterium",),
    "mysterie": ("Mysterium",),
    "mystik": ("Mysterium",),
    "romance": ("Romantik",),
    "romantisk komedi": ("Romantik", "Komedi"),
    "sci-fi": ("Science fiction",),
    "sci fi": ("Science fiction",),
    "scifi": ("Science fiction",),
    "superhjältefilm": ("Action",),
    "western": ("Västern",),
}

_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")
_IMDB = re.compile(r"https?://(?:www\.|m\.)?imdb\.com/title/(tt\d{7,8})")


def imdb_links(html: str) -> list[str]:
    """Canonical IMDb title URLs linked from a page."""
    return [f"https://www.imdb.com/title/{found}" for found in dict.fromkeys(_IMDB.findall(html))]


_DATE = re.compile(r"(?:1[89]|20)\d{2}(?:-\d{2}-\d{2})?")
_TAGS = {language.tag for language in Language}


def _text(value) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split()) if isinstance(value, str) else ""


def _list(value) -> list:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, list | tuple | set | frozenset) else [value]


def genres(values: Iterable[str]) -> list[str]:
    """Genres for source labels, in source order; labels that are no genre drop."""
    found = []
    for value in values:
        for part in re.split(r"\s*[,/|]\s*", _text(value)):
            found += _SPELLINGS.get(part.casefold(), ())
    return list(dict.fromkeys(found))


def minutes(value) -> int | None:
    if isinstance(value, str) and (found := _DURATION.fullmatch(value.strip())):
        value = int(found[1] or 0) * 60 + int(found[2] or 0)
    elif isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    # Listings round programme lengths; anything past a day is a typo.
    return value if isinstance(value, int) and 0 < value < 24 * 60 else None


def _people(value) -> list[dict]:
    names = []
    for person in _list(value):
        name = _text(person.get("name") if isinstance(person, dict) else person)
        if name:
            names.append(name)
    return [{"@type": "Person", "name": name} for name in dict.fromkeys(names)]


def _trailers(value) -> list[dict]:
    urls = []
    for trailer in _list(value):
        url = _text(trailer.get("url") or trailer.get("embedUrl") if isinstance(trailer, dict) else trailer)
        if url.startswith(("http://", "https://")):
            urls.append(url)
    return [{"@type": "VideoObject", "url": url} for url in dict.fromkeys(urls)]


def _languages(value) -> list[str]:
    tags = []
    for language in _list(value):
        tag = language.tag if isinstance(language, Language) else _text(language)
        if tag in _TAGS:
            tags.append(tag)
    return sorted(set(tags))


def normalise(movie: dict) -> dict:
    """A source Movie with every property in this module's vocabulary; empty values drop."""
    name = _text(movie.get("name"))
    fields = {
        "name": name,
        "alternateName": next(
            (alt for alt in map(_text, _list(movie.get("alternateName"))) if alt and alt != name), ""
        ),
        "url": _text(movie.get("url")),
        "sameAs": sorted({url for url in map(_text, _list(movie.get("sameAs"))) if url}),
        "description": _text(movie.get("description")),
        "duration": f"PT{runtime}M" if (runtime := minutes(movie.get("duration"))) else "",
        "datePublished": published if _DATE.fullmatch(published := _text(movie.get("datePublished"))) else "",
        "genre": genres(_list(movie.get("genre"))),
        "contentRating": str(age_rating(_text(movie.get("contentRating")))),
        "inLanguage": _languages(movie.get("inLanguage")),
        "image": _text(movie.get("image")) if not isinstance(movie.get("image"), dict) else movie["image"],
        "director": _people(movie.get("director")),
        "actor": _people(movie.get("actor")),
        "trailer": _trailers(movie.get("trailer")),
        "version": _text(movie.get("version")),
    }
    return {key: fields[key] for key in PROPERTIES if fields[key]}


def movie_fields(
    title,
    url="",
    description="",
    runtime=None,
    credits=None,
    *,
    year="",
    alternate="",
    genre=(),
    rating="",
    image="",
    languages=(),
    trailers=(),
    same_as=(),
) -> dict:
    """A normalised source Movie; `credits` maps `director`/`actor` to names."""
    credits = credits or {}
    return normalise(
        {
            "name": title,
            "alternateName": alternate,
            "url": url,
            "sameAs": list(same_as),
            "description": description,
            "duration": runtime,
            "datePublished": year,
            "genre": list(genre),
            "contentRating": rating,
            "inLanguage": list(languages),
            "image": image,
            "director": credits.get("director"),
            "actor": credits.get("actor"),
            "trailer": list(trailers),
        }
    )


def film_fields(film: Film, url=None, *, credits=None, **overrides) -> dict:
    """A normalised source Movie with every field a parsed `Film` states."""
    fields = {
        "description": film.overview,
        "runtime": film.runtime,
        "year": film.release_date,
        "alternate": film.title_original,
        "genre": film.genres,
        "rating": film.age_rating,
        "image": film.poster_url,
        "languages": film.original_languages,
        "trailers": film.trailers,
        "credits": {"director": film.directors, **(credits or {})},
    }
    return movie_fields(film.title, film.url if url is None else url, **(fields | overrides))


def details_fields(title, url, details: dict) -> dict:
    """A normalised source Movie from a dict keyed like `Film`'s fields, plus `actors`."""
    return movie_fields(
        title,
        url,
        details.get("overview"),
        details.get("runtime"),
        {"director": details.get("directors"), "actor": details.get("actors")},
        year=details.get("release_date") or "",
        alternate=details.get("title_original") or "",
        genre=details.get("genres") or [],
        rating=details.get("age_rating") or "",
        image=details.get("poster_url") or "",
        languages=details.get("original_languages") or [],
        trailers=details.get("trailers") or [],
    )


def booking_fields(detail: dict) -> dict:
    """Keyword arguments for `movie_fields` from a Biljettsystem/Filmgrail-style movie record.

    Roxy and Rio Tomelilla share it: genres as names, YouTube ids, IMDb and TMDB ids.
    """
    links = []
    if re.fullmatch(r"tt\d+", imdb := str(detail.get("imdb_id") or "")):
        links.append(f"https://www.imdb.com/title/{imdb}")
    if str(detail.get("tmdb_id") or "").isdigit():
        links.append(f"https://www.themoviedb.org/movie/{detail['tmdb_id']}")
    youtube = str(detail.get("youtube_link") or "").strip()
    return {
        "genre": [detail.get("genres_name") or ""],
        "languages": _languages_from_label(detail.get("audio_name")),
        "trailers": [youtube if youtube.startswith("http") else f"https://www.youtube.com/watch?v={youtube}"]
        if youtube
        else [],
        "same_as": links,
    }


def _languages_from_label(label) -> list[Language]:
    return sorted(_spoken(_text(label)))
