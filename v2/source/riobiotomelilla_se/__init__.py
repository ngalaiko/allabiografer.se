"""Rio Tomelilla's on-disk capture format."""

import json
from pathlib import Path
from time import time
from zoneinfo import ZoneInfo

BASE = "https://riobiotomelilla.se"
STOCKHOLM = ZoneInfo("Europe/Stockholm")
SOURCE = "riobiotomelilla_se"


def new_source(root: Path, stage: str) -> Path:
    return root / stage / str(int(time())) / "sources" / SOURCE


def response_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_bytes())
    if payload["resultCode"] != 0:
        raise ValueError(f"{path.name} returned resultCode {payload['resultCode']}")
    return payload["data"]
