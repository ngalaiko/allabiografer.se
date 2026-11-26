"""Bio Aspen's own film programme and per-screening booking links."""

import re

_RUNTIME = re.compile(r"(?:(\d+) tim(?: (\d+) min)?|(\d+) min)")
