"""Markdown is built from stored programme data, alongside every HTML page."""

import sys
from datetime import datetime, time, timedelta

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
