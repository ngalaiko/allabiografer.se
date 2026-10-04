"""Screening versions — site labels normalised to the values in ``store.version``.

Format defaults (2D, digital, 5.1/7.1 sound) and programme labels (Familj,
Klassiker…) are dropped.
"""

import re
import unicodedata

from store.version import (
    LANGUAGES,
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
    speech_label,
    subtitles_label,
)

NO_SPEECH = "Inget tal"
NO_SUBTITLES = "Ej textad"

# Spellings sites use for each format.
_FORMAT_SPELLINGS = {
    "IMAX": r"imax",
    "Dolby Cinema": r"dolby\s*cinema",
    "Dolby Atmos": r"(?:dolby\s*)?atmos",
    "4DX": r"4dx",
    "ScreenX": r"screen\s*x",
    "D-Box": r"d-?box",
    "iSense": r"isense",
    "Infinity Vision": r"infinity\s*vision",
    "3D": r"3d",
    "70 mm": r"70\s*mm",
    "35 mm": r"35\s*mm",
    "4K": r"4k",
    "Laser": r"laser",
    "XL": r"xl",
    "VIP": r"vip",
    "Syntolkning": r"syntolk\w*",
}
_FORMAT_PATTERNS = {
    tag: re.compile(rf"(?<![\w.]){pattern}(?!\w)", re.IGNORECASE) for tag, pattern in _FORMAT_SPELLINGS.items()
}

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
    "dk": "Danska",
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


_LANGUAGES = {name.casefold(): member for member in Language for name in (member.value,)}
_LANGUAGE_ALIASES = {
    "sv": Language.SWEDISH,
    "sve": Language.SWEDISH,
    "en": Language.ENGLISH,
    "eng": Language.ENGLISH,
    "fr": Language.FRENCH,
    "fre": Language.FRENCH,
    "de": Language.GERMAN,
    "ger": Language.GERMAN,
    "it": Language.ITALIAN,
    "es": Language.SPANISH,
    "jp": Language.JAPANESE,
    "ja": Language.JAPANESE,
    "ru": Language.RUSSIAN,
    "rus": Language.RUSSIAN,
    "nl": Language.DUTCH,
    "pl": Language.POLISH,
    "pt": Language.PORTUGUESE,
    "zh": Language.CHINESE,
    "dk": Language.DANISH,
    "swedish": Language.SWEDISH,
    "english": Language.ENGLISH,
    "french": Language.FRENCH,
    "german": Language.GERMAN,
    "italian": Language.ITALIAN,
    "spanish": Language.SPANISH,
    "japanese": Language.JAPANESE,
    "arabic": Language.ARABIC,
    "portuguese": Language.PORTUGUESE,
    "korean": Language.KOREAN,
    "chinese": Language.CHINESE,
    "cantonese": Language.CANTONESE,
    "finnish": Language.FINNISH,
    "norwegian": Language.NORWEGIAN,
    "danish": Language.DANISH,
    "icelandic": Language.ICELANDIC,
    "dutch": Language.DUTCH,
    "polish": Language.POLISH,
    "russian": Language.RUSSIAN,
    "ukrainian": Language.UKRAINIAN,
    "czech": Language.CZECH,
    "hungarian": Language.HUNGARIAN,
    "romanian": Language.ROMANIAN,
    "greek": Language.GREEK,
    "turkish": Language.TURKISH,
    "persian": Language.PERSIAN,
    "farsi": Language.PERSIAN,
    "kurdish": Language.KURDISH,
    "hebrew": Language.HEBREW,
    "thai": Language.THAI,
    "vietnamese": Language.VIETNAMESE,
    "georgian": Language.GEORGIAN,
    "catalan": Language.CATALAN,
    "serbian": Language.SERBIAN,
    "croatian": Language.CROATIAN,
    "bosnian": Language.BOSNIAN,
    "estonian": Language.ESTONIAN,
    "latvian": Language.LATVIAN,
    "lithuanian": Language.LITHUANIAN,
    "somali": Language.SOMALI,
}


def _typed_languages(text: str) -> frozenset[Language]:
    words = _words(text)
    found: set[Language] = set()
    for word in words:
        alias = _LANGUAGE_ALIASES.get(word)
        if alias:
            found.add(alias)
            continue
        # Prefixes and Swedish language adjectives are common in title suffixes.
        candidates = [lang for lang in Language if lang.value.casefold().startswith(word)] if len(word) >= 2 else []
        if len(candidates) == 1:
            found.add(candidates[0])
        elif word.endswith("t"):
            candidates = [lang for lang in Language if lang.value.casefold().startswith(word[:-1])]
            if len(candidates) == 1:
                found.add(candidates[0])
    return frozenset(found)


def languages(text: str) -> frozenset[Language]:
    """Canonical language set for film metadata."""
    return _typed_languages(text)


def title_suffixes(title: str) -> tuple[str, ...]:
    """Raw trailing version tags, excluding ordinary title words."""
    suffixes: list[str] = []
    while match := _TAIL.search(title):
        suffixes.insert(0, match.group(0))
        title = title[: match.start()]
    return tuple(suffixes)


def normalize(
    *texts: str,
    audio_text: str | None = None,
    subtitle_text: str | None = None,
    audio_role_text: str | None = None,
) -> tuple[ContentVersion, Presentation, Accessibility]:
    """Extract typed version, presentation, and accessibility facts."""
    joined = " ".join(t for t in (*texts, audio_text or "", subtitle_text or "") if t)
    inferred_audio: list[str] = []
    inferred_subs: list[str] = []
    for text in texts:
        remainder = text
        while m := _TAIL.search(remainder):
            if m.group("lang"):
                inferred_audio.append(m.group(0))
            elif m.group("subs") or m.group("unsub"):
                inferred_subs.append(m.group(0))
            elif m.group("role"):
                inferred_audio.append(m.group(0))
            remainder = remainder[: m.start()]
    if audio_text is None and not inferred_audio:
        for text in texts:
            if re.search(
                r"\b(?:original(?:språk|version)?|dubb(?:ad|at|ed|ing)|silent|stumfilm|talspråk|audio)\b",
                text,
                re.IGNORECASE,
            ):
                audio_part = re.sub(r"\b[\wåäöÅÄÖ-]+\s+(?:subtitles?|undertexter?)\b", "", text, flags=re.IGNORECASE)
                audio_part = re.split(
                    r"\b(?:subtitles?|undertexter?|textad|textat|text:)\b", audio_part, maxsplit=1, flags=re.IGNORECASE
                )[0]
                inferred_audio.append(audio_part)
    if subtitle_text is None and not inferred_subs:
        for text in texts:
            text_words = _words(text)
            if _UNSUBTITLED.intersection(text_words) and any(
                w in {"text", "textad", "textat", "undertext", "undertexter", "subtitle", "subtitles"}
                for w in text_words
            ):
                inferred_subs.append(text)
                continue
            preceding = re.search(r"\b([\wåäöÅÄÖ-]+)\s+(?:subtitles?|undertexter?)\b", text, re.IGNORECASE)
            if preceding:
                inferred_subs.append(preceding.group(1))
                continue
            match = re.search(
                r"\b(?:subtitles?|undertexter?|textad|textat|text:)\b\s*[:,-]?\s*(.*)$", text, re.IGNORECASE
            )
            if match:
                inferred_subs.append(match.group(1))
    aud = audio_text if audio_text is not None else " ".join(inferred_audio)
    subs = subtitle_text if subtitle_text is not None else " ".join(inferred_subs)
    aud_words = _words(aud)
    sub_words = _words(subs)

    kind = AudioKind.UNKNOWN
    role_words = set(aud_words) | set(_words(audio_role_text or ""))
    if _SILENT.intersection(role_words) or "silent" in role_words:
        kind = AudioKind.SILENT
    elif any(w in {"dubbad", "dubbat", "dubbas", "dubbning", "dubbed", "dubbing"} for w in role_words):
        kind = AudioKind.DUBBED
    elif "original" in role_words or "originalversion" in role_words or "originalspråk" in role_words:
        kind = AudioKind.ORIGINAL
    audio = AudioVersion(kind, _typed_languages(aud))

    subtitle_languages: frozenset[Language] | None = _typed_languages(subs)
    if not subs.strip():
        subtitle_languages = None
    elif _UNSUBTITLED.intersection(sub_words) or re.search(r"\b(?:no|without)\s+subtitles?\b", subs, re.IGNORECASE):
        subtitle_languages = frozenset()
    elif not subtitle_languages:
        subtitle_languages = None
    subtitles_value = SubtitleVersion(subtitle_languages)
    version = ContentVersion(audio, subtitles_value)

    experiences = frozenset(
        system
        for system, label in (
            (PresentationSystem.IMAX, "IMAX"),
            (PresentationSystem.DOLBY_CINEMA, "Dolby Cinema"),
            (PresentationSystem.FOUR_DX, "4DX"),
            (PresentationSystem.SCREENX, "ScreenX"),
            (PresentationSystem.D_BOX, "D-Box"),
            (PresentationSystem.ISENSE, "iSense"),
            (PresentationSystem.INFINITY_VISION, "Infinity Vision"),
        )
        if _FORMAT_PATTERNS[label].search(joined)
    )
    dimension = (
        Dimension.THREE_D
        if _FORMAT_PATTERNS["3D"].search(joined)
        else Dimension.TWO_D
        if re.search(r"(?<!\w)2d(?!\w)", joined, re.IGNORECASE)
        else Dimension.UNKNOWN
    )
    medium = (
        ProjectionMedium.MM_70
        if _FORMAT_PATTERNS["70 mm"].search(joined)
        else ProjectionMedium.MM_35
        if _FORMAT_PATTERNS["35 mm"].search(joined)
        else ProjectionMedium.DIGITAL
        if re.search(r"\bdigital\b", joined, re.IGNORECASE)
        else ProjectionMedium.UNKNOWN
    )
    projection = frozenset(
        attr
        for attr, label in ((ProjectionAttribute.K4, "4K"), (ProjectionAttribute.LASER, "Laser"))
        if _FORMAT_PATTERNS[label].search(joined)
    )
    sound = frozenset({SoundAttribute.DOLBY_ATMOS}) if _FORMAT_PATTERNS["Dolby Atmos"].search(joined) else frozenset()
    auditorium = frozenset(
        attr
        for attr, label in ((AuditoriumAttribute.XL, "XL"), (AuditoriumAttribute.VIP, "VIP"))
        if _FORMAT_PATTERNS[label].search(joined)
    )
    presentation = Presentation(experiences, dimension, medium, projection, sound, auditorium)
    accessibility = Accessibility(
        frozenset({AccessibilityFeature.AUDIO_DESCRIPTION})
        if _FORMAT_PATTERNS["Syntolkning"].search(joined)
        else frozenset()
    )
    return version, presentation, accessibility


def screening_facts(
    *,
    format: str = "",
    language: str = "",
    subtitles: str = "",
    audio_role_text: str = "",
    source_texts: tuple[str, ...] = (),
    raw_attributes: tuple[str, ...] = (),
) -> dict[str, object]:
    """Structured Screening keyword fields for parsers holding normalized labels."""
    version, presentation, accessibility = normalize(
        format,
        audio_text=language or None,
        subtitle_text=subtitles or None,
        audio_role_text=audio_role_text or None,
    )
    if source_texts:
        fallback_version, fallback_presentation, fallback_accessibility = normalize(*source_texts)
        version = ContentVersion(
            audio=AudioVersion(
                version.audio.kind if version.audio.kind is not AudioKind.UNKNOWN else fallback_version.audio.kind,
                version.audio.languages or fallback_version.audio.languages,
            ),
            subtitles=SubtitleVersion(
                version.subtitles.languages
                if version.subtitles.languages is not None
                else fallback_version.subtitles.languages
            ),
            edition=version.edition or fallback_version.edition,
        )
        presentation = Presentation(
            experiences=presentation.experiences or fallback_presentation.experiences,
            dimension=presentation.dimension
            if presentation.dimension is not Dimension.UNKNOWN
            else fallback_presentation.dimension,
            medium=presentation.medium
            if presentation.medium is not ProjectionMedium.UNKNOWN
            else fallback_presentation.medium,
            projection=presentation.projection or fallback_presentation.projection,
            sound=presentation.sound or fallback_presentation.sound,
            auditorium=presentation.auditorium or fallback_presentation.auditorium,
        )
        accessibility = Accessibility(accessibility.features | fallback_accessibility.features)
    return {
        "version": version,
        "presentation": presentation,
        "accessibility": accessibility,
        "raw_attributes": raw_attributes,
    }


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    return [w for w in re.split(r"[\s,.:/()-]+", text) if re.search(r"[^\W\d_]", w)]


def _name(word: str) -> str | None:
    """Language name for a word, code or adjective; None when unknown or ambiguous."""
    alias = _LANGUAGE_ALIASES.get(word)
    if alias is not None:
        return alias.value
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
    r"(?:^|\s+)(?:[-–]\s*)?\(?\s*(?:"
    rf"(?P<lang>{_LANG_WORD})\.?\s*(?:tal(?:\s*\(?\s*(?:dubbat|dubbad|dubbed)\s*\)?)?|(?:original|originalversion)|\(?\s*(?:dubbad|dubbat|dubbed)\s*\)?)"
    rf"|(?P<subs>{_LANG_WORD})\.?\s*(?:txt|text)"
    r"|(?P<unsub>otextad|ej\s+textad|no\s+subtitles?)"
    r"|(?P<role>original(?:version|språk)?|dubbad|dubbat|dubbed|silent|stumfilm)"
    r"|(?P<fmt>imax®?|dolby\s*cinema|(?:dolby\s*)?atmos|3d|2d|4dx|screen\s*x|d-?box|isense|infinity\s*vision|35\s*mm|70\s*mm|4k|2k|laser|digital|vip|xl|syntolk\w*)"
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
        elif m.group("role"):
            # The structured normalizer consumes audio roles; this legacy split has no role field.
            pass
        else:
            fmts.insert(0, m.group("fmt"))
        title = title[: m.start()]
    return title.strip(), formats(*fmts), spoken, subs


# Labels that open a stated version: "Originalspråk:", "Språk:", "Tal:", "Undertexter:", "Language:", "Subtitles:".
_TEXT_LABEL = re.compile(
    r"(?:original)?språk\s*:|\btal\s*:|undertext(?:er)?\s*:|\blanguage\s*:|\bsubtitles?\s*:", re.IGNORECASE
)
# Words that switch from spoken to subtitle languages: "med svensk text", "textad på svenska", "Subtitles:".
_TEXT_SUBTITLE_WORDS = {"text", "textad", "textat", "undertext", "undertexter", "med", "subtitle", "subtitles"}
_TEXT_SKIP = {"språk", "originalspråk", "tal", "och", "på", "dubbat", "dubbad", "language", "and"}


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
