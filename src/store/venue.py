"""The Venue value object — metadata about a cinema venue."""

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True, kw_only=True)
class Venue:
    """A cinema venue."""

    name: str
    city: str
    address: str = ""

    def to_dict(self) -> dict[str, str]:
        d: dict[str, str] = {"name": self.name, "city": self.city}
        if self.address:
            d["address"] = self.address
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            name=d["name"],
            city=d["city"],
            address=d.get("address", ""),
        )
