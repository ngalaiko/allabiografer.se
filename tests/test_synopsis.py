"""Synopsis expansion at desktop and mobile widths."""

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
@pytest.mark.parametrize("overflow", [0, 8, 9, 10, 40])
def test_synopsis_overflow(browser, width, overflow):
    html = (
        _make_env()
        .get_template("program.html")
        .render(
            num_days=1,
            days=[],
            blocks=[
                {
                    "film_title": "Film",
                    "film_id": "film",
                    "film_url": "/film/",
                    "full_desc": "x" * (40 + overflow),
                    "desc": "Short description",
                    "cinemas": [],
                }
            ],
        )
    )
    page = browser.new_page(viewport={"width": width, "height": 800})
    try:
        page.set_content(html)
        page.add_style_tag(content=(ROOT / "static/i/style.css").read_text())
        page.add_style_tag(
            content="""
            .synopsis { font: 16px/20px monospace; width: 20ch; overflow-wrap: anywhere; }
            .synopsis-more { font: 16px/20px monospace; }
        """
        )
        page.add_script_tag(content=(ROOT / "static/i/synopsis.js").read_text())
        paragraph = page.locator(".synopsis")
        button = page.locator(".synopsis-more")
        assert paragraph.is_visible()
        assert page.locator(".synopsis-short:visible").count() == 0
        assert button.is_visible() == (overflow > len("Visa mer…"))
        if overflow > len("Visa mer…"):
            assert paragraph.evaluate("p => p.clientHeight") == 40
            button.click()
            assert paragraph.evaluate("p => p.clientHeight == p.scrollHeight")
            button.click()
            assert paragraph.evaluate("p => p.clientHeight") == 40
            paragraph.evaluate("p => p.style.width = '80ch'")
            playwright.expect(button).to_be_hidden()
            assert paragraph.evaluate("p => p.clientHeight == p.scrollHeight")
            paragraph.evaluate("p => p.style.width = '20ch'")
            playwright.expect(button).to_be_visible()
            assert paragraph.evaluate("p => p.clientHeight") == 40
        else:
            assert paragraph.evaluate("p => p.clientHeight == p.scrollHeight")
    finally:
        page.close()
