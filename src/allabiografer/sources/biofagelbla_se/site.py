"""The cinema's own dated programme, including its session-specific ticket links."""

import re

_RUNTIME = re.compile(r"(?:(\d+)h(?: (\d+) mins?)?|(\d+) mins?)")
