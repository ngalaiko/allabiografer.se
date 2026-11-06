"""Exercise static-page fallbacks through Nginx, when installed."""

import http.client
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from requests import certs


@pytest.fixture
def nginx_server(tmp_path):
    nginx = shutil.which("openresty")
    if not nginx:
        pytest.skip("Run inside nix develop for Lua-enabled nginx")

    root = tmp_path / "www"
    for page in [
        "index.html",
        "stad/stockholm/index.html",
        "stad/göteborg/index.html",
        "stad/stockholm/film/current/index.html",
        "film/current/index.html",
        "i/style.css",
        "llms.txt",
    ]:
        path = root / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page)
        if path.suffix == ".html":
            path.with_suffix(".md").write_text(f"# {page}\n\nBioprogram i Sverige.\n")
    for city in ("stockholm", "göteborg"):
        (root / "stad" / city / "index.json").write_text('{"schema_version":1,"screenings":[]}\n')

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    site = (Path(__file__).resolve().parents[1] / "etc/nginx/sites-available/allabiografer.se").read_text()
    site = site.replace("listen 8080;", f"listen 127.0.0.1:{port};")
    site = site.replace("/var/www/allabiografer.se", str(root))
    site = site.replace("/etc/ssl/certs/ca-certificates.crt", certs.where())
    # test_newsletter_api owns newsletter API coverage.
    site = site.replace("content_by_lua_block { require('newsletter').handle() }", "return 503;")
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log;\n"
        "events {}\nhttp {\naccess_log off;\n"
        f"lua_package_path '{Path(__file__).resolve().parents[1]}/etc/nginx/lua/?.lua;;';\n"
        "types { text/html html; text/css css; application/json json; text/plain txt; }\n"
        f"include {Path(__file__).resolve().parents[1]}/etc/nginx/markdown.conf;\n"
        "limit_req_zone $binary_remote_addr zone=newsletter_signup:1m rate=5r/m;\n"
        "limit_req_zone $binary_remote_addr zone=newsletter_preferences:1m rate=30r/m;\n"
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
        ("/llms.txt", 200, None),
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


@pytest.mark.parametrize(
    ("accept", "markdown"),
    [
        (None, False),
        ("*/*", False),
        ("text/html,application/xhtml+xml,*/*;q=0.8", False),
        ("text/markdown", True),
        ("text/html, text/markdown;q=0.8", False),
        ("text/markdown;q=0.8, text/html;q=0.9", False),
        ("text/html;q=0.2, text/markdown;q=0.8", True),
        ("text/markdown;q=0.2, text/html;q=0.8", False),
        ("text/html, text/markdown", True),
        ("text/html;q=0.5, text/markdown;q=0.5", True),
        ("text/markdown;q=0.4, text/*;q=0.8", False),
        ("text/markdown;q=0.4, text/*;q=0.1", True),
        ("text/markdown;q=0.4, */*;q=0.8", False),
        ("text/markdown;q=0.4, text/html;q=0, */*;q=1", True),
        ("text/markdown;q=0, */*;q=1", False),
        ("text/*", False),
        ("TEXT/MARKDOWN; charset=utf-8", True),
        ("text/markdown; charset=utf-8; q=0.7, text/html;q=0.6", True),
        ("text/markdown;q=0", False),
        ("text/markdown;q=0.000, text/html", False),
        ("text/markdown-extra", False),
    ],
)
@pytest.mark.parametrize("path", ["/", "/stad/stockholm/", "/film/current/", "/stad/stockholm/film/current/index.html"])
def test_markdown_negotiation(nginx_server, accept, markdown, path):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", path, headers={"Accept": accept} if accept else {})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").split(";")[0] == ("text/markdown" if markdown else "text/html")
        assert "Accept" in response.getheader("Vary")
        body = response.read().decode()
        assert body.startswith("# ") is markdown
        alternate_path = path if path.endswith(".html") else path + "index.html"
        if not markdown:
            alternate_path = alternate_path.removesuffix(".html") + ".md"
        alternate_type = "text/html" if markdown else "text/markdown"
        expected_link = f'<{alternate_path}>; rel="alternate"; type="{alternate_type}"'
        if path == "/stad/stockholm/":
            expected_link += ', </stad/stockholm/index.json>; rel="alternate"; type="application/json"'
        assert response.getheader("Link") == expected_link
        if markdown:
            assert "Bioprogram i Sverige." in body
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/i/style.css", 200),
        ("/llms.txt", 200),
        ("/unrelated/", 404),
        ("/film/expired/", 302),
        ("/api/newsletter/signup", 503),
    ],
)
def test_markdown_preserves_nonpage_responses(nginx_server, path, status):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", path, headers={"Accept": "text/markdown"})
        response = connection.getresponse()
        assert response.status == status
        assert response.getheader("Link") is None
        if status == 200:
            expected_type = "text/plain" if path == "/llms.txt" else "text/css"
            assert response.getheader("Content-Type").split(";")[0] == expected_type
            assert response.read().decode() == path.lstrip("/")
    finally:
        connection.close()


@pytest.mark.parametrize("suffix", ["html", "md"])
def test_direct_representations_advertise_fetchable_alternate(nginx_server, suffix):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", f"/stad/g%C3%B6teborg/index.{suffix}")
        response = connection.getresponse()
        assert response.status == 200
        alternate = "md" if suffix == "html" else "html"
        media = "markdown" if suffix == "html" else "html"
        link = f"/stad/g%C3%B6teborg/index.{alternate}"
        assert response.getheader("Link") == (
            f'<{link}>; rel="alternate"; type="text/{media}", '
            '</stad/g%C3%B6teborg/index.json>; rel="alternate"; type="application/json"'
        )
        response.read()
        connection.request("GET", link)
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith(f"text/{media}")
    finally:
        connection.close()


@pytest.mark.parametrize("accept", ["application/json", "text/markdown", "*/*"])
def test_city_json_is_fetchable_without_negotiation(nginx_server, accept):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", "/stad/g%C3%B6teborg/index.json", headers={"Accept": accept})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").split(";")[0] == "application/json"
        assert response.getheader("Link") == ('</stad/g%C3%B6teborg/index.html>; rel="alternate"; type="text/html"')
        assert response.read() == b'{"schema_version":1,"screenings":[]}\n'
    finally:
        connection.close()
