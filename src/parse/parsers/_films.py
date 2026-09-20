"""Site-sourced film metadata for parsers — builds Films and stores their posters."""

import logging
from pathlib import Path

import requests

from store import DB_FILE, Film, film_key, has_poster, poster_key_for_film, write_poster

log = logging.getLogger(__name__)

# Database posters are written beside; the CLI points it at --output.
db_path: Path = DB_FILE

_MAX_BYTES = 8 * 1024 * 1024

_session = requests.Session()


def make(source: str, title: str, **fields) -> Film:
    """Build a Film with its key derived from source and title."""
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
        write_poster(key, bytes(data), content_type, path=db_path)
    except (requests.RequestException, OSError) as exc:
        log.warning("failed to download poster %s: %s", url, exc)
