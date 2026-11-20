"""Typed screening content, presentation, and accessibility facts."""

from dataclasses import dataclass, field
from enum import StrEnum


class Language(StrEnum):
    def __new__(cls, label: str, tag: str):
        language = str.__new__(cls, label)
        language._value_ = label
        language.tag = tag
        return language

    SWEDISH = "Svenska", "sv"
    ENGLISH = "Engelska", "en"
    FRENCH = "Franska", "fr"
    GERMAN = "Tyska", "de"
    ITALIAN = "Italienska", "it"
    SPANISH = "Spanska", "es"
    PORTUGUESE = "Portugisiska", "pt"
    JAPANESE = "Japanska", "ja"
    KOREAN = "Koreanska", "ko"
    CHINESE = "Kinesiska", "zh"
    MANDARIN = "Mandarin", "cmn"
    CANTONESE = "Kantonesiska", "yue"
    FINNISH = "Finska", "fi"
    NORWEGIAN = "Norska", "no"
    DANISH = "Danska", "da"
    ICELANDIC = "Isländska", "is"
    DUTCH = "Nederländska", "nl"
    POLISH = "Polska", "pl"
    RUSSIAN = "Ryska", "ru"
    UKRAINIAN = "Ukrainska", "uk"
    CZECH = "Tjeckiska", "cs"
    HUNGARIAN = "Ungerska", "hu"
    ROMANIAN = "Rumänska", "ro"
    GREEK = "Grekiska", "el"
    TURKISH = "Turkiska", "tr"
    ARABIC = "Arabiska", "ar"
    PERSIAN = "Persiska", "fa"
    KURDISH = "Kurdiska", "ku"
    HEBREW = "Hebreiska", "he"
    HINDI = "Hindi", "hi"
    KANNADA = "Kannada", "kn"
    TAMIL = "Tamil", "ta"
    TELUGU = "Telugu", "te"
    THAI = "Thailändska", "th"
    VIETNAMESE = "Vietnamesiska", "vi"
    GEORGIAN = "Georgiska", "ka"
    CATALAN = "Katalanska", "ca"
    KAZAKH = "Kazakiska", "kk"
    AZERBAIJANI = "Azerbajdzjanska", "az"
    SERBIAN = "Serbiska", "sr"
    CROATIAN = "Kroatiska", "hr"
    BOSNIAN = "Bosniska", "bs"
    ESTONIAN = "Estniska", "et"
    LATVIAN = "Lettiska", "lv"
    LITHUANIAN = "Litauiska", "lt"
    SOMALI = "Somaliska", "so"


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
    AFTERNOON_TEA = "Afternoon Tea"
    RECORDED_THEATRE = "Inspelad teater"
    KNATTEBIO = "Knattebio"
    BOOK_CLUB = "Bokklubb"
    BIOPASSET = "Biopasset"
    CINEVILLE = "Cineville"
    NEW_FINNISH_FILM = "Ny finsk film"
    QA = "Frågestund"
    DIRECTOR_QA = "Regissörssamtal (teckenspråkstolkat)"
    FAMILY_CINEMA = "Familjebio"
    PREMIERE = "Premiär"
    PREVIEW = "Förhandsvisning"
    BIOVINO = "BioVino"
    PAWLIKOWSKI_SERIES = "3 x Pawlikowski"
    LIVE_ON_CINEMA = "Live på bio"
    CLASSIC = "Klassiker"
    FILM_INTRODUCTION = "Filmintroduktion"
    CHILDRENS_CINEMA = "Barnbio"


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
