"""Browser geometry checks for shared breadcrumbs."""

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
