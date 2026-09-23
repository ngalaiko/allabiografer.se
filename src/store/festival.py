"""Festival value objects — an edition and its programme screenings."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class Festival:
    """One festival edition; ``source`` names its importer."""

    slug: str
    year: int
    name: str
    city: str
    start: str
    end: str
    url: str
    source: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FestivalScreening:
    """A programme screening. Times are ISO 8601 with UTC offset; ``end`` is empty when unknown."""

    id: str
    film_id: str
    title: str
    start: str
    end: str = ""
    venue: str
    url: str
    language: str = ""
    subtitles: str = ""
    film_url: str = ""
    poster_url: str = ""
    description: str = ""
    intro: str = ""
    runtime: int | None = None
    genres: str = ""
    sections: str = ""
    director: str = ""
    country: str = ""
    production_year: str = ""
