"""Shared Playwright utilities for browser-based parsers."""

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Page, sync_playwright


@contextmanager
def page() -> Iterator[Page]:
    """Yield a headless Chromium page, closing the browser on exit."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        try:
            yield pg
        finally:
            browser.close()
