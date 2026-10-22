"""Browser geometry checks for breadcrumbs and cinema locations."""

from base64 import b64encode
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from build import _make_env

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        if not Path(runtime.chromium.executable_path).exists():
            pytest.skip("Install Chromium with playwright install chromium")
        instance = runtime.chromium.launch()
        yield instance
        instance.close()


@pytest.mark.parametrize("width", [375, 1280])
@pytest.mark.parametrize("template", ["program.html", "festival.html"])
def test_breadcrumb_centers(browser, width, template):
    env = _make_env()
    html = env.get_template(template).render(
        breadcrumbs=" / Göteborg / <a href='/bio/'>Biograf</a>",
        festival={"city": "Göteborg", "name": "Filmfestival", "year": 2026, "days": []},
        versions={"css": "test"},
    )
    page = browser.new_page(viewport={"width": width, "height": 800})
    page.set_content(html)
    font = b64encode((ROOT / "static/i/FiraSans-Regular.woff2").read_bytes()).decode()
    page.add_style_tag(content="@font-face {font-family: 'Fira Sans'; src: url(data:font/woff2;base64," + font + ")}")
    page.evaluate("document.fonts.ready")
    for name in ["style.css", "festival.css"]:
        page.add_style_tag(content=(ROOT / "static/i" / name).read_text())
    page.evaluate("document.fonts.ready")
    navs = page.locator(".schedule-breadcrumbs:visible")
    assert navs.count() > 0
    for nav in navs.all():
        geometry = nav.evaluate("""nav => {
            const label = nav.querySelector('.breadcrumb-label');
            const marker = document.createElement('span');
            marker.style.display = 'inline-block';
            label.prepend(marker);
            const baseline = marker.getBoundingClientRect().bottom;
            marker.remove();
            return {iconOffset: nav.querySelector('svg').getBoundingClientRect().bottom - baseline};
        }""")
        # The icon sits on the text baseline, as on allekinos.de.
        assert abs(geometry["iconOffset"]) <= 0.5
    page.close()


@pytest.mark.parametrize("width", [375, 700, 1280])
@pytest.mark.parametrize("city", ["", "Göteborg"])
def test_cinema_address_layout(browser, width, city):
    html = (
        _make_env()
        .get_template("program.html")
        .render(
            num_days=1,
            days=[{"date": "2026-09-30", "label": "Ons 30"}],
            blocks=[
                {
                    "film_title": "Film",
                    "cinemas": [
                        {
                            "name": "Biograf",
                            "url": "/bio/",
                            "address": "Storgatan 1",
                            "city_name": city,
                            "city_url": "/goteborg/",
                            "min_height": 60,
                            "cells": [],
                        }
                    ],
                }
            ],
            versions={"css": "test"},
        )
    )
    page = browser.new_page(viewport={"width": width, "height": 800})
    try:
        page.set_content(html)
        page.add_style_tag(content=(ROOT / "static/i/style.css").read_text())
        address = page.locator(".cinema-address")
        assert address.is_visible()
        name_box = page.locator(".cinema-name > a").bounding_box()
        address_box = address.bounding_box()
        if width <= 700:
            assert address_box["x"] > name_box["x"] + name_box["width"]
            assert abs(address_box["y"] - name_box["y"]) < 4
        else:
            assert address_box["y"] > name_box["y"] + name_box["height"]
    finally:
        page.close()


@pytest.mark.parametrize("toolbar_height", [0, 180])
def test_movie_link_keeps_dates_visible_with_mobile_browser_toolbar(browser, toolbar_height):
    html = (
        _make_env()
        .get_template("program.html")
        .render(
            num_days=2,
            days=[{"date": "2026-10-23", "label": "Fre. 23 okt."}, {"date": "2026-10-24", "label": "Lör. 24 okt."}],
            breadcrumbs=" / Göteborg",
            blocks=[
                {
                    "film_title": title,
                    "film_id": anchor,
                    "film_url": "/film/",
                    "anchors": [anchor],
                    "full_desc": "Film description",
                    "cinemas": [{"name": "Bio Roy", "min_height": 600, "cells": []}],
                }
                for title, anchor in [("Rosetta", "film-rosetta"), ("The Thing", "film-the-thing")]
            ],
        )
    )
    page = browser.new_page(viewport={"width": 402, "height": 740}, is_mobile=True)

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/i/style.css":
            # Mobile Safari's large viewport includes the open browser toolbar;
            # its dynamic viewport is only the visible page. Chromium equates
            # the units, so emulate that difference without changing 100dvh.
            css = (ROOT / "static/i/style.css").read_text().replace("100vh", f"{740 + toolbar_height}px")
            route.fulfill(body=css, content_type="text/css")
        elif path.startswith("/i/"):
            route.fulfill(path=ROOT / "static" / path.lstrip("/"))
        else:
            route.fulfill(body=html, content_type="text/html")

    page.route("https://allabiografer.test/**", serve)
    try:
        page.goto("https://allabiografer.test/stad/goteborg/?utm_medium=email#film-the-thing")
        dates = page.locator(".schedule-dates")
        playwright.expect(dates).to_be_in_viewport(ratio=1)
        playwright.expect(page.locator(":target")).to_be_in_viewport()
        assert page.evaluate("scrollY") == 0
    finally:
        page.close()


@pytest.mark.parametrize("width", [375, 1280])
@pytest.mark.parametrize("blocked_storage", [False, True])
def test_festival_banner_stays_visible_and_remembers_dismissal(browser, width, blocked_storage):
    html = (
        _make_env()
        .get_template("program.html")
        .render(city="Stockholm", num_days=10, blocks=[], breadcrumbs=" / Stockholm")
    )
    context = browser.new_context(viewport={"width": width, "height": 800})
    if blocked_storage:
        context.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw Error('blocked'); }});")
    page = context.new_page()

    def serve(route):
        path = urlsplit(route.request.url).path
        if path.startswith("/i/"):
            route.fulfill(path=ROOT / "static" / path.lstrip("/"))
        else:
            route.fulfill(body=html, content_type="text/html")

    page.route("https://allabiografer.test/**", serve)
    try:
        page.goto("https://allabiografer.test/stad/stockholm/")
        page.add_style_tag(content=".program { min-height: 2000px; }")
        banner = page.get_by_role("complementary", name="Filmfestival")
        playwright.expect(banner.get_by_role("button", name="Stäng festivalbanner")).to_be_visible()
        page.evaluate("document.fonts.ready")
        initial = banner.bounding_box()
        page.evaluate("""() => {
            const scroll = innerWidth <= 700 ? document.querySelector('.schedule-scroll') : window;
            scroll.scrollTo(400, 500);
        }""")
        playwright.expect(banner).to_be_in_viewport()
        scrolled = banner.bounding_box()
        assert scrolled["x"] == pytest.approx(initial["x"])
        assert scrolled["y"] == pytest.approx(initial["y"])
        assert page.locator(".schedule-header").bounding_box()["y"] >= scrolled["y"] + scrolled["height"]
        banner.get_by_role("button", name="Stäng festivalbanner").click()
        playwright.expect(banner).to_be_hidden()
        # Closing the banner also reclaims the sticky header's space immediately.
        assert page.locator(".schedule-header").bounding_box()["y"] == pytest.approx(initial["y"])
        for path in ["/stad/stockholm/", "/stad/stockholm/bio/"]:
            page.goto("https://allabiografer.test" + path)
            if blocked_storage:
                playwright.expect(banner).to_be_visible()
                banner.get_by_role("button", name="Stäng festivalbanner").click()
            playwright.expect(banner).to_be_hidden()
    finally:
        context.close()


@pytest.mark.parametrize("width", [375, 1280])
def test_dense_showtimes_render_only_time_without_overlap(browser, width):
    from datetime import time

    from build import _compute_time_positions

    times = _compute_time_positions(
        [
            (time(18, 0), "/a"),
            (time(18, 5), "/b"),
            (time(18, 15), "/c"),
            (time(21, 0), "/d"),
        ]
    )
    for item in times:
        item["past"] = False
        item["attributes"] = ["VIP"]
    html = (
        _make_env()
        .get_template("program.html")
        .render(
            num_days=1,
            days=[{"date": "2026-10-02", "label": "Fre 2"}],
            blocks=[
                {
                    "film_title": "Film",
                    "film_url": "/film/",
                    "film_id": "film",
                    "variant": "",
                    "cinemas": [
                        {
                            "name": "Bio",
                            "url": "/bio/",
                            "address": "",
                            "city_name": None,
                            "city_url": None,
                            "min_height": 250,
                            "cells": [{"times": times}],
                        }
                    ],
                }
            ],
            versions={"css": "test"},
        )
    )
    page = browser.new_page(viewport={"width": width, "height": 800})
    try:
        page.set_content(html)
        page.add_style_tag(content=(ROOT / "static/i/style.css").read_text())
        entries = page.locator(".schedule-cell > a").all()
        boxes = [entry.bounding_box() for entry in entries]
        assert page.locator(".showtime-attributes").count() == 0
        assert [entry.inner_text() for entry in entries] == ["18:00", "18:05", "18:15", "21:00"]
        container = page.locator(".schedule-times" if width <= 700 else ".schedule-cell").bounding_box()
        assert all(box["x"] >= container["x"] for box in boxes)
        assert all(box["x"] + box["width"] <= container["x"] + container["width"] for box in boxes)
        for index, left in enumerate(boxes):
            for right in boxes[index + 1 :]:
                overlaps_x = left["x"] < right["x"] + right["width"] and right["x"] < left["x"] + left["width"]
                overlaps_y = left["y"] < right["y"] + right["height"] and right["y"] < left["y"] + left["height"]
                assert not (overlaps_x and overlaps_y)
    finally:
        page.close()
