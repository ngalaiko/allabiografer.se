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
        ("Engelska", "Engelska"),
        ("Eng.", "Engelska"),
        ("ENG", "Engelska"),
        ("En", "Engelska"),
        ("Engelskt tal", "Engelska"),
        ("Svenska (dubbad)", "Svenska"),
        ("Sv.", "Svenska"),
        ("SV", "Svenska"),
        ("Sve", "Svenska"),
        ("Italienskt", "Italienska"),
        ("It.", "Italienska"),
        ("ES", "Spanska"),
        ("Spa", "Spanska"),
        ("JP", "Japanska"),
        ("Rus", "Ryska"),
        ("Eng, fr, ty", "Engelska, Franska, Tyska"),
        ("Eng. Fr. Ty.", "Engelska, Franska, Tyska"),
        ("Arabiska, spanska", "Arabiska, Spanska"),
        ("Inget talspråk", "Inget tal"),
        ("STUM", "Inget tal"),
        ("Okänd", ""),
        ("Mandarin", "Mandarin"),
    ],
)
def test_language(raw, expected):
    assert _version.language(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sv. ", "Svenska"),
        ("Svensk text", "Svenska"),
        ("SV/ENG", "Svenska, Engelska"),
        ("Ej", "Otextad"),
        ("Ej textad", "Otextad"),
        ("Ingen text", "Otextad"),
        ("Otextad", "Otextad"),
    ],
)
def test_subtitles(raw, expected):
    assert _version.subtitles(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tony", ("Tony", "", "", "")),
        ("Bortglömda ön eng. tal ATMOS", ("Bortglömda ön", "Dolby Atmos", "Engelska", "")),
        ("Bortglömda ön sv. tal", ("Bortglömda ön", "", "Svenska", "")),
        ("Minioner & Monster SV.tal", ("Minioner & Monster", "", "Svenska", "")),
        ("Fårdetektiverna Sv tal", ("Fårdetektiverna", "", "Svenska", "")),
        ("Kikis expressbud jap. tal 4K", ("Kikis expressbud", "4K", "Japanska", "")),
        ("Kikis expressbud sv tal 2K", ("Kikis expressbud", "", "Svenska", "")),
        ("Kikis expressbud (Sv. tal)", ("Kikis expressbud", "", "Svenska", "")),
        ("In The Mood For Love - 35 mm", ("In The Mood For Love", "35 mm", "", "")),
        ("Irma Vep 35mm", ("Irma Vep", "35 mm", "", "")),
        ("Avengers: Endgame Encore IMAX", ("Avengers: Endgame Encore", "IMAX", "", "")),
        ("Resident Evil - IMAX®", ("Resident Evil", "IMAX", "", "")),
        ("Hamnet ATMOS", ("Hamnet", "Dolby Atmos", "", "")),
        ("Mad Max (otextad)", ("Mad Max", "", "", "Otextad")),
        (
            "Bajsfilmen - Dolores och Gunellens värld (Sv. txt)",
            ("Bajsfilmen - Dolores och Gunellens värld", "", "", "Svenska"),
        ),
        ("Lilla Amélie eller tecknet för regn Fr. tal", ("Lilla Amélie eller tecknet för regn", "", "Franska", "")),
        ("Your Name. (Jap. tal)", ("Your Name.", "", "Japanska", "")),
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
