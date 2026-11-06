"""Exercise the real nginx/Lua API against a local PostHog HTTP contract fixture."""

import copy
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
import requests

from newsletter import PostHog

ROOT = Path(__file__).resolve().parents[1]
SECRET = "test-only-signing-secret-32-characters-long"


def preferences_token(secret, identifier):
    signature = hmac.new(
        secret.encode(), f"newsletter-preferences:v1:{identifier}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{identifier}.{signature}"


@pytest.fixture(params=[False, True], ids=["native-json-null", "alpine-table-null"])
def newsletter_api(tmp_path, request):
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
    state = {"fail": False, "pending": [], "delay": 0, "fail_optin": False, "exceptions": []}

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

        def apply_pending(self):
            for pending in list(state["pending"]):
                when, identity, properties = pending
                if time.monotonic() >= when:
                    person = people.setdefault(
                        identity, {"uuid": str(uuid4()), "distinct_ids": [identity], "properties": {}}
                    )
                    person["properties"].update(properties)
                    state["pending"].remove(pending)

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer test-private-key"
            if state["fail"]:
                return self.respond({"error": "private upstream failure"}, 500)
            self.apply_pending()
            url = urlsplit(self.path)
            query = parse_qs(url.query, keep_blank_values=True)
            if url.path.endswith("/persons/"):
                if "email" in query:
                    result = [p for p in people.values() if p["properties"].get("email") == query["email"][0]]
                elif "distinct_id" in query:
                    result = [people[query["distinct_id"][0]]] if query["distinct_id"][0] in people else []
                elif "properties" in query:
                    [prop] = json.loads(query["properties"][0])
                    assert (prop["key"], prop["type"], prop["operator"]) == (
                        "newsletter_preferences_token",
                        "person",
                        "exact",
                    )
                    result = [p for p in people.values() if p["properties"].get(prop["key"]) in prop["value"]]
                else:
                    raise AssertionError("Unexpected person collection lookup")
                return self.respond({"results": [{"uuid": p["uuid"]} for p in result], "next": None})
            if "/persons/" in url.path:
                person = next((p for p in people.values() if p["uuid"] == url.path.split("/")[-2]), None)
                return self.respond(person, 200 if person else 404)
            if url.path.endswith("/messaging_categories/"):
                return self.respond({"results": categories, "next": None})
            if url.path.endswith("/opt_outs/"):
                if state.get("timeout_optout"):
                    time.sleep(5.2)  # Longer than the real backend's upstream timeout.
                    return None
                if state.get("fail_optout"):
                    return self.respond({"error": "private upstream failure"}, 500)
                category_key = query.get("category_key", [""])[0]
                category_id = next((c["id"] for c in categories if c["key"] == category_key), "$all")
                rows = [
                    {"identifier": email, "preferences": prefs}
                    for email, prefs in preferences.items()
                    if query.get("search", [""])[0] in email and prefs.get(category_id) == "OPTED_OUT"
                ]
                return self.respond({"results": rows, "next": None})
            return self.respond({}, 404)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/i/v0/e/":
                assert "Authorization" not in self.headers
                assert data["api_key"] == "test-public-key"
                if data["event"] == "$exception":
                    state["exceptions"].append(data)
                    return self.respond({"status": 1}, 500 if state.get("fail_error_capture") else 200)
                if state.get("fail_capture"):
                    return self.respond({"status": 0}, 500)
                state["pending"].append(
                    (time.monotonic() + state["delay"], data["distinct_id"], data["properties"]["$set"])
                )
                self.apply_pending()
                return self.respond({"status": 1})
            assert self.headers["Authorization"] == "Bearer test-private-key"
            assert self.path.endswith(("/add_opt_out/", "/remove_opt_out/"))
            writes.append((self.path, data))
            if state["fail"] or state["fail_optin"]:
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
    state.update(upstream_url=f"http://127.0.0.1:{upstream.server_port}", api_url=f"http://127.0.0.1:{port}")
    lua_path = f"{ROOT}/etc/nginx/lua/?.lua;" + os.environ["NEWSLETTER_LUA_PATH"]
    # Alpine cjson 2.1.0 represents JSON null as a table, unlike OpenResty's build.
    table_null = (
        """
        init_by_lua_block {
            local json = require "cjson.safe"
            local decode, old_null = json.decode, json.null
            json.null = {}
            local function replace(value)
                if value == old_null then return json.null end
                if type(value) == "table" then
                    for key, item in pairs(value) do value[key] = replace(item) end
                end
                return value
            end
            json.decode = function(...)
                local value, err = decode(...)
                return replace(value), err
            end
        }
    """
        if request.param
        else ""
    )
    config = tmp_path / "nginx.conf"
    config.write_text(
        "\n".join(f"env {key};" for key in env if key.startswith(("POSTHOG_", "NEWSLETTER_")))
        + f"\npid {tmp_path}/nginx.pid; error_log {tmp_path}/error.log;\n"
        + "events {}\nhttp { access_log off; lua_shared_dict newsletter_locks 1m;"
        + "lua_shared_dict newsletter_pending 1m;"
        + f"lua_package_path '{lua_path}'; {table_null} server {{listen 127.0.0.1:{port};"
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
    assert "newsletter_confirmed" not in person
    token = person["newsletter_preferences_token"]
    assert "newsletter_preferences_id" not in person
    expected_signature = hmac.new(
        SECRET.encode(), b"newsletter-preferences:v2:person@example.com", hashlib.sha256
    ).hexdigest()
    assert token == "v2." + expected_signature
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
    assert call("preferences", token=token).json() == {"cities": ["Stockholm"], "delivery_blocked": False}
    assert prefs["person@example.com"]["$all"] == "OPTED_IN"  # Explicit signup restores marketing consent.


@pytest.mark.parametrize("entry", ["native-unsubscribe", "preferences"])
def test_native_unsubscribe_clears_cities_and_late_events_preserve_signup(newsletter_api, entry):
    call, people, prefs, _, state = newsletter_api
    # Native events identify the recipient by email, not this existing distinct_id.
    person = people["existing-browser-id"] = {
        "uuid": str(uuid4()),
        "distinct_ids": ["existing-browser-id"],
        "properties": {"email": "person@example.com", "newsletter_cities": ["Göteborg", "Stockholm"]},
    }
    properties = person["properties"]
    token = properties["newsletter_preferences_token"] = preferences_token(SECRET, person["uuid"])
    callback_token = preferences_token(SECRET, "native-unsubscribe").split(".")[-1]
    body, auth = ({"email": "person@example.com"}, callback_token) if entry == "native-unsubscribe" else ({}, token)
    prefs["notperson@example.com"] = {"$all": "OPTED_OUT"}  # Search substring is not an exact email match.
    assert call(entry, body, auth).status_code == 200
    assert properties["newsletter_cities"] == ["Göteborg", "Stockholm"]
    prefs["person@example.com"] = {"$all": "OPTED_OUT", "$tracking": "OPTED_OUT"}
    state["delay"] = 0.2
    response = call(entry, body, auth)
    assert response.status_code == 200, response.text
    assert properties["newsletter_cities"] == []
    assert call("preferences", token=token).json() == {"cities": [], "delivery_blocked": True}
    assert call(entry, body, auth).status_code == 200
    assert properties["newsletter_cities"] == []
    assert prefs["person@example.com"]["$all"] == "OPTED_OUT"  # Unsubscribe never grants consent.
    assert call("signup", {"email": "person@example.com", "city": "Stockholm"}).status_code == 200
    assert prefs["person@example.com"] == {"$all": "OPTED_IN", "$tracking": "OPTED_OUT"}
    assert call("native-unsubscribe", {"email": "person@example.com"}, callback_token).status_code == 200
    assert call("preferences", token=token).json() == {"cities": ["Stockholm"], "delivery_blocked": False}
    assert len(people) == 1


def test_native_callback_authentication_unknown_people_and_retry(newsletter_api):
    call, people, prefs, _, state = newsletter_api
    assert call("signup", {"email": "p@example.com", "city": "Göteborg"}).status_code == 200
    token = people["newsletter:p@example.com"]["properties"]["newsletter_preferences_token"]
    callback_token = preferences_token(SECRET, "native-unsubscribe").split(".")[-1]
    prefs["p@example.com"] = {"$all": "OPTED_OUT"}
    before = copy.deepcopy(people)
    for bad in [None, "forged", token, callback_token[:-1] + ("0" if callback_token[-1] != "0" else "1")]:
        assert call("native-unsubscribe", {"email": "p@example.com"}, bad).status_code == 401
    assert people == before
    assert call("native-unsubscribe", {"email": "stranger@example.com"}, callback_token).status_code == 200
    assert people == before
    state["fail"] = True
    assert call("native-unsubscribe", {"email": "p@example.com"}, callback_token).status_code == 502
    assert people == before
    state["fail"] = False
    assert call("native-unsubscribe", {"email": "p@example.com"}, callback_token).status_code == 200
    assert call("preferences", token=token).json()["cities"] == []


def test_signup_fails_if_native_consent_cannot_be_restored_and_never_resurrects_old_cities(newsletter_api):
    call, people, prefs, writes, state = newsletter_api
    assert call("signup", {"email": "p@example.com", "city": "Göteborg"}).status_code == 200
    properties = people["newsletter:p@example.com"]["properties"]
    prefs["p@example.com"] = {"$all": "OPTED_OUT"}
    state["fail_optin"] = True
    assert call("signup", {"email": "p@example.com", "city": "Stockholm"}).status_code == 502
    assert properties["newsletter_cities"] == ["Stockholm"]
    assert prefs["p@example.com"]["$all"] == "OPTED_OUT"
    state["fail_optin"] = False
    assert call("signup", {"email": "p@example.com", "city": "Stockholm"}).status_code == 200
    assert properties["newsletter_cities"] == ["Stockholm"]
    assert prefs["p@example.com"]["$all"] == "OPTED_IN"
    assert all(path.endswith("/remove_opt_out/") and data == {"identifier": "p@example.com"} for path, data in writes)


@pytest.mark.parametrize("rejoined", [False, True])
def test_pre_send_fallback_repairs_missed_notification_without_undoing_new_signup(
    newsletter_api, monkeypatch, rejoined
):
    call, people, prefs, _, state = newsletter_api
    assert call("signup", {"email": "p@example.com", "city": "Göteborg"}).status_code == 200
    properties = people["newsletter:p@example.com"]["properties"]
    prefs.update({"p@example.com": {"$all": "OPTED_OUT"}, "unknown@example.com": {"$all": "OPTED_OUT"}})
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "123")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "test-private-key")
    monkeypatch.setenv("POSTHOG_API_HOST", "https://eu.posthog.com")

    def local_transport(request, timeout):
        url = urlsplit(request.full_url)
        if url.netloc == "eu.posthog.com":
            base = state["upstream_url"]
            assert request.get_header("Authorization") == "Bearer test-private-key"
        else:
            assert url.netloc == "allabiografer.se"
            assert url.path == "/api/newsletter/preferences"
            assert request.get_header("Authorization") == "Bearer " + properties["newsletter_preferences_token"]
            base = state["api_url"]
        response = urlopen(
            Request(base + url.path + "?" + url.query, data=request.data, headers=dict(request.header_items())),
            timeout=timeout,
        )
        if rejoined and url.path.endswith("/opt_outs/"):
            # The collected opt-out snapshot predates this newer signup.
            assert call("signup", {"email": "p@example.com", "city": "Stockholm"}).status_code == 200
        return response

    monkeypatch.setattr("newsletter.urlopen", local_transport)
    assert PostHog().reconcile_unsubscribes() == 1
    assert properties["newsletter_cities"] == (["Stockholm"] if rejoined else [])
    assert len(people) == 1
    assert prefs["p@example.com"]["$all"] == ("OPTED_IN" if rejoined else "OPTED_OUT")


@pytest.mark.parametrize("first", ["signup", "native-unsubscribe"])
def test_concurrent_signup_and_native_notification_preserve_new_city(newsletter_api, first):
    call, people, prefs, _, state = newsletter_api
    assert call("signup", {"email": "p@example.com", "city": "Göteborg"}).status_code == 200
    properties = people["newsletter:p@example.com"]["properties"]
    prefs["p@example.com"] = {"$all": "OPTED_OUT"}
    state["delay"] = 0.2
    actions = {
        "signup": ("signup", {"email": "p@example.com", "city": "Stockholm"}),
        "native-unsubscribe": (
            "native-unsubscribe",
            {"email": "p@example.com"},
            preferences_token(SECRET, "native-unsubscribe").split(".")[-1],
        ),
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_request = pool.submit(call, *actions.pop(first))
        time.sleep(0.05)
        second_request = pool.submit(call, *next(iter(actions.values())))
        assert first_request.result().status_code == 200
        assert second_request.result().status_code == 200
    assert properties["newsletter_cities"] == ["Stockholm"]
    assert prefs["p@example.com"]["$all"] == "OPTED_IN"


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
    properties["email"] = "different@example.com"
    assert call("preferences", token=token).status_code == 401  # A stored token must also sign this email.
    properties["email"] = "p@example.com"
    people["duplicate"] = copy.deepcopy(people["newsletter:p@example.com"])
    people["duplicate"]["uuid"] = str(uuid4())
    assert call("preferences", token=token).status_code == 409
    del people["duplicate"]
    properties["newsletter_preferences_token"] = "revoked"
    assert call("preferences", token=token).status_code == 401
    properties["newsletter_preferences_token"] = token
    assert call("preferences", token=token, origin="https://evil.test").status_code == 403
    assert call("signup", {"email": "p@example.com", "city": "Invented"}).status_code == 400
    assert state["exceptions"] == []  # Expected client errors are not application exceptions.
    state["fail"] = True
    response = call("preferences", token=token)
    assert response.status_code == 502
    assert "private" not in response.text
    assert token not in response.text


@pytest.mark.parametrize(
    ("upstream_failure", "reporting_unavailable"), [("http", False), ("http", True), ("timeout", False)]
)
def test_signup_preflight_failure_reports_safe_diagnostics_without_creating_a_profile(
    newsletter_api, upstream_failure, reporting_unavailable
):
    call, people, _, _, state = newsletter_api
    state.update(
        fail_optout=upstream_failure == "http",
        timeout_optout=upstream_failure == "timeout",
        fail_error_capture=reporting_unavailable,
    )
    response = call("signup", {"email": "reader@example.com", "city": "Göteborg"})
    assert response.status_code == 502
    assert response.json() == {"error": "Request failed", "status": 502}
    assert people == {}  # Do not create an email-only profile before checking consent.
    for _ in range(100):
        if state["exceptions"]:
            break
        time.sleep(0.01)
    assert len(state["exceptions"]) == 1
    event = state["exceptions"][0]
    assert event["distinct_id"] == "newsletter-backend"
    properties = event["properties"]
    assert properties["$process_person_profile"] is False
    assert properties["$geoip_disable"] is True
    assert properties["endpoint"] == "/api/newsletter/signup"
    assert properties["http_status"] == 502
    assert properties["stage"] == "check_marketing_consent"
    assert properties["upstream_operation"] == "GET messaging_preferences"
    if upstream_failure == "http":
        assert properties["upstream_status"] == 500
        assert "upstream_error" not in properties
    else:
        assert "upstream_status" not in properties
        assert properties["upstream_error"] == "timeout"
    assert properties["$exception_list"] == [
        {
            "type": "NewsletterAPIError",
            "value": "Newsletter API failed at check_marketing_consent",
            "mechanism": {"handled": True, "synthetic": True},
        }
    ]
    serialized = json.dumps(properties)
    for private in ["reader@example.com", SECRET, "test-private-key", "private upstream failure", "$set", "token"]:
        assert private not in serialized
    state.update(fail_optout=False, timeout_optout=False)
    assert call("signup", {"email": "reader@example.com", "city": "Stockholm"}).status_code == 200
    assert people["newsletter:reader@example.com"]["properties"]["newsletter_cities"] == ["Stockholm"]
    assert len(state["exceptions"]) == 1  # Reporting failures do not recursively report or retry.


def test_slow_profile_creation_keeps_the_whole_subscription_and_retry_preserves_it(newsletter_api):
    call, people, _, _, state = newsletter_api
    state["delay"] = 11  # Beyond the backend's 20 half-second polls.
    started = time.monotonic()
    response = call("signup", {"email": "reader@example.com", "city": "Göteborg"})
    assert response.status_code == 200
    assert response.json() == {"success": True}  # Accepted, not necessarily visible yet.
    assert time.monotonic() - started < 3
    assert people == {}
    # Another update must not overtake the accepted city while ingestion is delayed.
    assert call("signup", {"email": "reader@example.com", "city": "Stockholm"}).status_code == 503
    assert len(state["pending"]) == 1
    time.sleep(max(0, started + 11.2 - time.monotonic()))
    response = requests.get(
        state["upstream_url"] + "/api/projects/123/persons/?email=reader@example.com",
        headers={"Authorization": "Bearer test-private-key"},
        timeout=5,
    )
    assert response.status_code == 200
    properties = people["newsletter:reader@example.com"]["properties"]
    assert properties["email"] == "reader@example.com"
    assert properties["newsletter_cities"] == ["Göteborg"]  # Not the old stranded email-only profile.
    token = properties["newsletter_preferences_token"]
    assert call("preferences", token=token).json() == {"cities": ["Göteborg"], "delivery_blocked": False}
    state["delay"] = 0
    assert call("signup", {"email": "reader@example.com", "city": "Stockholm"}).status_code == 200
    assert properties["newsletter_cities"] == ["Göteborg", "Stockholm"]
    assert properties["newsletter_preferences_token"] == token


def test_signup_does_not_claim_acceptance_when_ingestion_rejects_the_write(newsletter_api):
    call, people, _, _, state = newsletter_api
    state["fail_capture"] = True
    assert call("signup", {"email": "reader@example.com", "city": "Stockholm"}).status_code == 502
    assert people == {}
    assert state["pending"] == []


def test_concurrent_signups_preserve_cities_across_ingestion_delay(newsletter_api):
    call, people, _, _, state = newsletter_api
    state["delay"] = 0.2
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda city: call("signup", {"email": "p@example.com", "city": city}), ["Stockholm", "Göteborg"])
        )
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    # Reading preferences drains the last accepted write before asserting final state.
    token = people["newsletter:p@example.com"]["properties"]["newsletter_preferences_token"]
    assert call("preferences", token=token).json() == {
        "cities": ["Göteborg", "Stockholm"],
        "delivery_blocked": False,
    }
    assert people["newsletter:p@example.com"]["properties"]["newsletter_cities"] == ["Göteborg", "Stockholm"]
