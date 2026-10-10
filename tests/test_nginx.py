"""Exercise static-page fallbacks through Nginx, when installed."""

import http.client
import shutil
import socket
import ssl
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture
def nginx_server(tmp_path):
    nginx = shutil.which("nginx")
    if not nginx:
        pytest.skip("nginx is not installed")

    root = tmp_path / "www"
    for page in [
        "index.html",
        "stad/stockholm/index.html",
        "stad/göteborg/index.html",
        "stad/stockholm/film/current/index.html",
        "film/current/index.html",
        "i/style.css",
    ]:
        path = root / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    site = (Path(__file__).resolve().parents[1] / "etc/nginx/sites-available/allabiografer.se").read_text()
    site = site.replace("listen 8080;", f"listen 127.0.0.1:{port};")
    site = site.replace("/var/www/allabiografer.se", str(root))
    site = site.replace("/etc/ssl/certs/ca-certificates.crt", ssl.get_default_verify_paths().cafile)
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log;\n"
        "events {}\nhttp {\naccess_log off;\n"
        "map $request_uri $posthog_upstream { default eu.i.posthog.com; }\n"
        "map $remote_addr $posthog_client_ip { default $remote_addr; }\n"
        f"{site}\n}}\n"
    )
    subprocess.run([nginx, "-t", "-p", str(tmp_path), "-c", str(config)], check=True)
    process = subprocess.Popen([nginx, "-p", str(tmp_path), "-c", str(config), "-g", "daemon off;"])
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if process.poll() is not None:
                    pytest.fail((tmp_path / "error.log").read_text())
                time.sleep(0.05)
        else:
            pytest.fail("Nginx did not start")
        yield port
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize(
    ("path", "status", "destination"),
    [
        ("/stad/stockholm/film/current/", 200, None),
        ("/stad/stockholm/", 200, None),
        ("/stad/stockholm/film/expired/", 302, "/stad/stockholm/"),
        ("/stad/stockholm/film/expired?selection=1", 302, "/stad/stockholm/"),
        ("/stad/stockholm/closed-cinema/", 302, "/stad/stockholm/"),
        ("/stad/stockholm/genre/missing/", 302, "/stad/stockholm/"),
        ("/stad/g%C3%B6teborg/film/expired/", 302, "/stad/göteborg/"),
        ("/stad/unknown/film/expired/", 404, None),
        ("/stad/unknown/", 404, None),
        ("/film/current/", 200, None),
        ("/film/expired/", 302, "/"),
        ("/film/expired?selection=1", 302, "/"),
        ("/film/", 403, None),
        ("/film/current/missing.css", 404, None),
        ("/unrelated/", 404, None),
        ("/i/missing.css", 404, None),
        ("/i/style.css", 200, None),
    ],
)
def test_page_fallback(nginx_server, path, status, destination):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        assert response.status == status
        location = response.getheader("Location")
        if destination:
            # HTTP header decoding uses Latin-1; Nginx emits normalized UTF-8 city paths.
            assert location.encode("latin-1").decode("utf-8") == destination
        else:
            assert location is None
        if status == 200:
            assert response.read().decode() == path.lstrip("/") + ("index.html" if path.endswith("/") else "")
    finally:
        connection.close()
