"""The Movie value object — TMDB metadata."""

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True, kw_only=True)
class Movie:
    """Movie metadata from TMDB."""

    tmdb_id: int
    title_sv: str
    title_original: str
    overview_sv: str
    genres: list[str]
    release_date: str
    release_date_se: str
    runtime: int | None
    poster_path: str
    vote_average: float | None
    age_rating: str

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            tmdb_id=d["tmdb_id"],
            title_sv=d.get("title_sv", ""),
            title_original=d.get("title_original", ""),
            overview_sv=d.get("overview_sv", ""),
            genres=d.get("genres", []),
            release_date=d.get("release_date", ""),
            release_date_se=d.get("release_date_se", ""),
            runtime=d.get("runtime"),
            poster_path=d.get("poster_path", ""),
            vote_average=d.get("vote_average"),
            age_rating=d.get("age_rating", ""),
        )
