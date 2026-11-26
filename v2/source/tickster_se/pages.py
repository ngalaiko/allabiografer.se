"""Save Tickster and linked cinema HTML for later replay through the v1 parsers."""

import logging
from datetime import datetime

import requests

from .._shared import STOCKHOLM, movie_fields, stable_key

log = logging.getLogger(__name__)


class Pages:
    """A disk-only client by default; fetch explicitly supplies a live session."""

    def __init__(self, inputs, session=None):
        self.inputs = inputs
        self.session = session

    def filename(self, url):
        return f"page-{stable_key(url)}.html"

    def get(self, url, timeout=30):
        path = self.inputs / self.filename(url)
        failure = path.with_suffix(".failure.txt")
        if failure.exists():
            raise requests.RequestException(failure.read_text(encoding="utf-8"))
        if self.session is not None and not path.exists():
            try:
                response = self.session.get(url, timeout=timeout)
                path.write_bytes(response.content)
                response.raise_for_status()
            except requests.RequestException as error:
                failure.write_text(f"{url}: {error}\n", encoding="utf-8")
                raise
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response.encoding = "utf-8"
        response._content = path.read_bytes()
        return response

    def text(self, url, *, optional=False):
        try:
            return self.get(url).text
        except requests.RequestException as error:
            if not optional:
                raise
            log.warning("Unavailable page %s: %s", url, error)
            return ""


def capture_day(inputs):
    return datetime.fromtimestamp(int(inputs.parents[1].name), STOCKHOLM).date()


def year_for_month(today, month):
    # Match v1's year inference, anchored to the capture day rather than replay time.
    if month == (today.month - 2) % 12 + 1:
        return today.year - (today.month == 1)
    return today.year + (month < today.month)


def source_movie(title, url, details):
    fields = movie_fields(
        title,
        url,
        details.get("overview"),
        details.get("runtime"),
        year=details.get("release_date"),
        alternate=details.get("title_original"),
    )
    if not url:
        fields.pop("url")
    for key, field in (("age_rating", "contentRating"), ("genres", "genre"), ("poster_url", "image")):
        if value := details.get(key):
            fields[field] = value
    return fields
