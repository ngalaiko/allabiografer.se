"""Verified Tickster cinema organisers not already covered by another source."""

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)
_BASE = "https://www.tickster.com/se/sv/events/by/"


@dataclass(frozen=True)
class _Site:
    organiser: str
    name: str
    city: str
    venue: str = ""


# Do not add cinemas already imported via bio.se, Cinemascenen, BioSverige, etc.
# Some organisers also sell tickets for concerts, theatre and other venues.
_SITES = (
    _Site("8efk0t38a63ealr/kulturhuset-finspang", "Kulturhuset Finspång", "Finspång"),
    _Site("mxrn1p8013ak53k/emmaboda-folketshus", "Emmaboda Folkets Hus", "Emmaboda"),
    _Site("r81ewlrj3upvvm7/storm", "Storm", "Grebbestad"),
    _Site("6fyy0bjpl74d6r5/florabiografen", "Flora Biografteater", "Sjöbo"),
    _Site("z46gh66v0v951ac/bobo-film", "Biograf Aniara", "Gnesta"),
    _Site("cm4wj7hhvxmhhb8/vilhelmina-f-h", "Vilhelmina Folkets Hus", "Vilhelmina"),
    _Site("57775z43gv88xrk/folkets-hus-sater", "Folkets Hus Säter", "Säter", "Biosalongen"),
    _Site("tntfe5rzu5zybfl/folketshus-alvsbyn", "Folkets Hus Älvsbyn", "Älvsbyn", "Andromeda"),
    _Site("agd4gkadcmcxeeg/metropol-kultur", "Metropol Kultur", "Karlshamn"),
    _Site("1m4h76jn8pvw8b0/ersboda-folkets-hus", "Ersboda Folkets Hus", "Umeå"),
    _Site("3gaa3vubd6a3yr5/skarpnacks-kulturhus", "Skarpnäcks Kulturhus", "Skarpnäck", "A-salen"),
)

_NOT_A_SHOWING = re.compile(r"presentkort|medlemskort|säsongskort|abonnemang|\bmall\b", re.IGNORECASE)
_PREFIX = re.compile(r"^(Knattebio|Barnbio|Familjebio|Dagbio|Bio)\s*[:-]\s*", re.IGNORECASE)
_SUFFIX = re.compile(r"\s+-\s+(Lunchbio|Dagbio)$", re.IGNORECASE)
_SCREEN = re.compile(r"\s+sal\s*(\d+)$", re.IGNORECASE)
# Explicit film lengths, not durations mentioned in a synopsis or the event slot.
_RUNTIME = re.compile(
    r"\b(?:(?P<label>speltid|längd)\s*:\s*|(?:filmen|den)\s+är\s+)"
    r"(?:(?P<hours>\d+)\s*tim(?:me|mar)?\b\s*(?:och\s+)?)?"
    r"(?:(?P<minutes>\d+)\s*min(?:uter)?\b)?(?P<long>\s*lång\b)?",
    re.IGNORECASE,
)


def _runtime(overview: str) -> int | None:
    for match in _RUNTIME.finditer(overview):
        if not (match.group("label") or match.group("long")):
            continue
        minutes = int(match.group("hours") or 0) * 60 + int(match.group("minutes") or 0)
        if minutes:
            return minutes
    return None
