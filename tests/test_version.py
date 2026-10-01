"""Screening version normalisation shared by parsers."""

import pytest

from parse import _version
from store.version import AudioKind, Dimension, ProjectionMedium


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("2D", ""),
        ("2D Digital", ""),
        ("Familj, 5.1", ""),
        ("IMAX, Laser", "IMAX, Laser"),
        ("7.1, XL - vår största duk", "XL"),
        ("Dolby Atmos", "Dolby Atmos"),
        ("ATMOS", "Dolby Atmos"),
        ("4DX 3D", "4DX, 3D"),
        ("4DX 2D, Klassiker, Infinity Vision", "4DX, Infinity Vision"),
        ("Infinity Vision, iSense", "iSense, Infinity Vision"),
        ("18år, 7.1, VIP-salong", "VIP"),
        ("Familj, Syntolkning via app", "Syntolkning"),
        ("70MM, XL - vår största duk", "70 mm, XL"),
        ("ScreenX", "ScreenX"),
        ("DBox, DolbyAtmos", "Dolby Atmos, D-Box"),
    ],
)
def test_formats(raw, expected):
    assert _version.formats(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("Engelska", "Engelskt tal"),
        ("Eng.", "Engelskt tal"),
        ("ENG", "Engelskt tal"),
        ("En", "Engelskt tal"),
        ("Engelskt tal", "Engelskt tal"),
        ("Svenska (dubbad)", "Svenskt tal"),
        ("Sv.", "Svenskt tal"),
        ("SV", "Svenskt tal"),
        ("Sve", "Svenskt tal"),
        ("Italienskt", "Italienskt tal"),
        ("It.", "Italienskt tal"),
        ("ES", "Spanskt tal"),
        ("Spa", "Spanskt tal"),
        ("JP", "Japanskt tal"),
        ("Rus", "Ryskt tal"),
        ("Eng, fr, ty", "Engelskt, franskt, tyskt tal"),
        ("Eng. Fr. Ty.", "Engelskt, franskt, tyskt tal"),
        ("Arabiska, spanska", "Arabiskt, spanskt tal"),
        ("Inget talspråk", "Inget tal"),
        ("STUM", "Inget tal"),
        ("Okänd", ""),
        ("Mandarin", "Tal på mandarin"),
    ],
)
def test_language(raw, expected):
    assert _version.language(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sv. ", "Svensk text"),
        ("Svensk text", "Svensk text"),
        ("SV/ENG", "Svensk, engelsk text"),
        ("Ej", "Ej textad"),
        ("Ej textad", "Ej textad"),
        ("Ingen text", "Ej textad"),
        ("Otextad", "Ej textad"),
        ("Hindi", "Text på hindi"),
    ],
)
def test_subtitles(raw, expected):
    assert _version.subtitles(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tony", ("Tony", "", "", "")),
        ("Bortglömda ön eng. tal ATMOS", ("Bortglömda ön", "Dolby Atmos", "Engelskt tal", "")),
        ("Bortglömda ön sv. tal", ("Bortglömda ön", "", "Svenskt tal", "")),
        ("Minioner & Monster SV.tal", ("Minioner & Monster", "", "Svenskt tal", "")),
        ("Fårdetektiverna Sv tal", ("Fårdetektiverna", "", "Svenskt tal", "")),
        ("Kikis expressbud jap. tal 4K", ("Kikis expressbud", "4K", "Japanskt tal", "")),
        ("Kikis expressbud sv tal 2K", ("Kikis expressbud", "", "Svenskt tal", "")),
        ("Kikis expressbud (Sv. tal)", ("Kikis expressbud", "", "Svenskt tal", "")),
        ("In The Mood For Love - 35 mm", ("In The Mood For Love", "35 mm", "", "")),
        ("Irma Vep 35mm", ("Irma Vep", "35 mm", "", "")),
        ("Avengers: Endgame Encore IMAX", ("Avengers: Endgame Encore", "IMAX", "", "")),
        ("Resident Evil - IMAX®", ("Resident Evil", "IMAX", "", "")),
        ("Hamnet ATMOS", ("Hamnet", "Dolby Atmos", "", "")),
        ("Mad Max (otextad)", ("Mad Max", "", "", "Ej textad")),
        (
            "Bajsfilmen - Dolores och Gunellens värld (Sv. txt)",
            ("Bajsfilmen - Dolores och Gunellens värld", "", "", "Svensk text"),
        ),
        ("Lilla Amélie eller tecknet för regn Fr. tal", ("Lilla Amélie eller tecknet för regn", "", "Franskt tal", "")),
        ("Your Name. (Jap. tal)", ("Your Name.", "", "Japanskt tal", "")),
        ("Avatar 3D", ("Avatar", "3D", "", "")),
        # Not version tags.
        (
            "Terminator 2: Judgment Day - 35th Anniversary",
            ("Terminator 2: Judgment Day - 35th Anniversary", "", "", ""),
        ),
        ("A Talent for Murder", ("A Talent for Murder", "", "", "")),
        ("UBUNTU: Timpi Tampa + samtal", ("UBUNTU: Timpi Tampa + samtal", "", "", "")),
        ("Sagan om ringen (1978)", ("Sagan om ringen (1978)", "", "", "")),
    ],
)
def test_split_title(raw, expected):
    assert _version.split_title(raw) == expected


@pytest.mark.parametrize("raw", ["TBA", "Tbc", "N/A"])
def test_placeholders_are_not_languages(raw):
    assert (_version.language(raw), _version.subtitles(raw)) == ("", "")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Åldersgräns: Barntillåten Originalspråk: Svenskt-tal, Svensk text. Eventuellt",
            ("Svenskt tal", "Svensk text"),
        ),
        ("Originalspråk: Engelskt-tal, Svensk text.", ("Engelskt tal", "Svensk text")),
        (
            "➤ Speltid : 82 min ➤ Språk: Svenska, Spanska ➤ Undertexter: Svenska, Engelska ➤ År",
            (
                "Svenskt, spanskt tal",
                "Svensk, engelsk text",
            ),
        ),
        ("En film om språk och kärlek.", ("", "")),
        ("Speltid: 96 minuter Språk: Engelska Text: Svenska Barntillåten", ("Engelskt tal", "Svensk text")),
        ("The Super Mario Galaxy Movie Tal: svenska (dubbat) Åldersgräns: Från 7 år", ("Svenskt tal", "")),
        ("Originalspråk: Engelskt-tal. Eventuellt kvarvarande biljetter", ("Engelskt tal", "")),
        ("Land: Sverige Språk: Svenska", ("Svenskt tal", "")),
        ("Språk: Norska och textad på svenska", ("Norskt tal", "Svensk text")),
        ("Språk: Arabiska och spanska med svensk text", ("Arabiskt, spanskt tal", "Svensk text")),
        ("Vid gala fick han vaska sitt tal och se sig besegrad.", ("", "")),
    ],
)
def test_from_text(text, expected):
    assert _version.from_text(text) == expected


def test_from_text_reads_decomposed_letters():
    assert _version.from_text("Språk: Svenska") == ("Svenskt tal", "")


def test_normalize_returns_structured_facts_and_keeps_non_variant_attributes():
    version, presentation, accessibility = _version.normalize("2D Digital Dolby Atmos Laser 4K VIP XL Syntolkning")

    assert presentation.dimension is Dimension.TWO_D
    assert presentation.medium is ProjectionMedium.DIGITAL
    assert presentation.sound == frozenset({"Dolby Atmos"})
    assert presentation.projection == frozenset({"Laser", "4K"})
    assert presentation.auditorium == frozenset({"VIP", "XL"})
    assert accessibility.features == frozenset({"Syntolkning"})
    assert version.audio.kind is AudioKind.UNKNOWN
    assert version.subtitles.languages is None


def test_normalize_classifies_experience_dimension_and_film_medium():
    _, imax, _ = _version.normalize("IMAX Laser")
    _, film, _ = _version.normalize("70mm XL")
    _, three_d, _ = _version.normalize("3D")

    assert imax.experiences == frozenset({"IMAX"})
    assert imax.projection == frozenset({"Laser"})
    assert film.medium is ProjectionMedium.MM_70
    assert film.auditorium == frozenset({"XL"})
    assert three_d.dimension is Dimension.THREE_D


def test_normalize_preserves_explicit_empty_subtitles_and_audio_kind():
    version, _, _ = _version.normalize(audio_text="Svenska dubbad", subtitle_text="Ej textad")

    assert version.audio.kind is AudioKind.DUBBED
    assert version.subtitles.languages == frozenset()


def test_normalize_leaves_unstated_values_unknown():
    version, presentation, _ = _version.normalize()

    assert version.audio.kind is AudioKind.UNKNOWN
    assert version.subtitles.languages is None
    assert presentation.dimension is Dimension.UNKNOWN
    assert presentation.medium is ProjectionMedium.UNKNOWN


def test_normalize_reads_roles_and_non_swedish_language_names():
    original, _, _ = _version.normalize(audio_text="Original English", subtitle_text="Swedish")
    dubbed, _, _ = _version.normalize(audio_text="English dubbed", subtitle_text="unknown")

    assert original.audio.kind is AudioKind.ORIGINAL
    assert original.audio.languages == frozenset({_version.Language.ENGLISH})
    assert original.subtitles.languages == frozenset({_version.Language.SWEDISH})
    assert dubbed.audio.kind is AudioKind.DUBBED
    assert dubbed.audio.languages == frozenset({_version.Language.ENGLISH})
    assert dubbed.subtitles.languages is None


def test_normalize_reads_suffix_language_without_inventing_subtitles():
    version, _, _ = _version.normalize("IMAX Laser Svenskt tal")

    assert version.audio.languages == frozenset({_version.Language.SWEDISH})
    assert version.subtitles.languages is None


def test_title_suffix_keeps_explicit_dub_marker():
    version, _, _ = _version.normalize(*_version.title_suffixes("Tony (Sv. tal) (dubbat)"))

    assert version.audio.kind is AudioKind.DUBBED
    assert version.audio.languages == frozenset({_version.Language.SWEDISH})


@pytest.mark.parametrize(
    ("raw", "title", "kind", "language"),
    [
        ("Vaiana Svenska (dubbad)", "Vaiana", AudioKind.DUBBED, _version.Language.SWEDISH),
        ("Vaiana (English original)", "Vaiana", AudioKind.ORIGINAL, _version.Language.ENGLISH),
    ],
)
def test_role_suffix_keeps_its_language(raw, title, kind, language):
    clean_title, *_ = _version.split_title(raw)
    version, _, _ = _version.normalize(*_version.title_suffixes(raw))

    assert clean_title == title
    assert version.audio.kind is kind
    assert version.audio.languages == frozenset({language})


def test_normalize_keeps_audio_and_subtitle_roles_explicit():
    audio, _, _ = _version.normalize("English audio")
    no_subtitles, _, _ = _version.normalize("Ej textad")

    assert audio.audio.languages == frozenset({_version.Language.ENGLISH})
    assert audio.audio.kind is AudioKind.UNKNOWN
    assert no_subtitles.subtitles.languages == frozenset()


def test_screening_facts_prefers_structured_values_over_title_suffixes():
    facts = _version.screening_facts(format="2D digital", source_texts=("3D", "70 mm"))
    presentation = facts["presentation"]

    assert presentation.dimension is Dimension.TWO_D
    assert presentation.medium is ProjectionMedium.DIGITAL


def test_normalize_understands_english_no_subtitles_marker():
    version, _, _ = _version.normalize(subtitle_text="English audio; no subtitles")

    assert version.subtitles.languages == frozenset()


def test_subtitle_role_does_not_set_audio_role():
    version, _, _ = _version.normalize(audio_text="Svenska", subtitle_text="Original Swedish subtitles")

    assert version.audio.kind is AudioKind.UNKNOWN
    assert version.audio.languages == frozenset({_version.Language.SWEDISH})
