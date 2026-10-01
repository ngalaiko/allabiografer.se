"""Typed screening content, presentation, and accessibility facts."""

from dataclasses import dataclass, field
from enum import StrEnum


class Language(StrEnum):
    SWEDISH = "Svenska"
    ENGLISH = "Engelska"
    FRENCH = "Franska"
    GERMAN = "Tyska"
    ITALIAN = "Italienska"
    SPANISH = "Spanska"
    PORTUGUESE = "Portugisiska"
    JAPANESE = "Japanska"
    KOREAN = "Koreanska"
    CHINESE = "Kinesiska"
    MANDARIN = "Mandarin"
    CANTONESE = "Kantonesiska"
    FINNISH = "Finska"
    NORWEGIAN = "Norska"
    DANISH = "Danska"
    ICELANDIC = "Isländska"
    DUTCH = "Nederländska"
    POLISH = "Polska"
    RUSSIAN = "Ryska"
    UKRAINIAN = "Ukrainska"
    CZECH = "Tjeckiska"
    HUNGARIAN = "Ungerska"
    ROMANIAN = "Rumänska"
    GREEK = "Grekiska"
    TURKISH = "Turkiska"
    ARABIC = "Arabiska"
    PERSIAN = "Persiska"
    KURDISH = "Kurdiska"
    HEBREW = "Hebreiska"
    HINDI = "Hindi"
    KANNADA = "Kannada"
    TAMIL = "Tamil"
    TELUGU = "Telugu"
    THAI = "Thailändska"
    VIETNAMESE = "Vietnamesiska"
    GEORGIAN = "Georgiska"
    CATALAN = "Katalanska"
    KAZAKH = "Kazakiska"
    AZERBAIJANI = "Azerbajdzjanska"
    SERBIAN = "Serbiska"
    CROATIAN = "Kroatiska"
    BOSNIAN = "Bosniska"
    ESTONIAN = "Estniska"
    LATVIAN = "Lettiska"
    LITHUANIAN = "Litauiska"
    SOMALI = "Somaliska"


class AudioKind(StrEnum):
    UNKNOWN = "unknown"
    ORIGINAL = "original"
    DUBBED = "dubbed"
    SILENT = "silent"


@dataclass(frozen=True, slots=True)
class AudioVersion:
    kind: AudioKind = AudioKind.UNKNOWN
    languages: frozenset[Language] = frozenset()


@dataclass(frozen=True, slots=True)
class SubtitleVersion:
    languages: frozenset[Language] | None = None


@dataclass(frozen=True, slots=True)
class ContentVersion:
    audio: AudioVersion = field(default_factory=AudioVersion)
    subtitles: SubtitleVersion = field(default_factory=SubtitleVersion)
    edition: str | None = None


class PresentationSystem(StrEnum):
    IMAX = "IMAX"
    DOLBY_CINEMA = "Dolby Cinema"
    FOUR_DX = "4DX"
    SCREENX = "ScreenX"
    D_BOX = "D-Box"
    ISENSE = "iSense"
    INFINITY_VISION = "Infinity Vision"


class Dimension(StrEnum):
    UNKNOWN = "unknown"
    TWO_D = "2D"
    THREE_D = "3D"


class ProjectionMedium(StrEnum):
    UNKNOWN = "unknown"
    DIGITAL = "digital"
    MM_35 = "35 mm"
    MM_70 = "70 mm"


class ProjectionAttribute(StrEnum):
    K4 = "4K"
    LASER = "Laser"


class SoundAttribute(StrEnum):
    DOLBY_ATMOS = "Dolby Atmos"


class AuditoriumAttribute(StrEnum):
    VIP = "VIP"
    XL = "XL"


@dataclass(frozen=True, slots=True)
class Presentation:
    experiences: frozenset[PresentationSystem] = frozenset()
    dimension: Dimension = Dimension.UNKNOWN
    medium: ProjectionMedium = ProjectionMedium.UNKNOWN
    projection: frozenset[ProjectionAttribute] = frozenset()
    sound: frozenset[SoundAttribute] = frozenset()
    auditorium: frozenset[AuditoriumAttribute] = frozenset()


class AccessibilityFeature(StrEnum):
    AUDIO_DESCRIPTION = "Syntolkning"


@dataclass(frozen=True, slots=True)
class Accessibility:
    features: frozenset[AccessibilityFeature] = frozenset()


class AgeRating(StrEnum):
    ALL = "Barntillåten"
    FROM_7 = "Från 7 år"
    FROM_11 = "Från 11 år"
    FROM_15 = "Från 15 år"
    FROM_18 = "Från 18 år"


LANGUAGES = tuple(language.value for language in Language)


def _label(names: list[str], ending: str, noun: str) -> str:
    if not names:
        return ""
    if not all(name.endswith("ska") for name in names):
        return f"{noun.capitalize()} på " + ", ".join(name.lower() for name in names)
    words = [name[:-1] + ending for name in names]
    return ", ".join([words[0], *(w.lower() for w in words[1:])]) + " " + noun


def speech_label(names: list[str]) -> str:
    return _label(names, "t", "tal")


def subtitles_label(names: list[str]) -> str:
    return _label(names, "", "text")
