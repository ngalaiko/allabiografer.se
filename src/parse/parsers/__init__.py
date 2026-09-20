"""Cinema site parsers.

Every module exposes::

    def parse() -> Iterator[Screening | Venue | Film]
"""

from collections.abc import Iterator
from typing import Protocol

from store import Film, Screening, Venue

type ParseResult = Screening | Venue | Film


class Parser(Protocol):
    """Protocol that every parser module must satisfy."""

    def parse(self) -> Iterator[ParseResult]: ...
