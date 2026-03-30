"""Cinema site parsers.

Every module exposes::

    def parse() -> Iterator[Screening | Venue]
"""

from collections.abc import Iterator
from typing import Protocol

from store import Screening, Venue

type ParseResult = Screening | Venue


class Parser(Protocol):
    """Protocol that every parser module must satisfy."""

    def parse(self) -> Iterator[ParseResult]: ...
