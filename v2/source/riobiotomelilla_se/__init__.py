"""Rio Tomelilla's capture format."""

import json
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://riobiotomelilla.se"
STOCKHOLM = ZoneInfo("Europe/Stockholm")
SOURCE = "riobiotomelilla_se"


def response_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_bytes())
    if payload["resultCode"] != 0:
        raise ValueError(f"{path.name} returned resultCode {payload['resultCode']}")
    return payload["data"]
