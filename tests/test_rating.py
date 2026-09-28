"""Age rating normalisation shared by parsers."""

import pytest

from parse._rating import age_rating
from store.version import AgeRating


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Barntillåten", AgeRating.ALL),
        ("BTL", AgeRating.ALL),
        ("Btl", AgeRating.ALL),
        ("Bt", AgeRating.ALL),
        ("G", AgeRating.ALL),
        ("Ingen åldersgräns", AgeRating.ALL),
        ("Från 7år", AgeRating.FROM_7),
        ("7+", AgeRating.FROM_7),
        ("7 år", AgeRating.FROM_7),
        ("11", AgeRating.FROM_11),
        ("11-årsgräns", AgeRating.FROM_11),
        ("11 år · 7 år med vuxen", AgeRating.FROM_11),
        ("15 år · 11 med vuxen", AgeRating.FROM_15),
        ("Fr.15 år", AgeRating.FROM_15),
        ("P15", AgeRating.FROM_15),
        ("15+", AgeRating.FROM_15),
        ("Från 18 år", AgeRating.FROM_18),
        ("", ""),
        ("-", ""),
        ("Ej angivet", ""),
        ("Ej granskad", ""),
        ("Åldersgräns ej granskad", ""),
        ("Ej bestämd", ""),
        ("NR", ""),
        # Not a Swedish age limit.
        ("Från 4 år", ""),
    ],
)
def test_age_rating(raw, expected):
    assert age_rating(raw) == expected
