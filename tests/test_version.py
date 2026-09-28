"""Screening version normalisation shared by parsers."""

import pytest

from parse import _version


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
