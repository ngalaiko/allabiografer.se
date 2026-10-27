"""Prepare city editions; PostHog owns audiences, consent and email delivery."""

import argparse
import copy
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from build import BASE_URL, _slugify, _slugify_sv, city_programme_url, film_anchor
from store import DB_FILE, title_key

STOCKHOLM = ZoneInfo("Europe/Stockholm")
NEWSLETTER_EVENT = "newsletter_edition_ready"
CITY_PREFIX = "newsletter_subscribed_city_"


def newsletter_url(url: str, start: date, content: str) -> str:
    """Attribute site visits without including any recipient information."""
    parts = urlsplit(url)
    query = urlencode(
        {
            "utm_source": "allabiografer.se",
            "utm_medium": "email",
            "utm_campaign": f"weekly-{start.isoformat()}",
            "utm_content": content,
        }
    )
    return urlunsplit(parts._replace(query=query))


def edition(db: Path, city: str, today: date) -> dict:
    """Exclude titles screened locally in the 30 days before the Friday–Thursday edition."""
    if not city.strip():
        raise ValueError("A city is required")
    city_url = quote(city_programme_url(city), safe=":/")
    start = today + timedelta(days=(3 - today.weekday()) % 7 + 1)
    previous = start - timedelta(days=30)
    end = start + timedelta(days=7)
    with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT s.title, s.date, coalesce(nullif(m.release_date, ''), f.release_date, ''), "
            "coalesce(nullif(f.poster_url, ''), CASE WHEN m.poster_path != '' "
            "THEN 'https://image.tmdb.org/t/p/w342' || m.poster_path ELSE '' END, ''), "
            "coalesce(nullif(m.overview_sv, ''), f.overview, ''), "
            "coalesce(nullif(m.genres, '[]'), f.genres, '[]'), coalesce(m.directors, '[]'), "
            "coalesce(m.runtime, f.runtime), coalesce(nullif(m.age_rating, ''), f.age_rating, '') "
            "FROM screenings s LEFT JOIN films f ON f.key = s.film_key "
            "LEFT JOIN movies m ON m.tmdb_id = s.tmdb_id "
            "WHERE s.city = ? AND s.date >= ? AND s.date < ? ORDER BY s.title, s.date",
            (city, previous.isoformat(), end.isoformat()),
        ).fetchall()
    old = {title_key(row[0]) for row in rows if row[1] < start.isoformat()}
    films = {}
    screening_counts = Counter()
    for title, day, release, poster, overview, genres, directors, runtime, age_rating in rows:
        key = title_key(title)
        if day < start.isoformat() or not key or key in old:
            continue
        screening_counts[key] += 1
        film = films.setdefault(key, {"title": title, "year": None, "poster": ""})
        if not film["year"] and release[:4].isdigit() and 1000 <= int(release[:4]) <= 9999:
            film["year"] = int(release[:4])
        if not film["poster"] and urlparse(poster).scheme in {"http", "https"}:
            film["poster"] = poster
        film["url"] = newsletter_url(city_url + "#" + quote(film_anchor(film["title"])), start, "movie")
        for field, value in {
            "description": overview,
            "genres": json.loads(genres),
            "directors": json.loads(directors),
            "runtime": runtime,
            "age_rating": age_rating,
        }.items():
            if not film.get(field):
                film[field] = value
    for film in films.values():
        film["genre_links"] = [
            {
                "name": genre,
                "url": newsletter_url(city_url + "genre/" + quote(_slugify_sv(genre)) + "/", start, "genre"),
            }
            for genre in film["genres"]
        ]
    return {
        "city": city,
        "city_url": newsletter_url(city_url, start, "city"),
        "home_url": newsletter_url(BASE_URL + "/", start, "home"),
        "start": start.isoformat(),
        "end": (end - timedelta(days=1)).isoformat(),
        "films": sorted(
            films.values(),
            key=lambda f: (
                -screening_counts[title_key(f["title"])],
                -(f["year"] or 0),
                title_key(f["title"]).translate(str.maketrans({"å": "{", "ä": "|", "ö": "}"})),
            ),
        ),
    }


class PostHog:
    def __init__(self):
        self.base = os.environ.get("POSTHOG_API_HOST", "https://eu.posthog.com").rstrip("/")
        if self.base not in {"https://eu.posthog.com", "https://us.posthog.com", "https://app.posthog.com"}:
            raise ValueError("Use a PostHog Cloud API host, not the analytics ingestion host")
        self.base += f"/api/projects/{quote(os.environ['POSTHOG_PROJECT_ID'], safe='')}/hog_flows/"
        self.token = os.environ["POSTHOG_PERSONAL_API_KEY"]

    def request(self, method: str, path: str = "", body: dict | None = None):
        url = path if path.startswith("https://") else self.base + path
        project = self.base.removesuffix("hog_flows/")
        if not (url.startswith((self.base, project + "messaging_categories/")) or url == project + "query/"):
            raise ValueError("Refusing to send credentials outside the workflow, category and query APIs")
        req = Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        # Writes deliberately have no automatic retries: an uncertain send needs reconciliation.
        with urlopen(req, timeout=60) as response:
            return json.load(response)

    def category(self, city: str) -> dict:
        url = self.base.removesuffix("hog_flows/") + "messaging_categories/"
        categories = self.request("GET", url + "?limit=1000")
        if categories.get("next"):
            raise ValueError("Marketing category lookup was truncated")
        key = "newsletter-city-" + _slugify(city)
        category = next((c for c in categories["results"] if c["key"] == key), None)
        if not category:
            category = self.request(
                "POST",
                url,
                {
                    "key": key,
                    "name": f"Nytt på bio i {city}",
                    "public_description": f"Ett mejl varje torsdag med nya filmer på bio i {city}.",
                    "category_type": "marketing",
                },
            )
        if category["category_type"] != "marketing":
            raise ValueError(f"The newsletter category for {city} must be marketing")
        return category

    def delivery(self, source: dict, city: str) -> dict:
        """Reuse a persistent city workflow so opt-outs and edition dedup survive each batch."""
        name = f"allabiografer:delivery:{city}"
        flows = self.request("GET", "?" + urlencode({"search": name, "limit": 100}))
        if flows.get("next"):
            raise ValueError("City delivery lookup was truncated")
        matches = [flow for flow in flows["results"] if flow["name"] == name]
        if len(matches) > 1:
            raise ValueError(f"Multiple delivery workflows for {city}; reconcile before sending")
        email = next(a for a in source["actions"] if a["type"] == "function_email")
        if email["config"].get("message_category_id"):
            raise ValueError("Migrate the template category's opt-outs before creating city delivery workflows")
        category = self.category(city)
        event = f"{NEWSLETTER_EVENT}:{city}"
        if matches:
            flow = self.request("GET", f"{quote(matches[0]['id'], safe='')}/")
        else:
            actions = copy.deepcopy(source["actions"])
            trigger = next(a for a in actions if a["type"] == "trigger")
            trigger["config"]["filters"] = {
                "events": [{"id": event, "type": "events", "order": 0}],
                "properties": trigger["config"]["filters"].get("properties", []),
            }
            next(a for a in actions if a["type"] == "function_email")["config"]["message_category_id"] = category["id"]
            flow = self.request(
                "POST",
                body={
                    "name": name,
                    "description": f"Newsletter delivery for {city}; uses its own marketing opt-out category.",
                    "status": "draft",
                    "actions": actions,
                    "edges": source["edges"],
                    "trigger_masking": {k: v for k, v in source["trigger_masking"].items() if k != "bytecode"},
                    "email_sending_rate_limit": source.get("email_sending_rate_limit"),
                    "exit_condition": "exit_only_at_end",
                },
            )
            # Enabling listens only for the new city event; it never starts a batch.
            flow = self.request("PATCH", f"{flow['id']}/", {"status": "active"})
        emails = [a for a in flow["actions"] if a["type"] == "function_email"]
        triggers = [a for a in flow["actions"] if a["type"] == "trigger"]
        if (
            flow["status"] != "active"
            or flow.get("email_sending_paused_at")
            or len(emails) != 1
            or len(triggers) != 1
            or triggers[0]["config"]["type"] != "event"
            or [e.get("id") for e in triggers[0]["config"]["filters"].get("events", [])] != [event]
            or emails[0]["config"].get("message_category_id") != category["id"]
            or emails[0]["config"].get("message_category_type") != "marketing"
            or flow.get("trigger_masking", {}).get("hash") != source["trigger_masking"]["hash"]
            or (flow.get("trigger_masking", {}).get("ttl") or 0) < 604800
            or flow.get("trigger_masking", {}).get("threshold") is not None
        ):
            raise ValueError(f"Invalid or paused city delivery workflow for {city}; no batch dispatched")
        return flow

    def cities(self) -> list[str]:
        """Fetch distinct registered cities, never subscriber addresses."""
        result = self.request(
            "POST",
            self.base.removesuffix("hog_flows/") + "query/",
            {
                "name": "Newsletter registered cities",
                "refresh": "force_blocking",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT DISTINCT city FROM ("
                    "SELECT properties.newsletter_city AS city FROM persons "
                    "WHERE properties.newsletter_confirmed = 'yes' AND properties.email != '' "
                    "UNION ALL SELECT arrayJoin(arrayMap(key -> "
                    f"substring(key, {len(CITY_PREFIX) + 1}, length(key)), arrayFilter(key -> "
                    f"startsWith(key, '{CITY_PREFIX}') AND JSONExtractString(properties, key) = 'yes', "
                    "JSONExtractKeys(properties)))) AS city FROM persons "
                    "WHERE properties.newsletter_confirmed = 'yes' AND properties.email != ''"
                    ") WHERE city != '' ORDER BY city LIMIT 10000",
                },
            },
        )
        rows = result["results"]
        if result.get("hasMore") or len(rows) >= 10000:
            raise ValueError("Registered city query was truncated; refusing a partial newsletter run")
        return [row[0] for row in rows if isinstance(row[0], str) and row[0].strip()]

    def send(self, template_id: str, data: dict) -> str:
        name = f"allabiografer:{data['city']}:{data['start']}"
        source = self.request("GET", f"{quote(template_id, safe='')}/")
        actions = copy.deepcopy(source["actions"])
        triggers = [a for a in actions if a["type"] == "trigger"]
        emails = [a for a in actions if a["type"] == "function_email"]
        if (
            len(triggers) != 1
            or len(emails) != 1
            or any(a["type"] not in {"trigger", "function_email", "exit"} for a in actions)
            or triggers[0]["config"]["type"] != "event"
            or source.get("status") != "active"
            or source.get("email_sending_paused_at")
        ):
            raise ValueError("Use an active event → email → exit workflow for shared delivery")
        events = triggers[0]["config"].get("filters", {}).get("events", [])
        if len(events) != 1 or events[0].get("id") != NEWSLETTER_EVENT:
            raise ValueError(f"Delivery workflow must listen for {NEWSLETTER_EVENT}")
        properties = triggers[0]["config"].get("filters", {}).get("properties", [])
        required = [
            {"key": "newsletter_confirmed", "type": "person", "operator": "exact", "value": ["yes"]},
        ]
        if not isinstance(properties, list) or any(
            not any(all(p.get(k) == v for k, v in condition.items()) for p in properties) for condition in required
        ):
            raise ValueError("Audience requires newsletter_confirmed = yes")
        if any(p.get("key") == "newsletter_city" or p.get("key", "").startswith(CITY_PREFIX) for p in properties):
            raise ValueError("Shared workflow must not restrict newsletter_city; Python adds each city's filter")
        masking = source.get("trigger_masking") or {}
        if (
            masking.get("hash") != "{person.id}:{event.properties.newsletter.city}:{event.properties.newsletter.start}"
            or masking.get("ttl", 0) < 604800
            or masking.get("threshold") is not None
        ):
            raise ValueError("Shared delivery must deduplicate person/city/edition for seven days")
        triggers[0]["config"] = {
            "type": "batch",
            "filters": {
                "properties": [
                    *properties,
                    {"key": "newsletter_city", "type": "person", "operator": "exact", "value": [data["city"]]},
                ]
            },
        }
        config = emails[0]["config"]
        if config.get("message_category_type") != "marketing":
            raise ValueError("The newsletter email must use a PostHog marketing category")
        value = config["inputs"]["email"]["value"]
        if value.get("to", {}).get("email") != "{{ person.properties.email }}" or value.get("cc") or value.get("bcc"):
            raise ValueError("Use the default person email recipient without CC/BCC for audience deduplication")
        if not config.get("template_uuid"):
            raise ValueError("Select a PostHog library email template for the newsletter")
        self.delivery(source, data["city"])
        # Batch overrides are not propagated to runs, and workflow variables have a
        # 5KB limit. Capture the edition as event data instead; PostHog keeps recipients.
        literal = json.dumps(data, ensure_ascii=False).replace("\\", "\\\\").replace("'", "\\'")
        emails[0].update(
            name="Dispatch newsletter edition",
            type="function",
            on_error="abort",
            config={
                "template_id": "template-posthog-capture",
                "inputs": {
                    "event": {"value": f"{NEWSLETTER_EVENT}:{data['city']}"},
                    "distinct_id": {"value": "{event.distinct_id}"},
                    "properties": {"value": {"newsletter": "{jsonParse('" + literal + "')}"}},
                },
            },
        )
        payload = {
            "name": name,
            "description": f"New local films, {data['start']} through {data['end']}",
            "status": "active",
            "actions": actions,
            "edges": source["edges"],
            "variables": [],
            "exit_condition": "exit_only_at_end",
        }
        jobs = []
        # Native batch conditions are AND-only. Preserve legacy subscribers without
        # migration; the shared workflow deduplicates overlap by person/city/edition.
        for key, value in [("newsletter_city", data["city"]), (CITY_PREFIX + data["city"], "yes")]:
            triggers[0]["config"]["filters"]["properties"][-1] = {
                "key": key,
                "type": "person",
                "operator": "exact",
                "value": [value],
            }
            flow = self.request("POST", body=payload)
            job = self.request("POST", f"{flow['id']}/batch_jobs/", {})
            jobs.append(str(job["id"]))
        return ",".join(jobs)

    def send_test(self, workflow_id: str, email: str, data: dict) -> str:
        """Run exactly one email step, without enabling a workflow or expanding an audience."""
        if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", email):
            raise ValueError("Provide exactly one email address")
        source = self.request("GET", f"{quote(workflow_id, safe='')}/")
        actions = copy.deepcopy(source["actions"])
        emails = [a for a in actions if a["type"] == "function_email"]
        triggers = [a for a in actions if a["type"] == "trigger"]
        if (
            len(emails) != 1
            or len(triggers) != 1
            or triggers[0]["config"]["type"] != "manual"
            or any(a["type"] not in {"trigger", "function_email", "exit"} for a in actions)
        ):
            raise ValueError("Use a manual → email → exit workflow for test emails")
        config = emails[0]["config"]
        value = config["inputs"]["email"]["value"]
        if (
            value.get("to", {}).get("email") != "{{ variables.email }}"
            or value.get("cc")
            or value.get("bcc")
            or not config.get("template_uuid")
            or config.get("message_category_type") != "marketing"
        ):
            raise ValueError(
                "Test email requires a library template, marketing type and only variables.email as recipient"
            )
        config["message_category_id"] = self.category(data["city"])["id"]
        for field in ("subject", "text", "html", "design", "preheader"):
            value.pop(field, None)
        config["inputs"]["email"]["templating"] = "liquid"
        # A fresh draft snapshots the latest library template; it never becomes active.
        flow = self.request(
            "POST",
            body={
                "name": f"allabiografer:test:{data['city']}:{uuid4()}",
                "status": "draft",
                "actions": actions,
                "edges": source["edges"],
                "variables": source.get("variables", []),
                "exit_condition": "exit_only_at_end",
            },
        )
        result = self.request(
            "POST",
            f"{flow['id']}/invocations/",
            {
                "current_action_id": emails[0]["id"],
                "mock_async_functions": False,
                "globals": {
                    "event": {
                        "uuid": str(uuid4()),
                        "event": "newsletter_test",
                        "distinct_id": f"newsletter-test:{uuid4()}",
                        "timestamp": datetime.now(STOCKHOLM).isoformat(),
                        "properties": {"newsletter": data},
                    },
                    "variables": {"email": email},
                },
            },
        )
        if (
            result.get("status") != "success"
            or result.get("errors")
            or any("skipping send" in log.get("message", "").lower() for log in result.get("logs", []))
        ):
            raise ValueError(
                f"Test send failed or was skipped. Inspect PostHog workflow {flow['id']}; do not blindly retry."
            )
        return str(flow["id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_FILE)
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(STOCKHOLM).date())
    parser.add_argument("--send", action="store_true", help="Create and dispatch real PostHog batches")
    parser.add_argument("--test-email", help="Send one real test email, without enrolling the recipient")
    parser.add_argument("--city", help="City for --test-email (case-insensitive)")
    parser.add_argument("--output", type=Path, default=Path("newsletter-preview"))
    args = parser.parse_args()
    if args.test_email:
        if args.send or not args.city:
            parser.error("--test-email requires --city and cannot be combined with --send")
        with sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True) as conn:
            city = next(
                (
                    r[0]
                    for r in conn.execute("SELECT DISTINCT city FROM screenings")
                    if r[0].casefold() == args.city.strip().casefold()
                ),
                None,
            )
        if not city:
            parser.error("City not found in scraped screenings")
        thursday = args.date + timedelta(days=(3 - args.date.weekday()) % 7)
        data = edition(args.db, city, thursday)
        if not data["films"]:
            parser.error("No new films for this city and week; no test sent")
        workflow = PostHog().send_test(os.environ["POSTHOG_NEWSLETTER_TEST_WORKFLOW"], args.test_email, data)
        print(f"{city}: test invocation completed in PostHog workflow {workflow}; check delivery in PostHog")
        return
    if args.city:
        parser.error("--city is only used with --test-email")
    client = PostHog()
    cities = client.cities()
    with sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True) as conn:
        known_cities = {row[0] for row in conn.execute("SELECT DISTINCT city FROM screenings")}
    unknown = set(cities) - known_cities
    if unknown:
        parser.error(f"Registered cities not found in scraped screenings: {', '.join(sorted(unknown))}")
    args.output.mkdir(parents=True, exist_ok=True)
    for city in cities:
        data = edition(args.db, city, args.date)
        args.output.joinpath(f"{quote(city, safe='')}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        )
        if not data["films"]:
            print(f"{city}: no new films; skipped")
        elif args.send:
            workflow = client.send(os.environ["POSTHOG_NEWSLETTER_WORKFLOW"], data)
            print(f"{city}: queued batch {workflow} ({len(data['films'])} films)")
        else:
            print(f"{city}: preview only ({len(data['films'])} films)")
