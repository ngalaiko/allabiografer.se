"""Valid screening version and rating values — what parse stores and build shows.

Screening fields hold these values verbatim:

    format      Format members joined by ", " in declaration order
    language    speech label: "Engelskt tal", "Engelskt, franskt tal", NO_SPEECH
    subtitles   subtitle label: "Svensk text", "Svensk, engelsk text", NO_SUBTITLES

Film and movie ``age_rating`` holds an AgeRating value or "".
"""

from enum import StrEnum


class Format(StrEnum):
    """Presentation formats, in display order."""

    IMAX = "IMAX"
    DOLBY_CINEMA = "Dolby Cinema"
    DOLBY_ATMOS = "Dolby Atmos"
    FOUR_DX = "4DX"
    SCREENX = "ScreenX"
    D_BOX = "D-Box"
    ISENSE = "iSense"
    INFINITY_VISION = "Infinity Vision"
    THREE_D = "3D"
    MM_70 = "70 mm"
    MM_35 = "35 mm"
    K4 = "4K"
    LASER = "Laser"
    XL = "XL"
    VIP = "VIP"
    AUDIO_DESCRIPTION = "Syntolkning"


class AgeRating(StrEnum):
    """Swedish cinema age limits."""

    ALL = "Barntillåten"
    FROM_7 = "Från 7 år"
    FROM_11 = "Från 11 år"
    FROM_15 = "Från 15 år"
    FROM_18 = "Från 18 år"


LANGUAGES = (
    "Svenska",
    "Engelska",
    "Franska",
    "Tyska",
    "Italienska",
    "Spanska",
    "Portugisiska",
    "Japanska",
    "Koreanska",
    "Kinesiska",
    "Mandarin",
    "Kantonesiska",
    "Finska",
    "Norska",
    "Danska",
    "Isländska",
    "Nederländska",
    "Polska",
    "Ryska",
    "Ukrainska",
    "Tjeckiska",
    "Ungerska",
    "Rumänska",
    "Grekiska",
    "Turkiska",
    "Arabiska",
    "Persiska",
    "Kurdiska",
    "Hebreiska",
    "Hindi",
    "Kannada",
    "Tamil",
    "Telugu",
    "Thailändska",
    "Vietnamesiska",
    "Georgiska",
    "Katalanska",
    "Kazakiska",
    "Azerbajdzjanska",
    "Serbiska",
    "Kroatiska",
    "Bosniska",
    "Estniska",
    "Lettiska",
    "Litauiska",
    "Somaliska",
)

NO_SPEECH = "Inget tal"
NO_SUBTITLES = "Ej textad"


def _label(names: list[str], ending: str, noun: str) -> str:
    """["Engelska", "Franska"] → "Engelsk{ending}, fransk{ending} {noun}"; ["Hindi"] → "{Noun} på hindi"."""
    if not names:
        return ""
    # Only "-ska" names have an adjective form.
    if not all(name.endswith("ska") for name in names):
        return f"{noun.capitalize()} på " + ", ".join(name.lower() for name in names)
    words = [name[:-1] + ending for name in names]
    return ", ".join([words[0], *(w.lower() for w in words[1:])]) + " " + noun


def speech_label(names: list[str]) -> str:
    """["Engelska"] → "Engelskt tal"; ["Mandarin"] → "Tal på mandarin"."""
    return _label(names, "t", "tal")


def subtitles_label(names: list[str]) -> str:
    """["Svenska"] → "Svensk text"; ["Hindi"] → "Text på hindi"."""
    return _label(names, "", "text")
