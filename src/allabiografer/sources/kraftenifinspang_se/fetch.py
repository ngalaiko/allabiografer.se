"""Capture the paginated Kraften i Finspång calendar API responses."""

from allabiografer.sources.kraftenifinspang_se.site import _URL

from .._shared import capture_json


def fetch_pages(session, inputs, today, *, selectors=None):
    page = 1
    while True:
        data = capture_json(
            session,
            _URL,
            inputs / f"events-{page:03d}.json",
            params={"start_date": today.isoformat(), "per_page": 50, "page": page},
        )
        if page >= data["total_pages"]:
            return
        page += 1
