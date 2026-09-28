"""Age ratings — site and TMDB wording normalised to ``store.version.AgeRating``."""

import re
import unicodedata

from store.version import AgeRating

_BY_AGE = {7: AgeRating.FROM_7, 11: AgeRating.FROM_11, 15: AgeRating.FROM_15, 18: AgeRating.FROM_18}
# "BTL", "Bt", "Barntillåten", "Ingen åldersgräns", TMDB's "G".
_ALL = re.compile(r"^(?:btl?|g|0)$|barntill|ingen åldersgräns", re.IGNORECASE)
# The first age states the limit; "7 år med vuxen" only restates the accompanied rule.
_AGE = re.compile(r"\d+")


def age_rating(raw: str) -> str:
    """AgeRating value for "15 år", "Fr.15 år", "15-årsgräns", "P15", "Btl"…; "" when unrated."""
    text = " ".join(unicodedata.normalize("NFC", raw or "").split())
    if _ALL.search(text):
        return AgeRating.ALL
    m = _AGE.search(text)
    return _BY_AGE.get(int(m.group()), "") if m else ""
