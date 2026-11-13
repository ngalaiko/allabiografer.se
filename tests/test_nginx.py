"""Exercise static-page fallbacks through Nginx, when installed."""

import http.client
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote

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
        "stad/stockholm/bagarmossen-folkets-hus/index.html",
        "stad/stockholm/genre/drama/index.html",
        "stad/stockholm/film/current/index.html",
        "stad/stockholm/film/blir-du-ledsen-om-jag-dör/index.html",
        "stad/stockholm/stockholm-bio-husby/index.html",
        "stad/stockholm/biocafé-tellus/index.html",
        "stad/malmö/hypnos-theatre/index.html",
        "stad/götene/bio-göta-lejon/index.html",
        "stad/hässleholm/index.html",
        "stad/hässleholm/blå-salongen/index.html",
        "stad/hässleholm/genre/dokumentär/index.html",
        "stad/hässleholm/film/samma-sång-en-resa-till-peps-persson/index.html",
        "film/current/index.html",
        "i/style.css",
        "i/links.js",
        "i/FiraSans-Regular.woff2",
        "i/favicon-32x32.png",
        "i/newsletter-cities.json",
        "posters/123-0123456789ab.webp",
        "posters/123-0123456789ab-104.webp",
        "posters/123-0123456789ab-125.webp",
        "posters/123-0123456789ab-500.webp",
        "posters/123-125.webp",
        "posters/123-0123456789ab-thumb.webp",
        "og/0123456789abcdef0123.jpg",
        "llms.txt",
    ]:
        path = root / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page)
        if path.suffix == ".html":
            path.with_suffix(".md").write_text(f"# {page}\n\nBioprogram i Sverige.\n")
    for city in ("stockholm", "göteborg"):
        (root / "stad" / city / "index.json").write_text('{"schema_version":1,"screenings":[]}\n')
    for suffix in ("js", "json", "md", "xml"):
        (root / f"i/compression.{suffix}").write_text("compressible content\n" * 100)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    site = (Path(__file__).resolve().parents[1] / "etc/nginx/sites-available/allabiografer.se").read_text()
    site = site.replace("listen 8080;", f"listen 127.0.0.1:{port};")
    site = site.replace("/var/www/allabiografer.se", str(root))
    site = site.replace(
        "/etc/nginx/rewrites.conf", str(Path(__file__).resolve().parents[1] / "etc/nginx/rewrites.conf")
    )
    site = site.replace("/etc/ssl/certs/ca-certificates.crt", certs.where())
    # test_newsletter_api owns newsletter API coverage.
    site = site.replace("content_by_lua_block { require('newsletter').handle() }", "return 503;")
    site = site.replace(
        "proxy_pass https://$posthog_upstream;",
        'content_by_lua_block { ngx.header["Cache-Control"] = "private, max-age=60"; ngx.say(ngx.var.uri) }',
    )
    # Exercise production gzip settings; OpenResty does not include the Brotli module.
    compression = "\n".join(
        line
        for line in (Path(__file__).resolve().parents[1] / "etc/nginx/nginx.conf").read_text().splitlines()
        if line.strip().startswith("gzip")
    )
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log;\n"
        "events {}\nhttp {\naccess_log off;\n"
        f"lua_package_path '{Path(__file__).resolve().parents[1]}/etc/nginx/lua/?.lua;;';\n"
        "types { text/html html; text/css css; application/json json; text/plain txt; "
        "application/javascript js; application/xml xml; }\n"
        f"include {Path(__file__).resolve().parents[1]}/etc/nginx/markdown.conf;\n"
        f"include {Path(__file__).resolve().parents[1]}/etc/nginx/cache.conf;\n"
        f"{compression}\n"
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
        ("/stad/08-649-27-550/", 404, None),
        ("/stad/h%C3%A4ssleholm-kulturhuset/", 404, None),
        ("/stad/kistas/", 404, None),
        ("/stad/stockholm/stockholm-biocaf%C3%A9-tellus-midsommarkransen-extra/", 302, "/stad/stockholm/"),
        ("/stad/h%C3%A4ssleholm/genre/bosse-skoglund/", 302, "/stad/hässleholm/"),
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
    ("path", "destination"),
    [
        ("/stad/stockholm", "/stad/stockholm/"),
        ("/film/current?selection=1", "/film/current/?selection=1"),
        ("/stad/stockholm/film/current", "/stad/stockholm/film/current/"),
        ("/stad/g%C3%B6teborg", "/stad/g%C3%B6teborg/"),
        ("/stad/kista", "/stad/stockholm/"),
        ("/stad/kista/", "/stad/stockholm/"),
        ("/stad/kista/stockholm-bio-husby/", "/stad/stockholm/stockholm-bio-husby/"),
        ("/stad/kista/genre/drama/?selection=1", "/stad/stockholm/genre/drama/?selection=1"),
        (
            "/stad/kista/film/blir-du-ledsen-om-jag-d%C3%B6r/",
            "/stad/stockholm/film/blir-du-ledsen-om-jag-d%C3%B6r/",
        ),
        (
            "/stad/stockholm/stockholm-biocaf%C3%A9-tellus-midsommarkransen",
            "/stad/stockholm/biocaf%C3%A9-tellus/",
        ),
        (
            "/stad/stockholm/stockholm-biocaf%C3%A9-tellus-midsommarkransen/?selection=1",
            "/stad/stockholm/biocaf%C3%A9-tellus/?selection=1",
        ),
        ("/stad/malm%C3%B6/malm%C3%B6-hypnos-theatre", "/stad/malm%C3%B6/hypnos-theatre/"),
        ("/stad/malm%C3%B6/malm%C3%B6-hypnos-theatre/", "/stad/malm%C3%B6/hypnos-theatre/"),
        ("/stad/g%C3%B6tene/g%C3%B6tene-bio-g%C3%B6ta-lejon", "/stad/g%C3%B6tene/bio-g%C3%B6ta-lejon/"),
        ("/stad/g%C3%B6tene/g%C3%B6tene-bio-g%C3%B6ta-lejon/", "/stad/g%C3%B6tene/bio-g%C3%B6ta-lejon/"),
        ("/stad/08-649-27-55", "/stad/stockholm/"),
        ("/stad/08-649-27-55/", "/stad/stockholm/"),
        ("/stad/08-649-27-55/bagarmossen-folkets-hus/", "/stad/stockholm/bagarmossen-folkets-hus/"),
        ("/stad/08-649-27-55/genre/drama/", "/stad/stockholm/genre/drama/"),
        ("/stad/08-649-27-55/film/current/?selection=1", "/stad/stockholm/film/current/?selection=1"),
        (
            "/stad/08-649-27-55/film/blir-du-ledsen-om-jag-d%C3%B6r/",
            "/stad/stockholm/film/blir-du-ledsen-om-jag-d%C3%B6r/",
        ),
        ("/stad/h%C3%A4ssleholm-kulturhus", "/stad/h%C3%A4ssleholm/"),
        ("/stad/h%C3%A4ssleholm-kulturhus/", "/stad/h%C3%A4ssleholm/"),
        (
            "/stad/h%C3%A4ssleholm-kulturhus/bl%C3%A5-salongen/?selection=1",
            "/stad/h%C3%A4ssleholm/bl%C3%A5-salongen/?selection=1",
        ),
        (
            "/stad/h%C3%A4ssleholm-kulturhus/genre/dokument%C3%A4r/",
            "/stad/h%C3%A4ssleholm/genre/dokument%C3%A4r/",
        ),
        (
            "/stad/h%C3%A4ssleholm-kulturhus/film/samma-s%C3%A5ng-en-resa-till-peps-persson/",
            "/stad/h%C3%A4ssleholm/film/samma-s%C3%A5ng-en-resa-till-peps-persson/",
        ),
    ],
)
def test_public_redirects_preserve_paths_and_queries_without_origin_scheme_or_port(nginx_server, path, destination):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", path, headers={"Host": "allabiografer.se", "X-Forwarded-Proto": "https"})
        response = connection.getresponse()
        assert response.status == 301
        assert response.getheader("Location") == destination
        response.read()

        connection.request("GET", destination)
        response = connection.getresponse()
        assert response.status == 200
        assert response.read().decode() == unquote(destination.split("?")[0]).lstrip("/") + "index.html"
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


@pytest.mark.parametrize(
    ("path", "status", "policy"),
    [
        ("/", 200, "no-cache"),
        ("/index.md", 200, "no-cache"),
        ("/stad/stockholm/index.json", 200, "no-cache"),
        ("/i/newsletter-cities.json?v=0123456789ab", 200, "no-cache"),
        ("/llms.txt", 200, "no-cache"),
        ("/i/style.css", 200, "no-cache"),
        ("/i/links.js?v=invalid", 200, "no-cache"),
        ("/i/links.js?v=0123456789ab", 200, "public, max-age=31536000, immutable"),
        ("/i/style.css?v=0123456789ab&other=1", 200, "public, max-age=31536000, immutable"),
        ("/i/FiraSans-Regular.woff2?v=0123456789ab", 200, "public, max-age=31536000, immutable"),
        ("/posters/123-0123456789ab.webp", 200, "public, max-age=31536000, immutable"),
        ("/posters/123-0123456789ab-104.webp", 200, "public, max-age=31536000, immutable"),
        ("/posters/123-0123456789ab-125.webp?other=1", 200, "public, max-age=31536000, immutable"),
        ("/posters/123-0123456789ab-500.webp", 200, "public, max-age=31536000, immutable"),
        ("/posters/123-125.webp", 200, "no-cache"),
        ("/posters/123-0123456789ab-thumb.webp", 200, "no-cache"),
        ("/og/0123456789abcdef0123.jpg", 200, "public, max-age=31536000, immutable"),
        ("/i/favicon-32x32.png", 200, "public, max-age=86400"),
        ("/i/missing.js?v=0123456789ab", 404, "no-cache"),
        ("/posters/missing-0123456789ab.webp", 404, "no-cache"),
        ("/posters/missing-0123456789ab-125.webp", 404, "no-cache"),
        ("/og/ffffffffffffffffffff.jpg", 404, "no-cache"),
        ("/film/expired/", 302, "no-cache"),
        ("/stad/stockholm/film/expired/", 302, "no-cache"),
        ("/api/newsletter/signup", 503, None),
        ("/salong/static/file.js?v=0123456789ab", 200, "private, max-age=60"),
    ],
)
def test_cache_policy(nginx_server, path, status, policy):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        assert response.status == status
        assert response.getheader("Cache-Control") == policy
        assert "Accept" in response.getheader("Vary")
        if path.startswith("/salong/"):
            assert response.read().decode().strip() == "/static/file.js"
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("path", "accept", "policy"),
    [
        ("/", "text/html", "no-cache"),
        ("/", "text/markdown", "no-cache"),
        ("/i/links.js?v=0123456789ab", "*/*", "public, max-age=31536000, immutable"),
        ("/posters/123-0123456789ab-125.webp", "*/*", "public, max-age=31536000, immutable"),
    ],
)
def test_conditional_cache_policy(nginx_server, path, accept, policy):
    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        connection.request("GET", path, headers={"Accept": accept})
        response = connection.getresponse()
        assert response.status == 200
        etag = response.getheader("ETag")
        modified = response.getheader("Last-Modified")
        assert etag
        assert modified
        original = response.read()
        for validator in ({"If-None-Match": etag}, {"If-Modified-Since": modified}):
            connection.request("GET", path, headers={"Accept": accept, **validator})
            response = connection.getresponse()
            assert response.status == 304
            assert response.getheader("Cache-Control") == policy
            assert "Accept" in response.getheader("Vary")
            assert response.read() == b""
        connection.request("GET", path, headers={"Accept": accept, "Range": "bytes=2-5"})
        response = connection.getresponse()
        assert response.status == 206
        assert response.getheader("Cache-Control") == policy
        assert response.read() == original[2:6]
    finally:
        connection.close()


@pytest.mark.parametrize("suffix", ["js", "json", "md", "xml"])
def test_text_compression(nginx_server, suffix):
    import gzip

    connection = http.client.HTTPConnection("127.0.0.1", nginx_server)
    try:
        path = f"/i/compression.{suffix}"
        connection.request("GET", path, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Encoding") is None
        original = response.read()
        connection.request("GET", path, headers={"Accept-Encoding": "gzip"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Encoding") == "gzip"
        assert "Accept-Encoding" in response.getheader("Vary")
        assert "Accept" in response.getheader("Vary")
        assert gzip.decompress(response.read()) == original
    finally:
        connection.close()
