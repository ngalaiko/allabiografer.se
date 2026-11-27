"""The Screening value object."""

from dataclasses import dataclass, field
from datetime import date, time
from typing import Self

from allabiografer.model.version import (
    AudioFormat,
    AudioKind,
    AudioVersion,
    ContentVersion,
    Language,
    Presentation,
    SubtitleVersion,
    VideoFormat,
    ordered,
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
    raw_attributes: tuple[str, ...] = ()
    runtime: int | None = None

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
            "raw_attributes": list(self.raw_attributes),
            **({"runtime": self.runtime} if self.runtime is not None else {}),
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
            raw_attributes=tuple(d.get("raw_attributes", ())),
            runtime=d.get("runtime"),
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
        "video": [x.value for x in ordered(p.video)],
        "audio": [x.value for x in ordered(p.audio)],
    }


def _presentation_from_dict(d: dict) -> Presentation:
    return Presentation(
        video=frozenset(VideoFormat(x) for x in d.get("video", ())),
        audio=frozenset(AudioFormat(x) for x in d.get("audio", ())),
    )
