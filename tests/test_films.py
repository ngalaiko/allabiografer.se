"""Site poster downloads."""

import io

from PIL import Image

from parse.parsers import _films
from store import poster_path


class _Response:
    def __init__(self, data: bytes, content_type: str):
        self.data = data
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.data


class _Session:
    def __init__(self, data: bytes, content_type: str):
        self.response = _Response(data, content_type)

    def get(self, url, timeout=None, stream=False):
        return self.response


def _image(width: int, height: int, fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buf, fmt)
    return buf.getvalue()


def test_oversized_posters_are_downscaled_to_jpeg(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr(_films, "db_path", db)

    _films._download("https://x/p.png", "s/film", _Session(_image(3000, 4500, "PNG"), "image/png"))

    stored = poster_path("s/film", path=db)
    assert stored.suffix == ".jpg"
    assert Image.open(stored).size == (1000, 1500)


def test_small_posters_are_stored_unchanged(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr(_films, "db_path", db)
    data = _image(500, 750, "PNG")

    _films._download("https://x/p.png", "s/film", _Session(data, "image/png"))

    assert poster_path("s/film", path=db).read_bytes() == data
