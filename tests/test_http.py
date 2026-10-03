"""Shared HTTP session retries."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from parse import _http


@pytest.fixture
def server():
    """Serve the queued statuses in order, then 200."""
    statuses: list[int] = []
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            status = statuses.pop(0) if statuses else 200
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", statuses, hits
    srv.shutdown()


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(_http, "_BACKOFF", 0)


def test_retries_server_errors(server):
    url, statuses, hits = server
    statuses.extend([503, 502])
    resp = _http.session().get(url, timeout=5)
    assert resp.status_code == 200
    assert len(hits) == 3


def test_gives_up(server):
    url, statuses, _ = server
    statuses.extend([503] * 10)
    resp = _http.session().get(url, timeout=5)
    with pytest.raises(requests.HTTPError):
        resp.raise_for_status()


def test_no_retry_on_not_found(server):
    url, statuses, hits = server
    statuses.append(404)
    resp = _http.session().get(url, timeout=5)
    assert resp.status_code == 404
    assert len(hits) == 1


def test_retries_connection_errors():
    s = _http.session()
    with pytest.raises(requests.ConnectionError) as exc:
        s.get("http://127.0.0.1:1", timeout=5)
    assert "Max retries exceeded" in str(exc.value)


def test_user_agent():
    assert _http.session(user_agent="x").headers["User-Agent"] == "x"
