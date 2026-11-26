"""The Film value object — metadata scraped from a cinema's own site."""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Self

from allabiografer.model.version import Language


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
    original_languages: frozenset[Language] = frozenset()
    directors: list[str] = field(default_factory=list)

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
            "original_languages": sorted(language.value for language in self.original_languages),
            "directors": list(self.directors),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            key=d["key"],
            source=d.get("source") or "",
            title=d.get("title") or "",
            title_original=d.get("title_original") or "",
            overview=d.get("overview") or "",
            runtime=d.get("runtime") or None,
            genres=d.get("genres") or [],
            release_date=d.get("release_date") or "",
            age_rating=d.get("age_rating") or "",
            poster_url=d.get("poster_url") or "",
            url=d.get("url") or "",
            original_languages=frozenset(Language(v) for v in d.get("original_languages", ())),
            directors=d.get("directors") or [],
        )


@lru_cache(maxsize=65536)
def title_key(title: str) -> str:
    """Normalised title: NFKC, casefolded, word tokens joined by single spaces."""
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", title).casefold()))


def shared_synopsis(left: str, right: str, *, corroborated: bool = False, allow_short: bool = False) -> bool:
    """Substantial literal plot overlap, not fuzzy titles or generic blurbs."""
    shorter, longer = sorted((title_key(left), title_key(right)), key=len)
    words, other_words = shorter.split(), longer.split()
    alignment = SequenceMatcher(None, words, other_words, autojunk=False)
    common = alignment.find_longest_match()
    return (
        (common.size >= 20 or (allow_short and common.size >= 15 and common.size == len(words)))
        and len(" ".join(words[common.a : common.a + common.size])) >= 100
        and (
            common.size * 2 >= len(words)
            or sum(block.size for block in alignment.get_matching_blocks()) * 10 >= len(words) * 9
            or corroborated
        )
    )


def film_key(source: str, title: str) -> str:
    """Film identity: source name and normalised title."""
    return f"{source}:{title_key(title)}"
