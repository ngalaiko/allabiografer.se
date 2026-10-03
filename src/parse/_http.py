"""HTTP session with retries for transient failures."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "Mozilla/5.0 (compatible; bio-parser/1.0)"

_TOTAL = 5
_BACKOFF = 1.0
_STATUSES = (429, 500, 502, 503, 504)


def session(user_agent: str = USER_AGENT) -> requests.Session:
    """Session retrying connection errors, timeouts and 429/5xx with exponential backoff."""
    retry = Retry(
        total=_TOTAL,
        backoff_factor=_BACKOFF,
        status_forcelist=_STATUSES,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s = requests.Session()
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers["User-Agent"] = user_agent
    return s
