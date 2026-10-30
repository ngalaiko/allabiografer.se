"""Private newsletter browser contracts, using the real generated page and assets."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from build import SiteData, _build_newsletter_preferences, _make_env, _write_newsletter_cities

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
URL = "https://allabiografer.test/nyhetsbrev/installningar/"


def test_newsletter_city_allowlist_contains_every_current_city(tmp_path):
    sd = SiteData(out_dir=tmp_path, cities={"Göteborg": 10, "Åmål": 0, "Örnsköldsvik": 2})
    _write_newsletter_cities(sd)
    assert json.loads((tmp_path / "i/newsletter-cities.json").read_text()) == {
        "Göteborg": "newsletter-city-goteborg",
        "Åmål": "newsletter-city-amal",
        "Örnsköldsvik": "newsletter-city-ornskoldsvik",
    }


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        if not executable and not Path(runtime.chromium.executable_path).exists():
            pytest.skip("Chromium is not available")
        instance = runtime.chromium.launch(executable_path=executable)
        yield instance
        instance.close()


@pytest.fixture
def preferences(browser, tmp_path):
    env = _make_env()
    env.globals["posthog_token"] = "must-not-appear-on-private-page"
    _build_newsletter_preferences(env, tmp_path)
    html = (tmp_path / "nyhetsbrev/installningar/index.html").read_text()
    assert "must-not-appear" not in html
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    state = {
        "cities": ["Göteborg", "Stockholm"],
        "delivery_blocked": False,
    }
    calls = []
    pending = []
    errors = []
    options = {"status": 200, "hold": False}
    page.on("pageerror", lambda error: errors.append(str(error)))

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/api/newsletter/preferences":
            assert route.request.method == "POST"
            assert route.request.headers["authorization"] == "Bearer test-only"
            assert "referer" not in route.request.headers
            data = route.request.post_data_json
            calls.append(data)
            if options["hold"]:
                pending.append(route)
                return
            if options["status"] == 200 and data:
                assert data.get("unsubscribe") is True
                assert set(data) <= {"city", "unsubscribe"}
                if "city" in data:
                    assert data["city"] in state["cities"]
                    state["cities"].remove(data["city"])
                else:
                    state["cities"] = []
            route.fulfill(status=options["status"], json=state)
        elif path.startswith("/i/"):
            route.fulfill(path=ROOT / "static" / path.lstrip("/"))
        else:
            assert path == "/nyhetsbrev/installningar/"
            route.fulfill(body=html, content_type="text/html")

    page.route("https://allabiografer.test/**", serve)
    yield page, state, calls, options, pending
    assert not errors
    page.close()


@pytest.mark.parametrize("width", [375, 1280])
def test_preferences_remove_city_all_canonical_and_privacy(preferences, width):
    page, state, calls, _, _ = preferences
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(URL + "#token=test-only")
    playwright.expect(page.get_by_role("status")).to_contain_text("hämtade")
    assert page.url == URL
    assert page.locator('meta[name="robots"]').get_attribute("content") == "noindex, nofollow"
    assert page.locator('meta[name="referrer"]').get_attribute("content") == "no-referrer"
    assert page.locator("script").count() == 1
    assert page.locator("input, select, form").count() == 0
    assert page.locator(".preferences-city").count() == 2
    assert calls == [{}]
    page.get_by_role("button", name="Avsluta Göteborg", exact=True).click()
    playwright.expect(page.get_by_role("status")).to_contain_text("sparats")
    assert calls[-2:] == [{"city": "Göteborg", "unsubscribe": True}, {}]
    playwright.expect(page.get_by_role("button", name="Avsluta Göteborg", exact=True)).to_have_count(0)
    assert state["cities"] == ["Stockholm"]
    playwright.expect(page.get_by_role("button", name="Avsluta Stockholm", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Avsluta alla prenumerationer").click()
    playwright.expect(page.get_by_role("status")).to_contain_text("sparats")
    assert calls[-2:] == [{"unsubscribe": True}, {}]
    assert state["cities"] == []
    assert page.locator(".preferences-city").count() == 0
    playwright.expect(page.locator("#preferences-cities")).to_contain_text("inte på någon stad")
    playwright.expect(page.locator("#preferences-unsubscribe-all")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length") == 0
    page.reload()
    playwright.expect(page.get_by_role("alert")).to_contain_text("saknar behörighet")


@pytest.mark.parametrize(("token", "status"), [("", 200), ("test-only", 401), ("test-only", 403)])
def test_missing_or_invalid_token(preferences, token, status):
    page, _, calls, options, _ = preferences
    options["status"] = status
    page.goto(URL + ("#token=" + token if token else ""))
    playwright.expect(page.get_by_role("alert")).to_contain_text("nyhetsbrev")
    playwright.expect(page.locator("#preferences-controls")).to_be_hidden()
    assert page.url == URL
    assert len(calls) == bool(token)


def test_failed_save_retry_and_concurrent_controls(preferences):
    page, state, calls, options, pending = preferences
    page.goto(URL + "#token=test-only")
    city = page.get_by_role("button", name="Avsluta Göteborg", exact=True)
    playwright.expect(city).to_be_enabled()
    options["hold"] = True
    city.click()
    playwright.expect(page.get_by_role("status")).to_contain_text("Sparar")
    for control in page.locator("#preferences-controls button").all():
        playwright.expect(control).to_be_disabled()
    assert len(pending) == 1
    options["hold"] = False
    pending.pop().fulfill(status=503, json={})
    playwright.expect(page.get_by_role("alert")).to_contain_text("Försök igen")
    playwright.expect(city).to_be_enabled()
    assert state["cities"] == ["Göteborg", "Stockholm"]
    page.get_by_role("button", name="Försök igen", exact=True).click()
    playwright.expect(page.get_by_role("status")).to_contain_text("hämtade")
    playwright.expect(city).to_be_enabled()  # Read canonical state before retrying a mutation.
    assert calls[-1] == {}


def test_last_city_removal_shows_empty_state(preferences):
    page, state, calls, _, _ = preferences
    state["cities"] = ["Göteborg"]
    page.goto(URL + "#token=test-only")
    page.get_by_role("button", name="Avsluta Göteborg", exact=True).click()
    playwright.expect(page.locator("#preferences-cities")).to_contain_text("inte på någon stad")
    assert calls == [{}, {"city": "Göteborg", "unsubscribe": True}, {}]
    playwright.expect(page.locator("#preferences-unsubscribe-all")).to_be_hidden()


def test_delivery_blocked_warning_does_not_offer_reenable(preferences):
    page, state, calls, _, _ = preferences
    state["cities"] = []
    state["delivery_blocked"] = True
    page.goto(URL + "#token=test-only")
    warning = page.locator("#preferences-delivery-warning")
    playwright.expect(warning).to_be_visible()
    assert warning.get_attribute("role") == "alert"
    playwright.expect(warning).to_contain_text("Du har avslutat nyhetsbrevet.")
    assert "posthog" not in page.locator("body").inner_text().lower()
    playwright.expect(warning).to_contain_text("Prenumerera på en stads programsida")
    playwright.expect(page.locator("#preferences-cities")).to_contain_text("inte på någon stad")
    assert page.locator("input, select").count() == 0
    playwright.expect(page.locator("#preferences-unsubscribe-all")).to_be_hidden()
    assert calls == [{}]
