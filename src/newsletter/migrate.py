"""Backfill newsletter membership arrays and signed links; dry-run unless --apply."""

import argparse
import hashlib
import hmac
import json
import os
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from build import _slugify
from newsletter import CITY_PREFIX, PostHog, city_filter


def membership(properties: dict) -> list[str]:
    existing = properties.get("newsletter_cities", [])
    if not isinstance(existing, list) or any(not isinstance(city, str) for city in existing):
        raise ValueError("Invalid newsletter_cities; refusing to replace it")
    if "newsletter_cities" in properties:
        # Once migrated, [] is an unsubscribe, never an invitation to restore old keys.
        return sorted(set(existing))
    cities = set(existing)
    if properties.get("newsletter_city"):
        cities.add(properties["newsletter_city"])
    cities.update(
        key.removeprefix(CITY_PREFIX)
        for key, value in properties.items()
        if key.startswith(CITY_PREFIX) and value == "yes"
    )
    return sorted(city for city in cities if city)


def active_membership(client: PostHog, properties: dict, categories: list[dict]) -> list[str]:
    cities = membership(properties)
    if "newsletter_cities" in properties or not properties.get("email"):
        return cities
    by_key = {category["key"]: category for category in categories}
    keys = [None, *("newsletter-city-" + _slugify(city) for city in cities)]
    base = client.base.removesuffix("hog_flows/") + "messaging_preferences/opt_outs/?"
    for key in keys:
        if key is not None and key not in by_key:
            continue
        query = {"search": properties["email"], "page_size": 100}
        if key:
            query["category_key"] = key
        page = client.request("GET", base + urlencode(query))
        if isinstance(page, dict) and page.get("next"):
            raise ValueError("Opt-out lookup truncated")
        for entry in page.get("results", []) if isinstance(page, dict) else page:
            if entry["identifier"] != properties["email"]:
                continue
            prefs = entry.get("preferences") or {}
            if prefs.get("$all") == "OPTED_OUT":
                return []
            return [
                city
                for city in cities
                if prefs.get(str(by_key.get("newsletter-city-" + _slugify(city), {}).get("id"))) != "OPTED_OUT"
            ]
    return cities


def preferences_token(secret: str, identifier: str) -> str:
    signature = hmac.new(
        secret.encode(), f"newsletter-preferences:v1:{identifier}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{identifier}.{signature}"


def migrate(client: PostHog, secret: str, *, apply: bool = False, prune: bool = False) -> dict:
    if len(secret) < 32:
        raise ValueError("NEWSLETTER_SIGNING_SECRET must have at least 32 characters")
    public_key = os.environ.get("POSTHOG_PROJECT_TOKEN")
    if apply and not public_key:
        raise ValueError("POSTHOG_PROJECT_TOKEN is required to apply the migration")
    base = client.base.removesuffix("hog_flows/") + "persons/"
    url = base + "?limit=100"
    category_page = client.request("GET", client.base.removesuffix("hog_flows/") + "messaging_categories/?limit=1000")
    if category_page.get("next"):
        raise ValueError("Category lookup truncated")
    counts = {"people": 0, "updates": 0, "legacy_properties": 0}
    while url:
        page = client.request("GET", url)
        # Never follow an upstream next URL outside the exact person collection.
        next_url = page.get("next")
        if next_url and not next_url.startswith(base + "?"):
            raise ValueError("Unexpected person pagination URL")
        for summary in page["results"]:
            person_url = base + quote(str(summary.get("uuid") or summary["id"]), safe="") + "/"
            person = client.request("GET", person_url)
            properties = person["properties"]
            if not membership(properties) and "newsletter_cities" not in properties:
                continue
            cities = active_membership(client, properties, category_page["results"])
            identifier = str(UUID(person["uuid"]))
            updated = {
                "newsletter_cities": cities,
                "newsletter_preferences_token": preferences_token(secret, identifier),
            }
            legacy = [
                key
                for key in properties
                if key in {"newsletter_city", "newsletter_confirmed"} or key.startswith(CITY_PREFIX)
            ]
            changed = any(properties.get(key) != value for key, value in updated.items()) or (
                "newsletter_preferences_id" in properties
            )
            counts["people"] += 1
            counts["updates"] += changed
            counts["legacy_properties"] += len(legacy)
            if not apply:
                continue
            if changed:
                # Use the same ingestion path as signup; the existing newsletter key needs only Person Read.
                host = "eu" if client.base.startswith("https://eu.posthog.com/") else "us"
                request = Request(
                    f"https://{host}.i.posthog.com/i/v0/e/",
                    data=json.dumps(
                        {
                            "api_key": public_key,
                            "event": "$set",
                            "distinct_id": person["distinct_ids"][0],
                            "properties": {
                                "$process_person_profile": True,
                                "$geoip_disable": True,
                                "$set": updated,
                                "$unset": ["newsletter_preferences_id"],
                            },
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=60) as response:
                    if json.load(response).get("status") not in (1, "Ok"):
                        raise RuntimeError("Person capture not accepted; inspect before rerunning")
            # Read back asynchronous person writes before declaring success or pruning.
            for _ in range(30):
                fresh = client.request("GET", person_url)["properties"]
                if all(fresh.get(key) == value for key, value in updated.items()) and (
                    "newsletter_preferences_id" not in fresh
                ):
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Person update not yet visible; stop and inspect before rerunning")
            if prune and legacy:
                client.request("POST", person_url + "delete_property/", {"$unset": legacy})
                for _ in range(30):
                    fresh = client.request("GET", person_url)["properties"]
                    if not any(key in fresh for key in legacy):
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError("Legacy removal not yet visible; stop and inspect before rerunning")
        url = next_url
    return counts


def cutover_workflows(client: PostHog) -> int:
    """Run only after the person migration: replace native city categories with membership filters."""
    categories = client.request("GET", client.base.removesuffix("hog_flows/") + "messaging_categories/?limit=1000")
    if categories.get("next"):
        raise ValueError("Category lookup truncated")
    category_ids = {c["key"]: str(c["id"]) for c in categories["results"]}
    flows = client.request("GET", "?search=allabiografer%3Adelivery%3A&limit=1000")
    if flows.get("next"):
        raise ValueError("Delivery workflow lookup truncated")
    count = 0
    for summary in flows["results"]:
        if not summary["name"].startswith("allabiografer:delivery:"):
            continue
        city = summary["name"].removeprefix("allabiografer:delivery:")
        flow = client.request("GET", f"{summary['id']}/")
        for action in flow["actions"]:
            if action["type"] == "function_email":
                if action["config"].get("message_category_type") != "marketing":
                    raise ValueError("Refusing to migrate a non-marketing newsletter")
                category_id = action["config"].get("message_category_id")
                if category_id and str(category_id) != category_ids.get("newsletter-city-" + _slugify(city)):
                    raise ValueError("Unknown newsletter category; preserve its opt-outs before cutover")
                action["config"]["message_category_id"] = None
            elif action["type"] == "trigger":
                properties = action["config"]["filters"].setdefault("properties", [])
                condition = city_filter(city)
                if condition not in properties:
                    properties.append(condition)
                action["config"]["filters"].pop("bytecode", None)
        client.request("PATCH", f"{summary['id']}/", {"actions": flow["actions"]})
        fresh = client.request("GET", f"{summary['id']}/")
        # PostHog regenerates compiled bytecode; verify the public filter/category fields.
        for action in fresh["actions"]:
            if action["type"] == "trigger" and city_filter(city) not in action["config"]["filters"]["properties"]:
                raise RuntimeError("Workflow cutover did not match; inspect before sending")
            if action["type"] == "function_email" and (
                action["config"].get("message_category_id")
                or action["config"].get("message_category_type") != "marketing"
            ):
                raise RuntimeError("Workflow cutover did not match; inspect before sending")
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write and verify backfilled properties in PostHog")
    parser.add_argument("--prune", action="store_true", help="Also remove verified legacy city keys (requires --apply)")
    parser.add_argument(
        "--cutover", action="store_true", help="After backfill, update city delivery workflows (requires --apply)"
    )
    args = parser.parse_args()
    if (args.prune or args.cutover) and not args.apply:
        parser.error("--prune and --cutover require --apply")
    client = PostHog()
    counts = migrate(client, os.environ["NEWSLETTER_SIGNING_SECRET"], apply=args.apply, prune=args.prune)
    if args.cutover:
        counts["workflows"] = cutover_workflows(client)
    print("Applied" if args.apply else "Dry run (no writes)", counts)


if __name__ == "__main__":
    main()
