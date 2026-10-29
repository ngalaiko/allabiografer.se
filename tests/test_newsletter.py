import ast
import copy
import json
import sqlite3
from datetime import date
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest

from newsletter import PostHog, edition
from newsletter.migrate import cutover_workflows


@pytest.mark.parametrize("edition_day", [14, 15])
def test_city_edition_excludes_films_screened_in_previous_month(tmp_path, edition_day):
    db = tmp_path / "screenings.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE screenings (title, date, time, cinema, ticket_url, city, film_key, tmdb_id)")
        conn.execute("CREATE TABLE films (key, release_date, poster_url, overview, genres, runtime, age_rating)")
        conn.execute(
            "CREATE TABLE movies (tmdb_id, release_date, poster_path, overview_sv, "
            "genres, directors, runtime, age_rating)"
        )
        for title, day, city in [
            ("Ongoing", "2026-10-09", "Stockholm"),
            ("ONGOING!", "2026-10-16", "Stockholm"),
            ("Thursday", "2026-10-15", "Stockholm"),
            ("Thursday", "2026-10-22", "Stockholm"),
            ("Recent return", "2026-10-08", "Stockholm"),
            ("Recent return", "2026-10-16", "Stockholm"),
            ("History boundary", "2026-09-16", "Stockholm"),
            ("History boundary", "2026-10-16", "Stockholm"),
            ("Returning", "2026-09-15", "Stockholm"),
            ("Returning", "2026-10-16", "Stockholm"),
            ("Local debut", "2026-10-10", "Malmö"),
            ("Local debut", "2026-10-22", "Stockholm"),
            ("Local debut", "2026-10-23", "Stockholm"),
            ("Too late", "2026-10-23", "Stockholm"),
            ("Zebra", "2026-10-17", "Stockholm"),
            ("Åter", "2026-10-17", "Stockholm"),
            ("Unknown", "2026-10-17", "Stockholm"),
        ]:
            conn.execute(
                "INSERT INTO screenings VALUES (?, ?, '18:30', 'Bio', 'https://example.com/ticket', ?, ?, NULL)",
                (title, day, city, title),
            )
        conn.executemany(
            "INSERT INTO films (key, release_date, poster_url) VALUES (?, ?, ?)",
            [
                ("Returning", "2026-01-01", "https://example.com/old.jpg"),
                ("Local debut", "2026-01-01", "https://example.com/new.jpg"),
                ("Zebra", "2026-10-20", ""),
                ("Åter", "2026-01-01", ""),
            ],
        )
        # Original release year wins over a cinema's re-release date.
        conn.execute(
            "INSERT INTO movies VALUES (1, '1999-01-01', '/old.jpg', 'Original synopsis', "
            "'[\"Drama\"]', '[\"Director\"]', 123, '15 år')"
        )
        conn.execute(
            "UPDATE films SET overview = 'Scraped synopsis', genres = '[\"Komedi\"]', runtime = 90 "
            "WHERE key = 'Local debut'"
        )
        conn.execute("UPDATE screenings SET tmdb_id = 1 WHERE title = 'Returning'")
    result = edition(db, "Stockholm", date(2026, 10, edition_day))
    assert [f["title"] for f in result["films"]] == ["Local debut", "Zebra", "Åter", "Returning", "Unknown"]
    assert result["films"][0]["poster"] == "https://example.com/new.jpg"
    assert [f["year"] for f in result["films"]] == [2026, 2026, 2026, 1999, None]
    assert (result["start"], result["end"]) == ("2026-10-16", "2026-10-22")
    assert result["films"][0]["description"] == "Scraped synopsis"
    assert result["films"][0]["genres"] == ["Komedi"]
    assert result["films"][3]["directors"] == ["Director"]
    assert result["films"][3]["runtime"] == 123
    assert result["films"][3]["age_rating"] == "15 år"
    movie_url = urlsplit(result["films"][2]["url"])
    assert movie_url.fragment == "film-%C3%A5ter"
    assert movie_url.path == "/stad/stockholm/"
    genre = result["films"][0]["genre_links"][0]
    assert genre["name"] == "Komedi"
    assert urlsplit(genre["url"]).path == "/stad/stockholm/genre/komedi/"
    for url, content in [
        (result["films"][2]["url"], "movie"),
        (genre["url"], "genre"),
        (result["city_url"], "city"),
        (result["home_url"], "home"),
    ]:
        assert parse_qs(urlsplit(url).query) == {
            "utm_source": ["allabiografer.se"],
            "utm_medium": ["email"],
            "utm_campaign": ["weekly-2026-10-16"],
            "utm_content": [content],
        }
    with pytest.raises(ValueError, match="city"):
        edition(db, "", date(2026, 10, 15))

    with sqlite3.connect(db) as conn:
        # Same-day shows count separately, including normalized title variants.
        conn.executemany(
            "INSERT INTO screenings VALUES (?, '2026-10-16', ?, 'Bio', "
            "'https://example.com/ticket', 'Stockholm', 'Returning', 1)",
            [("Returning", "20:00"), ("RETURNING!", "21:00")],
        )
        conn.execute(
            "INSERT INTO screenings VALUES ('Zebra', '2026-10-17', '20:00', 'Bio', "
            "'https://example.com/ticket', 'Stockholm', 'Zebra', NULL)"
        )
    ranked = edition(db, "Stockholm", date(2026, 10, edition_day))
    assert [f["title"] for f in ranked["films"]] == ["RETURNING!", "Zebra", "Local debut", "Åter", "Unknown"]


@pytest.mark.parametrize("truncated", [False, True])
def test_registered_cities_query(monkeypatch, truncated):
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "123")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "test-key")

    def respond(request, timeout):
        assert request.full_url == "https://eu.posthog.com/api/projects/123/query/"
        query = json.loads(request.data)
        assert query["refresh"] == "force_blocking"
        assert "JSONExtract(properties, 'newsletter_cities', 'Array(String)')" in query["query"]["query"]
        assert "newsletter_subscribed_city_" not in query["query"]["query"]
        assert "properties.newsletter_confirmed = 'yes'" in query["query"]["query"]
        return BytesIO(json.dumps({"results": [["Göteborg"], ["Malmö"]], "hasMore": truncated}).encode())

    monkeypatch.setattr("newsletter.urlopen", respond)
    if truncated:
        with pytest.raises(ValueError, match="truncated"):
            PostHog().cities()
    else:
        assert PostHog().cities() == ["Göteborg", "Malmö"]


class FakePostHog(PostHog):
    """In-memory API model: batch records are the observable send outcome."""

    def __init__(self):
        self.base = "https://eu.posthog.com/api/projects/123/hog_flows/"
        self.categories = []
        self.deliveries = {}
        self.flows = []
        self.jobs = []
        self.invocations = []
        self.test_result = {"status": "success", "errors": [], "logs": []}
        self.fail_send = False
        self.people = [
            {
                "uuid": "reader-profile",
                "distinct_ids": ["existing-reader"],
                "properties": {"email": "reader@example.org", "newsletter_preferences_token": "signed-link"},
            }
        ]
        self.template = {
            "status": "active",
            "trigger_masking": {
                "hash": "{person.id}:{event.properties.newsletter.city}:{event.properties.newsletter.start}",
                "ttl": 604800,
            },
            "actions": [
                {
                    "id": "trigger",
                    "type": "trigger",
                    "config": {
                        "type": "event",
                        "filters": {
                            "events": [{"id": "newsletter_edition_ready"}],
                            "properties": [
                                {
                                    "key": "newsletter_confirmed",
                                    "type": "person",
                                    "operator": "exact",
                                    "value": ["yes"],
                                },
                            ],
                        },
                    },
                },
                {
                    "id": "email",
                    "type": "function_email",
                    "config": {
                        "template_id": "template-email",
                        "template_uuid": "library-template",
                        "message_category_type": "marketing",
                        "inputs": {
                            "email": {
                                "value": {
                                    "from": {"integrationId": 7},
                                    "to": {"email": "{{ person.properties.email }}"},
                                    "subject": "Old subject",
                                    "html": "Old HTML",
                                    "text": "Old text",
                                    "design": {"old": True},
                                }
                            }
                        },
                    },
                },
                {"id": "exit", "type": "exit", "config": {}},
            ],
            "edges": [{"from": "trigger", "to": "email"}, {"from": "email", "to": "exit"}],
        }

    def request(self, method, path="", body=None):
        if "persons/" in path:
            if "?" in path:
                return {"results": copy.deepcopy(self.people)}
            return copy.deepcopy(self.people[0])
        if "messaging_categories/" in path:
            if method == "GET":
                return {"results": copy.deepcopy(self.categories)}
            category = {"id": body["key"], **copy.deepcopy(body)}
            self.categories.append(category)
            return category
        if method == "GET":
            if path.startswith("?"):
                name = parse_qs(path[1:])["search"][0]
                return {"results": [copy.deepcopy(f) for f in self.deliveries.values() if f["name"] == name]}
            if path.rstrip("/") in self.deliveries:
                return copy.deepcopy(self.deliveries[path.rstrip("/")])
            return copy.deepcopy(self.template)
        if method == "PATCH":
            flow = self.deliveries[path.rstrip("/")]
            flow.update(body)
            return copy.deepcopy(flow)
        if not path:
            if body["name"].startswith("allabiografer:delivery:"):
                flow = {**copy.deepcopy(body), "id": f"delivery-{len(self.deliveries)}"}
                self.deliveries[flow["id"]] = flow
                return copy.deepcopy(flow)
            flow = {**copy.deepcopy(body), "id": "edition"}
            self.flows.append(flow)
            return flow
        if path.endswith("/invocations/"):
            self.invocations.append(copy.deepcopy(body))
            if self.fail_send:
                raise TimeoutError("Response lost after test was accepted")
            return copy.deepcopy(self.test_result)
        self.jobs.append({"id": "batch", "workflow": self.flows[-1], **copy.deepcopy(body)})
        if self.fail_send:
            raise TimeoutError("Response lost after server accepted batch")
        return self.jobs[-1]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_posthog_preserves_audience_and_allows_repeating_an_edition(ambiguous):
    api = FakePostHog()
    api.fail_send = ambiguous
    data = {
        "city": "Stockholm",
        "start": "2026-10-16",
        "end": "2026-10-22",
        "films": [{"title": "Ö O'Brien \\ {{ person.email }}\n", "description": "film " * 10000, "year": 2026}],
    }
    if ambiguous:
        with pytest.raises(TimeoutError):
            api.send("template", data)
    else:
        assert api.send("template", data) == "batch"
    initial_jobs = 1
    assert len(api.jobs) == initial_jobs
    api.fail_send = False
    assert api.send("template", data) == "batch"
    assert len(api.jobs) == initial_jobs + 1
    assert [flow["name"] for flow in api.flows] == ["allabiografer:Stockholm:2026-10-16"] * (initial_jobs + 1)
    sent = api.jobs[0]["workflow"]["actions"]
    assert sent[0]["config"]["filters"]["properties"] == [
        {"key": "newsletter_confirmed", "type": "person", "operator": "exact", "value": ["yes"]},
        {
            "type": "hogql",
            "key": "has(JSONExtract(ifNull(properties.newsletter_cities, '[]'), 'Array(String)'), 'Stockholm')",
        },
    ]
    assert sent[0]["config"]["type"] == "batch"
    assert sent[1]["type"] == "function"
    assert sent[1]["config"]["template_id"] == "template-posthog-capture"
    inputs = sent[1]["config"]["inputs"]
    assert inputs["event"]["value"] == "newsletter_edition_ready:Stockholm"
    assert inputs["distinct_id"]["value"] == "{event.distinct_id}"
    expression = inputs["properties"]["value"]["newsletter"]
    assert expression.startswith("{jsonParse(")
    assert expression.endswith(")}")
    assert json.loads(ast.literal_eval(expression[len("{jsonParse(") : -2])) == data
    assert api.jobs[0]["workflow"]["variables"] == []
    assert "variables" not in api.jobs[0]
    assert api.template["actions"][1]["type"] == "function_email"


def test_shared_workflow_keeps_city_audiences_separate():
    api = FakePostHog()
    for city in ["Göteborg", "Malmö"]:
        api.send("template", {"city": city, "start": "2026-10-16", "end": "2026-10-22", "films": []})
    assert [job["workflow"]["actions"][0]["config"]["filters"]["properties"][-1]["key"] for job in api.jobs] == [
        "has(JSONExtract(ifNull(properties.newsletter_cities, '[]'), 'Array(String)'), 'Göteborg')",
        "has(JSONExtract(ifNull(properties.newsletter_cities, '[]'), 'Array(String)'), 'Malmö')",
    ]
    assert len(api.template["actions"][0]["config"]["filters"]["properties"]) == 1


def test_city_delivery_uses_property_membership_and_deduplication_across_editions():
    api = FakePostHog()
    for city, start in [("Göteborg", "2026-10-16"), ("Stockholm", "2026-10-16"), ("Göteborg", "2026-10-23")]:
        api.send("template", {"city": city, "start": start, "end": start, "films": []})
    assert api.categories == []
    assert len(api.deliveries) == 2
    assert {job["workflow"]["actions"][1]["config"]["inputs"]["event"]["value"] for job in api.jobs} == {
        "newsletter_edition_ready:Göteborg",
        "newsletter_edition_ready:Stockholm",
    }
    for flow in api.deliveries.values():
        city = flow["name"].removeprefix("allabiografer:delivery:")
        trigger, email, _ = flow["actions"]
        assert trigger["config"]["filters"]["events"][0]["id"] == f"newsletter_edition_ready:{city}"
        assert not email["config"].get("message_category_id")
        assert email["config"]["message_category_type"] == "marketing"
        assert {"type": "hogql", "key": f"has(person.properties.newsletter_cities, '{city}')"} in trigger["config"][
            "filters"
        ]["properties"]
        assert flow["trigger_masking"] == api.template["trigger_masking"]
        assert email["config"]["inputs"]["email"]["value"]["to"] == {"email": "{{ person.properties.email }}"}


@pytest.mark.parametrize("unsafe", ["paused", "wrong_category", "wrong_event", "no_dedup"])
def test_invalid_city_delivery_never_dispatches(unsafe):
    api = FakePostHog()
    data = {"city": "Göteborg", "start": "2026-10-16", "end": "2026-10-22", "films": []}
    api.send("template", data)
    flow = next(iter(api.deliveries.values()))
    if unsafe == "paused":
        flow["email_sending_paused_at"] = "2026-10-16T12:00:00Z"
    elif unsafe == "wrong_category":
        flow["actions"][1]["config"]["message_category_id"] = "newsletter-city-stockholm"
    elif unsafe == "wrong_event":
        flow["actions"][0]["config"]["filters"]["events"][0]["id"] = "newsletter_edition_ready:Stockholm"
    else:
        flow["trigger_masking"]["ttl"] = 60
    jobs_before = len(api.jobs)
    with pytest.raises(ValueError, match="Invalid or paused"):
        api.send("template", data)
    assert len(api.jobs) == jobs_before


def test_existing_category_consent_requires_explicit_migration():
    api = FakePostHog()
    api.template["actions"][1]["config"]["message_category_id"] = "old-newsletter"
    with pytest.raises(ValueError, match="Migrate"):
        api.send("template", {"city": "Stockholm", "start": "2026-10-16", "end": "2026-10-22", "films": []})
    assert api.jobs == []
    assert api.deliveries == {}


@pytest.mark.parametrize("unknown_category", [False, True])
def test_workflow_cutover_preserves_filters_and_rejects_unknown_consent(unknown_category):
    class CutoverAPI(FakePostHog):
        def request(self, method, path="", body=None):
            if path.startswith("?search=allabiografer%3Adelivery%3A"):
                return {"results": list(copy.deepcopy(self.deliveries).values())}
            result = super().request(method, path, body)
            if method == "GET" and path == "old/":
                result["actions"][0]["config"]["filters"]["bytecode"] = ["server-compiled"]
            return result

    api = CutoverAPI()
    api.categories = [{"id": "cat-g", "key": "newsletter-city-goteborg"}]
    flow = copy.deepcopy(api.template)
    flow.update(id="old", name="allabiografer:delivery:Göteborg")
    flow["actions"][1]["config"]["message_category_id"] = "unknown" if unknown_category else "cat-g"
    api.deliveries["old"] = flow
    before = copy.deepcopy(flow)
    if unknown_category:
        with pytest.raises(ValueError, match="preserve its opt-outs"):
            cutover_workflows(api)
        assert api.deliveries["old"] == before
    else:
        assert cutover_workflows(api) == 1
        migrated = api.deliveries["old"]
        assert migrated["actions"][0]["config"]["filters"]["properties"] == [
            *before["actions"][0]["config"]["filters"]["properties"],
            {"type": "hogql", "key": "has(person.properties.newsletter_cities, 'Göteborg')"},
        ]
        expected_email = before["actions"][1]
        expected_email["config"]["message_category_id"] = None
        assert migrated["actions"][1] == expected_email
        assert cutover_workflows(api) == 1  # Idempotent, without duplicated filters.
        assert api.deliveries["old"] == migrated
    assert api.jobs == []


def test_city_membership_expressions_escape_literals_in_both_scopes():
    api = FakePostHog()
    api.send("template", {"city": "Göte'borg\\East", "start": "2026-10-16", "end": "2026-10-22", "films": []})
    batch = api.jobs[0]["workflow"]["actions"][0]["config"]["filters"]["properties"][-1]
    assert batch == {
        "type": "hogql",
        "key": "has(JSONExtract(ifNull(properties.newsletter_cities, '[]'), 'Array(String)'), 'Göte\\'borg\\\\East')",
    }
    event = next(iter(api.deliveries.values()))["actions"][0]["config"]["filters"]["properties"][-1]
    assert event == {"type": "hogql", "key": "has(person.properties.newsletter_cities, 'Göte\\'borg\\\\East')"}


def test_overlapping_audiences_require_delivery_deduplication():
    api = FakePostHog()
    api.template["trigger_masking"] = None
    with pytest.raises(ValueError, match="deduplicate"):
        api.send("template", {"city": "Stockholm", "start": "2026-10-16", "end": "2026-10-22", "films": []})
    assert api.jobs == []


def test_posthog_requires_confirmed_audience():
    api = FakePostHog()
    api.template["actions"][0]["config"]["filters"]["properties"] = []
    with pytest.raises(ValueError, match="Audience requires"):
        api.send("template", {"city": "Malmö", "start": "2026-10-16", "end": "2026-10-22", "films": []})
    assert api.jobs == []


@pytest.mark.parametrize("invalid", ["draft", "wrong_event"])
def test_delivery_must_be_listening_before_dispatch(invalid):
    api = FakePostHog()
    if invalid == "draft":
        api.template["status"] = "draft"
    else:
        api.template["actions"][0]["config"]["filters"]["events"] = [{"id": "other_event"}]
    with pytest.raises(ValueError, match=r"active event|must listen"):
        api.send("template", {"city": "Malmö", "start": "2026-10-16", "end": "2026-10-22", "films": []})
    assert api.flows == []
    assert api.jobs == []


@pytest.mark.parametrize("outcome", ["success", "skipped", "error", "timeout"])
def test_single_recipient_test_never_enables_or_batches(outcome):
    api = FakePostHog()
    api.template["actions"][0]["config"]["type"] = "manual"
    email_config = api.template["actions"][1]["config"]
    email_config["inputs"]["email"]["value"]["to"] = {"email": "{{ variables.email }}"}
    api.fail_send = outcome == "timeout"
    if outcome == "skipped":
        api.test_result["logs"] = [{"message": "Skipping send: recipient opted out"}]
    elif outcome == "error":
        api.test_result["status"] = "error"
        api.test_result["errors"] = ["Sender unverified"]
    data = {"city": "Göteborg", "films": [{"title": "A & B", "year": 2026}]}
    if outcome == "success":
        assert api.send_test("manual", "reader@example.org", data) == "edition"
    else:
        with pytest.raises(TimeoutError if outcome == "timeout" else ValueError):
            api.send_test("manual", "reader@example.org", data)
    assert api.jobs == []
    assert len(api.invocations) == 1
    assert api.flows[0]["status"] == "draft"
    invocation = api.invocations[0]
    assert invocation["current_action_id"] == "email"
    assert invocation["mock_async_functions"] is False
    assert invocation["globals"]["variables"] == {"email": "reader@example.org"}
    assert invocation["globals"]["event"]["properties"]["newsletter"] == data
    assert invocation["globals"]["event"]["distinct_id"] == "existing-reader"
    assert invocation["globals"]["person"]["properties"]["newsletter_preferences_token"] == "signed-link"
    value = api.flows[0]["actions"][1]["config"]["inputs"]["email"]["value"]
    assert value == {"from": {"integrationId": 7}, "to": {"email": "{{ variables.email }}"}}
    assert not api.flows[0]["actions"][1]["config"].get("message_category_id")


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "unmigrated", "different-email"])
def test_single_recipient_test_requires_matching_migrated_profile(invalid):
    api = FakePostHog()
    api.template["actions"][0]["config"]["type"] = "manual"
    api.template["actions"][1]["config"]["inputs"]["email"]["value"]["to"] = {"email": "{{ variables.email }}"}
    if invalid == "missing":
        api.people = []
    elif invalid == "duplicate":
        api.people *= 2
    elif invalid == "unmigrated":
        del api.people[0]["properties"]["newsletter_preferences_token"]
    else:
        api.people[0]["properties"]["email"] = "different@example.org"
    with pytest.raises(ValueError, match=r"profile|preferences"):
        api.send_test("manual", "reader@example.org", {"city": "Göteborg", "films": []})
    assert api.flows == []
    assert api.invocations == []


@pytest.mark.parametrize("unsafe", ["multiple", "cc", "batch"])
def test_single_recipient_test_rejects_broader_delivery(unsafe):
    api = FakePostHog()
    api.template["actions"][0]["config"]["type"] = "batch" if unsafe == "batch" else "manual"
    value = api.template["actions"][1]["config"]["inputs"]["email"]["value"]
    value["to"] = {"email": "{{ variables.email }}"}
    if unsafe == "cc":
        value["cc"] = [{"email": "someone@example.org"}]
    recipient = "one@example.org,two@example.org" if unsafe == "multiple" else "one@example.org"
    error = {"multiple": "exactly one email", "cc": "only variables.email", "batch": "manual → email"}[unsafe]
    with pytest.raises(ValueError, match=error):
        api.send_test("manual", recipient, {"city": "Göteborg", "films": []})
    assert api.flows == []
    assert api.invocations == []
    assert api.jobs == []
