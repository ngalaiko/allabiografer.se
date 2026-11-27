"""Rio Tomelilla's capture format."""

import json
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from pathlib import Path

BASE = "https://riobiotomelilla.se"
STOCKHOLM = ZoneInfo("Europe/Stockholm")
SOURCE = "riobiotomelilla_se"
# The website the adapter reads, naming its actions and datasets.
SITE = "riobiotomelilla.se"


def response_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_bytes())
    if payload["resultCode"] != 0:
        raise ValueError(f"{path.name} returned resultCode {payload['resultCode']}")
    return payload["data"]
