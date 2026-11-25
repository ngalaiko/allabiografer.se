"""Rio Biografen Tomelilla's own booking programme."""

from collections.abc import Iterator

from parse.parsers.roxy_bio import parse_programme
from store import Film, Screening, Venue

_VENUE = Venue(name="Tomelilla Riobiografen", city="Tomelilla", address="Norregatan 3")
REPLACES_VENUES = (("bio_se", _VENUE.city, _VENUE.name),)


def parse() -> Iterator[Screening | Venue | Film]:
    yield from parse_programme("riobiotomelilla_se", "https://riobiotomelilla.se", 8, _VENUE, sound_71_id=2)
