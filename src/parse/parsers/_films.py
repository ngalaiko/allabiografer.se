"""Site-sourced film metadata for parsers — builds Films and stores their posters."""

import io
import logging
from pathlib import Path

import requests
from PIL import Image

from parse import _http
from parse._rating import age_rating
from store import DB_FILE, Film, film_key, has_poster, poster_key_for_film, write_poster

log = logging.getLogger(__name__)

# Database posters are written beside; the CLI points it at --output.
db_path: Path = DB_FILE

_MAX_BYTES = 8 * 1024 * 1024
# Wider posters are scaled down to this width and stored as JPEG.
_MAX_WIDTH = 1000

_session = _http.session()


def make(source: str, title: str, **fields) -> Film:
    """Build a Film keyed by source and title, with its age rating normalised."""
    title = title.strip()
    fields["age_rating"] = age_rating(fields.get("age_rating", ""))
    return Film(key=film_key(source, title), source=source, title=title, **fields)


def register(film: Film, *, session: requests.Session | None = None) -> Film:
    """Store the film's poster unless already present.  Returns *film* unchanged."""
    key = poster_key_for_film(film.key)
    if film.poster_url and not has_poster(key, path=db_path):
        _download(film.poster_url, key, session or _session)
    return film


def _download(url: str, key: str, session: requests.Session) -> None:
    try:
        with session.get(url, timeout=15, stream=True) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                log.warning("poster %s is %s, not an image", url, content_type or "untyped")
                return
            data = bytearray()
            for chunk in resp.iter_content(64 * 1024):
                data += chunk
                if len(data) > _MAX_BYTES:
                    log.warning("poster %s exceeds %d bytes", url, _MAX_BYTES)
                    return
        data, content_type = _fit(bytes(data), content_type)
        write_poster(key, data, content_type, path=db_path)
    except (requests.RequestException, OSError, Image.DecompressionBombError) as exc:
        log.warning("failed to download poster %s: %s", url, exc)


def _fit(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Image bytes no wider than _MAX_WIDTH; unchanged when already within it or undecodable."""
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
    except OSError:
        return data, content_type
    if width <= _MAX_WIDTH:
        return data, content_type
    image.thumbnail((_MAX_WIDTH, round(height * _MAX_WIDTH / width)))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue(), "image/jpeg"
