"""Browser geometry checks for breadcrumbs and cinema locations."""

from base64 import b64encode
from pathlib import Path

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
            const center = element => {
                const rect = element.getBoundingClientRect();
                return rect.y + rect.height / 2;
            };
            const svg = nav.querySelector('svg');
            const box = svg.getBBox();
            const view = svg.viewBox.baseVal;
            const label = nav.querySelector('.breadcrumb-label');
            return {
                drawingOffset: box.y + box.height / 2 - (view.y + view.height / 2),
                iconOffset: center(svg) - center(nav),
                textOffset: label ? center(label) - center(nav) : null,
            };
        }""")
        assert abs(geometry["drawingOffset"]) <= 0.5
        assert abs(geometry["iconOffset"]) <= 0.5
        assert geometry["textOffset"] is not None
        assert abs(geometry["textOffset"]) <= 0.5
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
