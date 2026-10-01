"""The Screening value object."""

from dataclasses import dataclass, field
from datetime import date, time
from typing import Self

from store.version import (
    Accessibility,
    AccessibilityFeature,
    AudioKind,
    AudioVersion,
    AuditoriumAttribute,
    ContentVersion,
    Dimension,
    Language,
    Presentation,
    PresentationSystem,
    ProjectionAttribute,
    ProjectionMedium,
    SoundAttribute,
    SubtitleVersion,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Screening:
    """One showtime of one film at one cinema."""

    tmdb_id: int | None
    date: date
    time: time
    ticket_url: str
    cinema_name: str
    city: str
    title: str = ""
    source: str = ""
    film_key: str = ""
    screen: str = ""
    version: ContentVersion = field(default_factory=ContentVersion)
    presentation: Presentation = field(default_factory=Presentation)
    accessibility: Accessibility = field(default_factory=Accessibility)
    raw_attributes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Serialise for JSON storage."""
        return {
            "tmdb_id": self.tmdb_id,
            "date": self.date.isoformat(),
            "time": self.time.strftime("%H:%M"),
            "cinema_name": self.cinema_name,
            "city": self.city,
            "ticket_url": self.ticket_url,
            "title": self.title,
            "source": self.source,
            "film_key": self.film_key,
            "screen": self.screen,
            "version": _content_to_dict(self.version),
            "presentation": _presentation_to_dict(self.presentation),
            "accessibility": [feature.value for feature in sorted(self.accessibility.features)],
            "raw_attributes": list(self.raw_attributes),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        """Deserialise from JSON storage."""
        h, m = d["time"].split(":")
        return cls(
            tmdb_id=d.get("tmdb_id"),
            title=d.get("title", ""),
            source=d.get("source", ""),
            film_key=d.get("film_key", ""),
            date=date.fromisoformat(d["date"]),
            time=time(int(h), int(m)),
            ticket_url=d["ticket_url"],
            cinema_name=d["cinema_name"],
            city=d["city"],
            screen=d.get("screen", ""),
            version=_content_from_dict(d.get("version", {})),
            presentation=_presentation_from_dict(d.get("presentation", {})),
            accessibility=Accessibility(frozenset(AccessibilityFeature(v) for v in d.get("accessibility", ()))),
            raw_attributes=tuple(d.get("raw_attributes", ())),
        )


def _content_to_dict(v: ContentVersion) -> dict:
    return {
        "audio": {"kind": v.audio.kind.value, "languages": sorted(x.value for x in v.audio.languages)},
        "subtitles": None if v.subtitles.languages is None else sorted(x.value for x in v.subtitles.languages),
        "edition": v.edition,
    }


def _content_from_dict(d: dict) -> ContentVersion:
    audio = d.get("audio", {})
    subtitles = d.get("subtitles")
    audio_languages = frozenset(Language(x) for x in audio.get("languages", ()))
    return ContentVersion(
        audio=AudioVersion(AudioKind(audio.get("kind", "unknown")), audio_languages),
        subtitles=SubtitleVersion(None if subtitles is None else frozenset(Language(x) for x in subtitles)),
        edition=d.get("edition"),
    )


def _presentation_to_dict(p: Presentation) -> dict:
    return {
        "experiences": sorted(x.value for x in p.experiences),
        "dimension": p.dimension.value,
        "medium": p.medium.value,
        "projection": sorted(x.value for x in p.projection),
        "sound": sorted(x.value for x in p.sound),
        "auditorium": sorted(x.value for x in p.auditorium),
    }


def _presentation_from_dict(d: dict) -> Presentation:
    return Presentation(
        experiences=frozenset(PresentationSystem(x) for x in d.get("experiences", ())),
        dimension=Dimension(d.get("dimension", "unknown")),
        medium=ProjectionMedium(d.get("medium", "unknown")),
        projection=frozenset(ProjectionAttribute(x) for x in d.get("projection", ())),
        sound=frozenset(SoundAttribute(x) for x in d.get("sound", ())),
        auditorium=frozenset(AuditoriumAttribute(x) for x in d.get("auditorium", ())),
    )
