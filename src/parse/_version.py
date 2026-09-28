"""Screening versions — site labels normalised to the values in ``store.version``.

Format defaults (2D, digital, 5.1/7.1 sound) and programme labels (Familj,
Klassiker…) are dropped.
"""

import re
import unicodedata

from store.version import LANGUAGES, NO_SPEECH, NO_SUBTITLES, Format, speech_label, subtitles_label

# Spellings sites use for each format.
_FORMAT_SPELLINGS: dict[Format, str] = {
    Format.IMAX: r"imax",
    Format.DOLBY_CINEMA: r"dolby\s*cinema",
    Format.DOLBY_ATMOS: r"(?:dolby\s*)?atmos",
    Format.FOUR_DX: r"4dx",
    Format.SCREENX: r"screen\s*x",
    Format.D_BOX: r"d-?box",
    Format.ISENSE: r"isense",
    Format.INFINITY_VISION: r"infinity\s*vision",
    Format.THREE_D: r"3d",
    Format.MM_70: r"70\s*mm",
    Format.MM_35: r"35\s*mm",
    Format.K4: r"4k",
    Format.LASER: r"laser",
    Format.XL: r"xl",
    Format.VIP: r"vip",
    Format.AUDIO_DESCRIPTION: r"syntolk\w*",
}
_FORMAT_PATTERNS = {tag: re.compile(rf"(?<![\w.]){_FORMAT_SPELLINGS[tag]}(?!\w)", re.IGNORECASE) for tag in Format}

# Codes that are not a prefix of the language name.
_ALIASES = {
    "es": "Spanska",
    "jp": "Japanska",
    "ja": "Japanska",
    "ru": "Ryska",
    "rus": "Ryska",
    "de": "Tyska",
    "nl": "Nederländska",
    "pl": "Polska",
    "pt": "Portugisiska",
    "zh": "Kinesiska",
}
# Words around language names that carry no language.
_FILLER = {
    "tal",
    "talspråk",
    "text",
    "textad",
    "txt",
    "dubbad",
    "dubbat",
    "okänd",
    "olika",
    "flera",
    "tba",
    "tbc",
    "tbd",
}
_SILENT = {"inget", "stum", "stumfilm"}
_UNSUBTITLED = {"ej", "ingen", "inget", "otextad", "otextat"}


def formats(*texts: str) -> str:
    """Canonical format tags found in free-text labels."""
    joined = " , ".join(texts)
    return ", ".join(tag for tag, pattern in _FORMAT_PATTERNS.items() if pattern.search(joined))


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return [w for w in re.split(r"[\s,.:/()-]+", text) if re.search(r"[^\W\d_]", w)]


def _name(word: str) -> str | None:
    """Language name for a word, code or adjective; None when unknown or ambiguous."""
    if word in _ALIASES:
        return _ALIASES[word]
    if len(word) < 2:
        return None
    stems = [word, word[:-1]] if word.endswith("t") else [word]
    for stem in stems:
        matches = [name for name in LANGUAGES if name.casefold().startswith(stem)]
        if len(matches) == 1:
            return matches[0]
    return None


def _names(words: list[str]) -> list[str]:
    names: list[str] = []
    for word in words:
        if word in _FILLER:
            continue
        name = _name(word) or (word.capitalize() if len(word) > 1 else "")
        if name and name not in names:
            names.append(name)
    return names


def language(text: str) -> str:
    """Speech label from a site's language field."""
    words = _words(text)
    if _SILENT.intersection(words):
        return NO_SPEECH
    return speech_label(_names(words))


def subtitles(text: str) -> str:
    """Subtitle label from a site's subtitle field."""
    words = _words(text)
    if _UNSUBTITLED.intersection(words):
        return NO_SUBTITLES
    return subtitles_label(_names(words))


_LANG_WORD = r"[^\W\d_]+"
# Trailing version tags: "sv. tal", "(Eng. tal)", "(Sv. txt)", "(otextad)", "- 35 mm", "ATMOS".
_TAIL = re.compile(
    r"\s+(?:[-–]\s*)?\(?\s*(?:"
    rf"(?P<lang>{_LANG_WORD})\.?\s*tal"
    rf"|(?P<subs>{_LANG_WORD})\.?\s*(?:txt|text)"
    r"|(?P<unsub>otextad)"
    r"|(?P<fmt>imax®?|(?:dolby\s*)?atmos|3d|2d|4dx|screen\s*x|35\s*mm|70\s*mm|4k|2k)"
    r")\s*\)?$",
    re.IGNORECASE,
)


def split_title(title: str) -> tuple[str, str, str, str]:
    """Split trailing version tags off a title: (title, formats, language, subtitles)."""
    fmts: list[str] = []
    spoken = subs = ""
    while m := _TAIL.search(title):
        if m.group("lang"):
            name = _name(m.group("lang").casefold())
            if name is None:
                break
            spoken = spoken or speech_label([name])
        elif m.group("subs"):
            name = _name(m.group("subs").casefold())
            if name is None:
                break
            subs = subs or subtitles_label([name])
        elif m.group("unsub"):
            subs = subs or NO_SUBTITLES
        else:
            fmts.insert(0, m.group("fmt"))
        title = title[: m.start()]
    return title.strip(), formats(*fmts), spoken, subs


# Labels that open a stated version: "Originalspråk:", "Språk:", "Tal:", "Undertexter:".
_TEXT_LABEL = re.compile(r"(?:original)?språk\s*:|\btal\s*:|undertext(?:er)?\s*:", re.IGNORECASE)
# Words that switch from spoken to subtitle languages: "med svensk text", "textad på svenska".
_TEXT_SUBTITLE_WORDS = {"text", "textad", "textat", "undertext", "undertexter", "med"}
_TEXT_SKIP = {"språk", "originalspråk", "tal", "och", "på", "dubbat", "dubbad"}


def from_text(text: str) -> tuple[str, str]:
    """(language, subtitles) stated in a free-text description.

    Reads words after the first version label until one is neither a
    language nor a connector: "Originalspråk: Svenskt-tal, Svensk text."
    """
    # Sites mix composed and decomposed å/ä/ö.
    text = unicodedata.normalize("NFC", text)
    m = _TEXT_LABEL.search(text)
    if not m:
        return "", ""
    spoken: list[str] = []
    subs: list[str] = []
    target = spoken
    words = _words(text[m.start() :])
    for i, word in enumerate(words):
        following = words[i + 1] if i + 1 < len(words) else ""
        if word in _TEXT_SKIP:
            continue
        if word in _TEXT_SUBTITLE_WORDS:
            target = subs
            continue
        if target is subs and word in _UNSUBTITLED:
            subs.append(NO_SUBTITLES)
            continue
        name = _name(word)
        if name is None:
            break
        # "Svensk text": an adjective before "text" names subtitles; "Engelska Text:" opens a new label.
        (subs if following == "text" and not word.endswith("a") else target).append(name)
    spoken_label = speech_label(list(dict.fromkeys(spoken)))
    if NO_SUBTITLES in subs:
        return spoken_label, NO_SUBTITLES
    return spoken_label, subtitles_label(list(dict.fromkeys(subs)))
