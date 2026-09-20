"""The Film value object — metadata scraped from a cinema's own site."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Self


@dataclass(frozen=True, slots=True, kw_only=True)
class Film:
    """Film metadata from a cinema site, keyed by ``source:title``."""

    key: str
    source: str
    title: str
    title_original: str = ""
    overview: str = ""
    runtime: int | None = None
    genres: list[str] = field(default_factory=list)
    release_date: str = ""
    age_rating: str = ""
    poster_url: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "source": self.source,
            "title": self.title,
            "title_original": self.title_original,
            "overview": self.overview,
            "runtime": self.runtime,
            "genres": list(self.genres),
            "release_date": self.release_date,
            "age_rating": self.age_rating,
            "poster_url": self.poster_url,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            key=d["key"],
            source=d.get("source") or "",
            title=d.get("title") or "",
            title_original=d.get("title_original") or "",
            overview=d.get("overview") or "",
            runtime=d.get("runtime"),
            genres=d.get("genres") or [],
            release_date=d.get("release_date") or "",
            age_rating=d.get("age_rating") or "",
            poster_url=d.get("poster_url") or "",
            url=d.get("url") or "",
        )


def title_key(title: str) -> str:
    """Normalised title: NFKC, casefolded, word tokens joined by single spaces."""
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", title).casefold()))


def film_key(source: str, title: str) -> str:
    """Film identity: source name and normalised title."""
    return f"{source}:{title_key(title)}"


def poster_key_for_film(key: str) -> str:
    """Poster key for a film key — a relative path segment under the posters dir."""
    source, _, normalised = key.partition(":")
    return f"{source}/{normalised.replace(' ', '-')[:100]}"
