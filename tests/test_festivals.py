"""Festival imports and static pages."""

import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pytest
from bs4 import BeautifulSoup

import build
from build.festivals import build_festivals, prepare
from parse.festivals import prisma_screenings, stockholm_screenings
from store import Festival, FestivalScreening, write_festival


@pytest.fixture
def festival():
    return {
        "slug": "test-festival",
        "year": 2026,
        "name": "Testfestival",
        "city": "Stockholm",
        "start": "2026-11-11",
        "end": "2026-11-22",
        "url": "https://example.com/",
        "screenings": [
            {
                "id": "one",
                "film_id": "film",
                "title": "Film <ett>",
                "venue": "Bio",
                "start": "2026-11-11T17:30:00+01:00",
                "end": "2026-11-11T19:30:00+01:00",
                "url": "https://example.com/tickets",
            }
        ],
    }


def test_festival_build_keeps_full_programme_before_and_after_festival(tmp_path, festival):
    db = tmp_path / "db.sqlite"
    festival["screenings"][0].update(genres="Genre not shown", sections="COMPETITION, ICONS")
    screenings = [FestivalScreening(**s) for s in festival.pop("screenings")]
    write_festival(Festival(**festival, source="stockholm"), screenings, path=db)
    write_festival(
        Festival(
            **{
                **festival,
                "slug": "goteborg-film-festival-prisma",
                "name": "Göteborg Film Festival Prisma",
                "city": "Göteborg",
            },
            source="prisma",
        ),
        screenings,
        path=db,
    )
    for today in (date(2026, 1, 1), date(2027, 1, 1)):
        sd = build.SiteData(
            out_dir=tmp_path / str(today.year),
            today=today,
            cities={"Göteborg": 1},
            city_slugs={"Göteborg": "goteborg"},
        )
        env = build._make_env()
        festivals = build_festivals(env, sd, build._register, db)
        build._build_index(env, sd, festivals)
        html = (sd.out_dir / "festival/test-festival/2026/index.html").read_text()
        assert "Film &lt;ett&gt;" in html
        assert "2026-11-22" in html
        assert "https://example.com/tickets" in html
        assert "festival-data" in html
        assert '<a href="/stad/stockholm/">Stockholm</a>' in html
        assert "COMPETITION, ICONS" in html.split('id="festival-data"')[0]
        assert "Genre not shown" not in html.split('id="festival-data"')[0]
        assert "https://allabiografer.se/festival/test-festival/2026/" in sd.sitemap_urls
        for path in ("index.html", "festival/index.html"):
            soup = BeautifulSoup((sd.out_dir / path).read_text(), "html.parser")
            assert soup.select_one("a[href='/festival/test-festival/2026/']").get_text() == "Testfestival 2026"
            assert not soup.select("a[href*='goteborg-film-festival-prisma']")
        home = BeautifulSoup((sd.out_dir / "index.html").read_text(), "html.parser")
        assert home.h1 is None
        assert home.select_one("a[href='/festival/']") is None
        assert home.select_one("main h2").get_text() == "Filmfestivaler"
        assert home.select_one("a[href='/stad/goteborg/']") is not None
        assert not (sd.out_dir / "festival/goteborg-film-festival-prisma").exists()
        assert not any("goteborg-film-festival-prisma" in url for url in sd.sitemap_urls)


def test_overlapping_screenings_have_separate_lanes(festival):
    festival["screenings"].append({**festival["screenings"][0], "id": "two"})
    result = prepare(festival)
    assert [s["lane"] for s in result["screenings"]] == [0, 1]
    assert result["films"][0]["cinemas"][0]["height"] == 92


@pytest.mark.parametrize(
    "change",
    [
        {"start": "2026-11-11T17:30:00"},
        {"end": "2026-11-11T16:30:00+01:00"},
        {"start": "2026-10-11T17:30:00+01:00"},
        {"url": "javascript:alert(1)"},
    ],
)
def test_invalid_screening_rejected(festival, change):
    festival["screenings"][0].update(change)
    with pytest.raises(ValueError, match=r"Invalid|outside festival"):
        prepare(festival)


def test_unknown_duration_is_not_invented(festival):
    festival["screenings"][0]["end"] = None
    assert prepare(festival)["screenings"][0]["duration"] is None


def test_festival_film_metadata_is_shared_between_screenings(festival):
    festival["screenings"].append(
        {
            **festival["screenings"][0],
            "id": "two",
            "runtime": 120,
            "genres": "Drama",
            "sections": "ICONS",
            "description": "En berättelse.",
            "poster_url": "https://example.com/poster.jpg",
        }
    )
    film = prepare(festival)["films"][0]
    assert film["runtime"] == 120
    assert film["genres"] == "Drama"
    assert film["sections"] == "ICONS"
    assert film["description"] == "En berättelse."
    assert film["poster_url"] == "https://example.com/poster.jpg"


def test_stockholm_import_filters_events_and_uses_local_time():
    def attr(code, value):
        return {"attribute_metadata": {"code": code}, "entered_attribute_value": {"value": value}}

    def product(identifier, when, section="ICONS"):
        return {
            "uid": identifier,
            "name": "Opening",
            "parent_url_key": "film",
            "url_key": "screening",
            "url_suffix": "",
            "custom_attributes": [
                attr("event_start_iso", when),
                attr("event_location", "Skandia"),
                attr("length", "120"),
                attr("filmtitle", "The film"),
                attr("sektion", section),
            ],
        }

    products = [
        product("yes", "2026-11-11 23:30:00"),
        product("old", "2025-11-11 17:30:00"),
        product("other", "2026-11-11 17:30:00", ""),
        {
            "url_key": "film",
            "name": "The film",
            "image": {"url": "https://example.com/poster.jpg"},
            "description": {"html": "<style>.bad {}</style><p>A &amp; B</p><script>bad()</script>"},
            "short_description": {"html": "<p>Introduction</p>"},
            "custom_attributes": [attr("genre", "Drama"), attr("director", "Director")],
        },
    ]
    result = stockholm_screenings(products, date(2026, 11, 11), date(2026, 11, 22))
    assert len(result) == 1
    assert result[0].start == "2026-11-11T23:30:00+01:00"
    assert result[0].end == "2026-11-12T01:30:00+01:00"
    assert result[0].title == "The film"
    assert result[0].url == "https://www.stockholmfilmfestival.se/screening"
    assert result[0].description == "A & B"
    assert result[0].intro == "Introduction"
    assert result[0].poster_url == "https://example.com/poster.jpg"
    assert result[0].film_url == "https://www.stockholmfilmfestival.se/film"
    assert result[0].genres == "Drama"
    assert result[0].runtime == 120

    # Surprise screenings use zero when the runtime has not been announced.
    products[0]["custom_attributes"][2] = attr("length", "0")
    result = stockholm_screenings(products, date(2026, 11, 11), date(2026, 11, 22))
    assert len(result) == 1
    assert result[0].runtime is None
    assert result[0].end == ""


def test_prisma_import_keeps_films_and_packages_in_local_time():
    def document(identifier, kind, when="2026-10-24T12:00:00Z", key="film-key"):
        return {
            "id": identifier,
            "type": kind,
            "eventKey": key,
            "uniqueTitle": "the-film",
            "title": "The film",
            "location": "Göta 1",
            "length": 80,
            "timeStart": when,
            "timeEnd": "2026-10-24T13:20:00Z",
            "imageUrl": {"poster": None, "thumbnail": "https://example.com/thumb.jpg"},
        }

    documents = [
        document(1, "Movie"),
        document(2, "Happening"),
        document(3, "Movie", "2026-11-24T12:00:00Z"),
        document(4, "Package", key="package-key"),
    ]
    details = {
        "film-key": {
            "description": "**Lead *text*.**\n\nRest <i>of</i> it.<br />End.",
            "category": "Fiction",
            "originCountry": ["united states"],
            "language": '["english"]',
            "releaseYear": "2026",
            "crew": [{"crewType": "director", "firstname": "A", "surname": "B"}, {"crewType": "editor"}],
        }
    }
    result = prisma_screenings(documents, details, date(2026, 10, 23), date(2026, 10, 31))
    assert [s.id for s in result] == ["1", "4"]
    film, package = result
    assert film.start == "2026-10-24T14:00:00+02:00"
    assert film.end == "2026-10-24T15:20:00+02:00"
    assert film.url == "https://program.goteborgfilmfestival.se/program/the-film"
    assert film.intro == "Lead text."
    assert film.description == "Rest of it. End."
    assert film.genres == "Spelfilm"
    assert film.director == "A B"
    assert film.country == "United States"
    assert film.language == "English"
    assert film.poster_url == "https://example.com/thumb.jpg"
    assert package.url == "https://program.goteborgfilmfestival.se/paket/package-key"
    assert package.sections == "Kortfilmer"


def test_festival_stylesheet_braces_balance():
    depth = 0
    for char in Path("static/i/festival.css").read_text():
        depth += {"{": 1, "}": -1}.get(char, 0)
        assert depth >= 0
    assert depth == 0


@pytest.mark.parametrize("share_method", ["native", "clipboard"])
def test_festival_selection_restores_locally_but_shared_links_take_priority(festival, share_method):
    playwright = pytest.importorskip("playwright.sync_api")
    festival["screenings"].append({**festival["screenings"][0], "id": "two", "film_id": "another"})
    html = (
        build._make_env()
        .get_template("festival.html")
        .render(festival=prepare(festival), versions={"css": "test", "js": "test"}, city_url="/stad/stockholm/")
    )

    def serve(route):
        if route.request.resource_type == "document":
            route.fulfill(body=html, content_type="text/html")
        else:
            route.fulfill(path=Path("static") / urlparse(route.request.url).path.lstrip("/"))

    with playwright.sync_playwright() as runtime:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        if not executable and not Path(runtime.chromium.executable_path).exists():
            pytest.skip("Install Chromium with playwright install chromium")
        browser = runtime.chromium.launch(executable_path=executable)
        context = browser.new_context()
        context.route("https://festival.test/**", serve)
        context.add_init_script("""window.captured = [];
            window.posthog = {capture: (name, properties) => window.captured.push({name, ...properties})};
        """)
        page = context.new_page()
        url = "https://festival.test/festival/test-festival/2026/"
        page.goto(url)
        page.locator('[data-select="one"]').click()
        page.close()

        page = context.new_page()
        page.goto(url)
        assert page.locator('[data-select="one"]').get_attribute("aria-pressed") == "true"
        assert "selected=one" in page.url
        page.goto(url + "?selected=two,removed")
        assert page.locator('[data-select="one"]').get_attribute("aria-pressed") == "false"
        assert page.locator('[data-select="two"]').get_attribute("aria-pressed") == "true"
        page.goto(url)
        assert page.locator('[data-select="two"]').get_attribute("aria-pressed") == "true"
        page.locator('[data-select="two"]').click()
        page.goto(url)
        assert page.locator("#festival-count").inner_text() == "0"
        assert page.evaluate("window.captured") == []  # Restoring a schedule is not a user selection.

        page.locator('[data-select="two"]').click()
        page.locator('[data-select="one"]').click()
        page.locator("#festival-selected").click()
        page.locator("#festival-selected").click()  # Re-clicking the active tab is not a view change.
        page.evaluate(
            """method => {
            const share = async () => { if (window.failShare) throw new Error('Cancelled or denied'); };
            Object.defineProperty(navigator, 'share', {configurable: true,
                value: method === 'native' ? share : undefined});
            Object.defineProperty(navigator, 'clipboard', {value: {writeText: share}});
        }""",
            share_method,
        )
        page.locator("#festival-share").click()
        page.wait_for_function("window.captured.some(event => event.name === 'festival_schedule_shared')")
        page.evaluate("window.failShare = true")
        page.locator("#festival-share").click()
        with page.expect_download() as download:
            page.locator("#festival-export").click()
        assert download.value.suggested_filename == "test-festival-2026.ics"
        # Prevent navigation without suppressing the ticket event or its propagation behavior.
        page.locator(".festival-calendar-event a").first.evaluate(
            "link => link.addEventListener('click', event => event.preventDefault())"
        )
        page.locator(".festival-calendar-event a").first.click()
        assert page.locator("#festival-count").inner_text() == "2"
        page.get_by_role("button", name="Ta bort Film <ett>, 2026-11-11 17:30", exact=True).first.press("Enter")
        page.locator("#festival-all").click()

        common = {"festival_slug": "test-festival", "festival_year": 2026, "city": "Stockholm"}
        assert page.evaluate("window.captured") == [
            {
                **common,
                "name": "festival_screening_selected",
                "view": "program",
                "selected_count": 1,
                "screening_id": "two",
                "film_id": "another",
            },
            {
                **common,
                "name": "festival_screening_selected",
                "view": "program",
                "selected_count": 2,
                "screening_id": "one",
                "film_id": "film",
            },
            {**common, "name": "festival_view_changed", "view": "selected", "selected_count": 2},
            {
                **common,
                "name": "festival_schedule_shared",
                "view": "selected",
                "selected_count": 2,
                "method": share_method,
            },
            {**common, "name": "festival_schedule_exported", "view": "selected", "selected_count": 2, "format": "ics"},
            {
                **common,
                "name": "festival_ticket_clicked",
                "view": "selected",
                "selected_count": 2,
                "screening_id": "one",
                "film_id": "film",
            },
            {
                **common,
                "name": "festival_screening_deselected",
                "view": "selected",
                "selected_count": 1,
                "screening_id": "one",
                "film_id": "film",
            },
            {**common, "name": "festival_view_changed", "view": "program", "selected_count": 1},
        ]
        page.evaluate("delete window.posthog")
        page.locator('[data-select="two"]').click()
        assert page.locator("#festival-count").inner_text() == "0"
        browser.close()
