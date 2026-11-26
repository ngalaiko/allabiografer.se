"""Capture the paginated Kraften i Finspång calendar API responses."""

from datetime import datetime

from parse.parsers.kraftenifinspang_se import _SOURCE, _URL

from .._shared import STOCKHOLM, capture_json, fetch_main


def fetch_pages(session, inputs):
    today = datetime.fromtimestamp(int(inputs.parents[1].name), STOCKHOLM).date()
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


if __name__ == "__main__":
    fetch_main(_SOURCE, fetch_pages)
