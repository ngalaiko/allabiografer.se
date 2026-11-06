"""Markdown is built from stored programme data, alongside every HTML page."""

import re
import sys
from datetime import datetime, time, timedelta
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

import build
from store import Movie, Screening, write_movie, write_screenings


def test_build_writes_markdown_from_database(tmp_path, monkeypatch):
    db = tmp_path / "site.db"
    out = tmp_path / "www"
    monkeypatch.setattr(build, "DB_FILE", db)
    monkeypatch.setattr(sys, "argv", ["build", str(out)])
    tomorrow = datetime.now(tz=build.SWEDEN_TZ).date() + timedelta(days=1)
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 42,
                "title_sv": "Filmen [ett]",
                "overview_sv": "Kärlek & hopp",
                "genres": ["Drama"],
                "directors": ["A & B"],
                "release_date_se": tomorrow.isoformat(),
            }
        ),
        path=db,
    )
    write_screenings(
        [
            Screening(
                tmdb_id=42,
                date=tomorrow + timedelta(days=offset),
                time=time(hour, 30),
                ticket_url=f"https://tickets.example/{offset}",
                cinema_name="Bio Roy",
                city="Göteborg",
            )
            for offset, hour in [(0, 17), (1, 20)]
        ],
        path=db,
    )

    build.main()

    pages = list(out.rglob("*.html"))
    assert pages
    assert all(page.with_suffix(".md").exists() for page in pages)
    guide = (out / "llms.txt").read_text()
    assert guide.startswith("# allabiografer.se\n\n> ")
    assert "Accept: text/markdown" in guide
    assert "generated_at is the build time, not a source fetch time" in guide
    assert "coverage.completeness is unknown" in guide
    assert "no_listings_found does not prove that nothing is showing" in guide
    assert "Subtitle languages are null when unknown, [] when explicitly absent" in guide
    links = re.findall(r"\]\((https://allabiografer\.se/[^)]+)\)", guide)
    assert links
    for url in links:
        assert (out / unquote(urlsplit(url).path).lstrip("/")).is_file()
    feed_links = [url for url in links if url.endswith(".json")]
    assert feed_links == ["https://allabiografer.se/stad/göteborg/index.json"]
    for page in pages:
        soup = BeautifulSoup(page.read_text(), "html.parser")
        if soup.select_one('link[rel="canonical"]'):
            assert soup.select_one('link[rel="help"][href="/llms.txt"]') is not None
            alternate = soup.select_one('link[rel="alternate"][type="text/markdown"]')
            assert alternate is not None
            target = out / unquote(urlsplit(alternate["href"]).path).lstrip("/")
            assert target == page.with_suffix(".md")
            assert target.exists()
    city = (out / "stad/göteborg/index.md").read_text()
    assert city.startswith("# Bio i Göteborg")
    assert "Filmen \\[ett\\]" in city
    assert "Kärlek & hopp" in city
    assert "Drama • A & B" in city
    assert "href=" not in city
    assert "Bio Roy" in city
    assert f"{tomorrow}: [17:30](https://tickets.example/0)" in city
    assert f"{tomorrow + timedelta(days=1)}: [20:30](https://tickets.example/1)" in city
    assert "<script" not in city
    assert "<style" not in city
    assert "Prenumerera" not in city
    assert "[Göteborg](/stad/göteborg/)" in (out / "index.md").read_text()
    for path in ("filmer/index.md", "premiarer/index.md"):
        assert "[Filmen \\[ett\\]](/film/filmen-ett/)" in (out / path).read_text()
