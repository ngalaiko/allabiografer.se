"""Shared version vocabulary."""

import pytest

from store.version import speech_label, subtitles_label


@pytest.mark.parametrize(
    ("names", "speech", "subtitles"),
    [
        ([], "", ""),
        (["Engelska"], "Engelskt tal", "Engelsk text"),
        (["Engelska", "Franska"], "Engelskt, franskt tal", "Engelsk, fransk text"),
        (["Hindi"], "Tal på hindi", "Text på hindi"),
        (["Engelska", "Hindi"], "Tal på engelska, hindi", "Text på engelska, hindi"),
    ],
)
def test_labels(names, speech, subtitles):
    assert (speech_label(names), subtitles_label(names)) == (speech, subtitles)
