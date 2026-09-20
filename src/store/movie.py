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

    def to_dict(self) -> dict:
        return {
            "tmdb_id": self.tmdb_id,
            "title_sv": self.title_sv,
            "title_original": self.title_original,
            "overview_sv": self.overview_sv,
            "genres": list(self.genres),
            "release_date": self.release_date,
            "release_date_se": self.release_date_se,
            "runtime": self.runtime,
            "poster_path": self.poster_path,
            "vote_average": self.vote_average,
            "age_rating": self.age_rating,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            tmdb_id=d["tmdb_id"],
            title_sv=d.get("title_sv") or "",
            title_original=d.get("title_original") or "",
            overview_sv=d.get("overview_sv") or "",
            genres=d.get("genres") or [],
            release_date=d.get("release_date") or "",
            release_date_se=d.get("release_date_se") or "",
            runtime=d.get("runtime"),
            poster_path=d.get("poster_path") or "",
            vote_average=d.get("vote_average"),
            age_rating=d.get("age_rating") or "",
        )
