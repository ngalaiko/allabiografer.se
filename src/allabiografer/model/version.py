"""Typed screening content and presentation facts."""

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
    DARI = "Dari", "prs"


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


class VideoFormat(StrEnum):
    """In display order: dimension, system, picture, film gauge."""

    TWO_D = "2D"
    THREE_D = "3D"
    IMAX = "IMAX"
    DOLBY_CINEMA = "Dolby Cinema"
    FOUR_DX = "4DX"
    SCREENX = "ScreenX"
    D_BOX = "D-Box"
    ISENSE = "iSense"
    INFINITY_VISION = "Infinity Vision"
    K4 = "4K"
    LASER = "Laser"
    MM_35 = "35 mm"
    MM_70 = "70 mm"


class AudioFormat(StrEnum):
    DOLBY_ATMOS = "Dolby Atmos"


@dataclass(frozen=True, slots=True)
class Presentation:
    video: frozenset[VideoFormat] = frozenset()
    audio: frozenset[AudioFormat] = frozenset()


type Format = VideoFormat | AudioFormat
_GAUGES = (VideoFormat.MM_35, VideoFormat.MM_70)
# Sound reads before the film gauge: "3D IMAX Dolby Atmos 70 mm".
_DISPLAY: tuple[Format, ...] = (
    *(value for value in VideoFormat if value not in _GAUGES),
    *AudioFormat,
    *_GAUGES,
)


def ordered(formats: frozenset[Format]) -> list[Format]:
    return [value for value in _DISPLAY if value in formats]


def formats(presentation: Presentation) -> list[Format]:
    """Video and audio formats in display order."""
    return ordered(presentation.video | presentation.audio)


FORMATS: dict[str, Format] = {value.value: value for value in _DISPLAY}


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
