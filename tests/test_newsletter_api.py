"""Exercise the real nginx/Lua API against a local PostHog HTTP contract fixture."""

import copy
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import requests

from newsletter.migrate import migrate, preferences_token

ROOT = Path(__file__).resolve().parents[1]
SECRET = "test-only-signing-secret-32-characters-long"


@pytest.fixture
def newsletter_api(tmp_path):
    nginx = shutil.which("openresty")
    if not nginx:
        pytest.skip("Run inside nix develop for Lua-enabled nginx")
    people, preferences, writes = {}, {}, []
    categories = [
        {
            "id": "cat-g",
            "key": "newsletter-city-goteborg",
            "name": "Nytt på bio i Göteborg",
            "category_type": "marketing",
        },
        {
            "id": "cat-s",
            "key": "newsletter-city-stockholm",
            "name": "Nytt på bio i Stockholm",
            "category_type": "marketing",
        },
        {"id": "cat-m", "key": "newsletter-city-malmo", "name": "Nytt på bio i Malmö", "category_type": "marketing"},
    ]
    state = {"fail": False, "pending": [], "delay": 0}

    class PostHogHandler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, data, status=200):
            payload = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer test-private-key"
            if state["fail"]:
                return self.respond({"error": "private upstream failure"}, 500)
            for pending in list(state["pending"]):
                when, identity, properties = pending
                if time.monotonic() >= when:
                    person = people.setdefault(
                        identity, {"uuid": str(uuid4()), "distinct_ids": [identity], "properties": {}}
                    )
                    person["properties"].update(properties)
                    state["pending"].remove(pending)
            url = urlsplit(self.path)
            query = parse_qs(url.query, keep_blank_values=True)
            if url.path.endswith("/persons/"):
                if "email" in query:
                    result = [p for p in people.values() if p["properties"].get("email") == query["email"][0]]
                elif "distinct_id" in query:
                    result = [people[query["distinct_id"][0]]] if query["distinct_id"][0] in people else []
                else:
                    raise AssertionError("Unexpected person collection lookup")
                return self.respond({"results": [{"uuid": p["uuid"]} for p in result], "next": None})
            if "/persons/" in url.path:
                person = next((p for p in people.values() if p["uuid"] == url.path.split("/")[-2]), None)
                return self.respond(person, 200 if person else 404)
            if url.path.endswith("/messaging_categories/"):
                return self.respond({"results": categories, "next": None})
            if url.path.endswith("/opt_outs/"):
                category_key = query.get("category_key", [""])[0]
                category_id = next((c["id"] for c in categories if c["key"] == category_key), "$all")
                rows = [
                    {"identifier": email, "preferences": prefs}
                    for email, prefs in preferences.items()
                    if query["search"][0] in email and prefs.get(category_id) == "OPTED_OUT"
                ]
                return self.respond({"results": rows, "next": None})
            return self.respond({}, 404)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/i/v0/e/":
                assert "Authorization" not in self.headers
                assert data["api_key"] == "test-public-key"
                state["pending"].append(
                    (time.monotonic() + state["delay"], data["distinct_id"], data["properties"]["$set"])
                )
                return self.respond({"status": 1})
            assert self.headers["Authorization"] == "Bearer test-private-key"
            writes.append((self.path, data))
            if state["fail"]:
                return self.respond({"error": "private upstream failure"}, 500)
            prefs = preferences.setdefault(data["identifier"], {})
            category_id = next((c["id"] for c in categories if c["key"] == data.get("category_key")), "$all")
            if self.path.endswith("/add_opt_out/"):
                prefs[category_id] = "OPTED_OUT"
            else:
                if category_id != "$all" and prefs.get("$all") == "OPTED_OUT":
                    for category in categories:
                        prefs[category["id"]] = "OPTED_OUT"
                    prefs["$all"] = "OPTED_IN"
                prefs[category_id] = "OPTED_IN"
            return self.respond({"preferences": prefs})

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), PostHogHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cities = tmp_path / "cities.json"
    cities.write_text(json.dumps({"Göteborg": "newsletter-city-goteborg", "Stockholm": "newsletter-city-stockholm"}))
    env = {
        **os.environ,
        "POSTHOG_PERSONAL_API_KEY": "test-private-key",
        "POSTHOG_PROJECT_ID": "123",
        "POSTHOG_PROJECT_TOKEN": "test-public-key",
        "POSTHOG_API_HOST": f"http://127.0.0.1:{upstream.server_port}",
        "POSTHOG_CAPTURE_HOST": f"http://127.0.0.1:{upstream.server_port}",
        "NEWSLETTER_SIGNING_SECRET": SECRET,
        "NEWSLETTER_CITIES_FILE": str(cities),
    }
    lua_path = f"{ROOT}/etc/nginx/lua/?.lua;" + os.environ["NEWSLETTER_LUA_PATH"]
    config = tmp_path / "nginx.conf"
    config.write_text(
        "\n".join(f"env {key};" for key in env if key.startswith(("POSTHOG_", "NEWSLETTER_")))
        + f"\npid {tmp_path}/nginx.pid; error_log {tmp_path}/error.log;\n"
        + "events {}\nhttp { access_log off; lua_shared_dict newsletter_locks 1m;"
        + "lua_shared_dict newsletter_pending 1m;"
        + f"lua_package_path '{lua_path}'; server {{listen 127.0.0.1:{port};"
        + "location /api/newsletter/ {client_max_body_size 2k; content_by_lua_block {require('newsletter').handle()}}}}"
    )
    process = subprocess.Popen([nginx, "-p", str(tmp_path), "-c", str(config), "-g", "daemon off;"], env=env)
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
            pytest.fail("Lua nginx did not start")

        def call(path, body=None, token=None, origin="https://allabiografer.se"):
            headers = {"Origin": origin}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            return requests.post(
                f"http://127.0.0.1:{port}/api/newsletter/{path}", json=body or {}, headers=headers, timeout=30
            )

        yield call, people, preferences, writes, state
    finally:
        process.terminate()
        process.wait(timeout=5)
        upstream.shutdown()
        thread.join(timeout=5)


def test_signup_and_property_unsubscribe_end_to_end(newsletter_api):
    call, people, prefs, writes, _ = newsletter_api
    for city in ["Göteborg", "Stockholm", "Göteborg"]:
        response = call("signup", {"email": " PERSON@Example.com ", "city": city})
        assert response.status_code == 200, response.text
        assert response.json() == {"success": True}  # Never return a bearer token from signup.
    person = people["newsletter:person@example.com"]["properties"]
    assert person["newsletter_cities"] == ["Göteborg", "Stockholm"]
    assert not any(key.startswith("newsletter_subscribed_city_") for key in person)
    token = person["newsletter_preferences_token"]
    assert "newsletter_preferences_id" not in person
    assert token == preferences_token(SECRET, people["newsletter:person@example.com"]["uuid"])
    expected = {"delivery_blocked": False, "cities": ["Göteborg", "Stockholm"]}
    response = call("preferences", token=token)
    assert response.status_code == 200, response.text
    assert response.json() == expected  # Malmö exists, but was never joined: absent.
    assert response.headers["Cache-Control"] == "no-store"
    assert call("preferences", {"city": "Malmö", "unsubscribe": True}, token).status_code == 400
    assert writes == []
    assert call("preferences", {"city": "Göteborg", "unsubscribe": True}, token).json()["cities"] == ["Stockholm"]
    assert person["newsletter_cities"] == ["Stockholm"]
    assert call("preferences", {"unsubscribe": True}, token).json()["cities"] == []
    assert person["newsletter_cities"] == []
    assert "newsletter_enabled" not in person
    assert prefs == {}  # Native state is not a competing copy of the city list.
    prefs["person@example.com"] = {"$all": "OPTED_OUT"}
    assert call("signup", {"email": "person@example.com", "city": "Stockholm"}).status_code == 200
    assert person["newsletter_cities"] == ["Stockholm"]  # Does not restore removed Göteborg.
    assert call("preferences", token=token).json() == {"cities": ["Stockholm"], "delivery_blocked": True}
    assert prefs["person@example.com"]["$all"] == "OPTED_OUT"  # Native unsubscribe never bypassed.


def test_api_rejects_forged_links_and_upstream_errors(newsletter_api):
    call, people, _, writes, state = newsletter_api
    assert call("signup", {"email": "p@example.com", "city": "Göteborg"}).status_code == 200
    token = people["newsletter:p@example.com"]["properties"]["newsletter_preferences_token"]
    before = copy.deepcopy(people)
    for bad_token in [
        None,
        "garbage",
        token[:-1] + ("0" if token[-1] != "0" else "1"),
        preferences_token(SECRET, "a" * 32),
        preferences_token(SECRET, str(uuid4())),
        preferences_token(SECRET, "aaaaaaaaa-aaa-aaaa-aaaa-aaaaaaaaaaaa"),
    ]:
        assert call("preferences", {"unsubscribe": True}, bad_token).status_code == 401
    assert people == before
    assert writes == []
    properties = people["newsletter:p@example.com"]["properties"]
    properties["newsletter_preferences_token"] = "revoked"
    assert call("preferences", token=token).status_code == 401
    properties["newsletter_preferences_token"] = token
    assert call("preferences", token=token, origin="https://evil.test").status_code == 403
    assert call("signup", {"email": "p@example.com", "city": "Invented"}).status_code == 400
    state["fail"] = True
    response = call("preferences", token=token)
    assert response.status_code == 502
    assert "private" not in response.text
    assert token not in response.text


def test_concurrent_signups_preserve_cities_across_ingestion_delay(newsletter_api):
    call, people, _, _, state = newsletter_api
    state["delay"] = 0.2
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda city: call("signup", {"email": "p@example.com", "city": city}), ["Stockholm", "Göteborg"])
        )
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert people["newsletter:p@example.com"]["properties"]["newsletter_cities"] == ["Göteborg", "Stockholm"]


@pytest.mark.parametrize("native_optout", [None, "city", "global"])
def test_migration_is_dry_run_idempotent_and_preserves_consent(native_optout, monkeypatch):
    class MigrationAPI:
        base = "https://eu.posthog.com/api/projects/123/hog_flows/"

        def __init__(self):
            self.properties = {
                "email": "p@example.com",
                "newsletter_confirmed": "yes",
                "newsletter_city": "Stockholm",
                "newsletter_subscribed_city_Stockholm": "yes",
                "newsletter_subscribed_city_Göteborg": "yes",
                "newsletter_subscribed_city_Malmö": "no",
                "newsletter_preferences_id": "a" * 32,
            }

        def request(self, method, path, body=None):
            if method == "GET":
                if "messaging_categories/" in path:
                    return {"results": [{"key": "newsletter-city-goteborg", "id": "cat-g"}]}
                if "messaging_preferences/" in path:
                    if native_optout == "global" or (
                        native_optout == "city" and "category_key=newsletter-city-goteborg" in path
                    ):
                        return {
                            "results": [
                                {
                                    "identifier": "p@example.com",
                                    "preferences": {
                                        "$all" if native_optout == "global" else "cat-g": "OPTED_OUT",
                                    },
                                }
                            ]
                        }
                    return {"results": []}
                if "?" in path:
                    return {"results": [{"uuid": "12345678-1234-5678-9abc-123456789abc"}], "next": None}
                return {
                    "uuid": "12345678-1234-5678-9abc-123456789abc",
                    "properties": copy.deepcopy(self.properties),
                    "distinct_ids": ["existing-subscriber"],
                }
            assert "/persons/12345678-1234-5678-9abc-123456789abc/" in path  # No opt-out or delivery mutations.
            assert method == "POST"
            for key in body["$unset"]:
                self.properties.pop(key)
            return {}

    client = MigrationAPI()

    def capture(request, timeout):
        assert request.full_url == "https://eu.i.posthog.com/i/v0/e/"
        assert not request.has_header("Authorization")
        payload = json.loads(request.data)
        assert payload["api_key"] == "test-public-key"
        assert payload["event"] == "$set"
        assert payload["distinct_id"] == "existing-subscriber"
        client.properties.update(payload["properties"]["$set"])
        for key in payload["properties"]["$unset"]:
            client.properties.pop(key, None)
        return BytesIO(b'{"status":1}')

    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "test-public-key")
    monkeypatch.setattr("newsletter.migrate.urlopen", capture)
    before = copy.deepcopy(client.properties)
    assert migrate(client, SECRET)["updates"] == 1
    assert client.properties == before
    assert migrate(client, SECRET, apply=True, prune=True)["legacy_properties"] == 4
    expected = {None: ["Göteborg", "Stockholm"], "city": ["Stockholm"], "global": []}
    assert client.properties["newsletter_cities"] == expected[native_optout]
    assert "newsletter_preferences_id" not in client.properties
    assert client.properties["newsletter_preferences_token"] == preferences_token(
        SECRET, "12345678-1234-5678-9abc-123456789abc"
    )
    assert client.properties["newsletter_confirmed"] == "yes"
    assert not any(k.startswith("newsletter_subscribed_city_") for k in client.properties)
    assert migrate(client, SECRET, apply=True) == {"people": 1, "updates": 0, "legacy_properties": 0}
    # A rerun before pruning must never resurrect a removed city from legacy keys.
    client.properties["newsletter_cities"] = []
    client.properties["newsletter_city"] = "Stockholm"
    migrate(client, SECRET, apply=True)
    assert client.properties["newsletter_cities"] == []
