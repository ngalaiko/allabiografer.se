"""Build data loading."""

import json
from datetime import date, datetime, time, timedelta

import pytest
from bs4 import BeautifulSoup
from PIL import Image

import build
from build import SWEDEN_TZ
from build.og import write_card
from store import (
    Film,
    Movie,
    Screening,
    Venue,
    film_key,
    poster_key_for_film,
    read_screenings,
    write_films,
    write_movie,
    write_poster,
    write_screenings,
    write_venue,
)
from store.version import (
    Accessibility,
    AccessibilityFeature,
    AudioKind,
    AudioVersion,
    ContentVersion,
    Dimension,
    Language,
    Presentation,
    PresentationSystem,
    SoundAttribute,
    SubtitleVersion,
)

# sha256("okänd film 4")[:8] exceeds 2**63, so its negated synthetic id
# falls outside SQLite's signed 64-bit INTEGER range.
UNTITLED = "Okänd film 4"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(build, "DB_FILE", path)
    return path


def screening(**kwargs) -> Screening:
    defaults = {
        "tmdb_id": None,
        "date": datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=30),
        "time": time(18, 30),
        "ticket_url": "https://example.com/1",
        "cinema_name": "Bio",
        "city": "Stockholm",
    }
    return Screening(**{**defaults, **kwargs})


def movie(tmdb_id: int) -> Movie:
    return Movie.from_dict({"tmdb_id": tmdb_id, "title_sv": "Filmen"})


@pytest.mark.parametrize(
    ("original", "spoken", "expected"),
    [
        ("en", ["en"], ["en"]),
        ("fr", ["fr", "en"], ["fr", "en"]),
        ("en", None, ["en"]),
        ("en", [], None),
        ("xx", ["xx", ""], None),
        ("", None, None),
    ],
)
def test_film_page_uses_movie_languages_not_page_language(db, tmp_path, original, spoken, expected):
    write_movie(
        Movie.from_dict(
            {"tmdb_id": 42, "title_sv": "Filmen", "original_language": original, "spoken_languages": spoken}
        ),
        path=db,
    )
    write_screenings([screening(tmdb_id=42)], path=db)
    out = tmp_path / "out"
    build._build_programme_pages(build._make_env(), build._load_data(out))
    page = BeautifulSoup((out / "film/filmen/index.html").read_text(), "html.parser")
    nodes = [json.loads(script.string) for script in page.select('script[type="application/ld+json"]')]
    movie_node = next(node for data in nodes for node in data.get("@graph", []) if node["@type"] == "Movie")
    if expected is None:
        assert "inLanguage" not in movie_node
    else:
        assert movie_node["inLanguage"] == expected


def test_robots_declares_content_signals_for_every_crawler(tmp_path):
    build._write_robots(tmp_path)

    robots = (tmp_path / "robots.txt").read_text()
    groups = robots.split("\n\n")
    crawler_groups = [group for group in groups if group.startswith("User-agent:")]
    assert "User-agent: *" in crawler_groups[0]
    for group in crawler_groups:
        assert "Content-Signal: ai-train=no, search=yes, ai-input=yes" in group.splitlines()
        assert "Allow: /" in group.splitlines()
    assert "Sitemap: https://allabiografer.se/sitemap.xml" in robots.splitlines()


def test_schedule_pages_describe_their_screenings_and_formats(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "genres": ["Drama"]}), path=db)
    write_movie(Movie.from_dict({"tmdb_id": 43, "title_sv": "En annan film"}), path=db)
    write_screenings(
        [
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/imax",
                screen="Salong 2",
                version=ContentVersion(
                    audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH})),
                    subtitles=SubtitleVersion(frozenset({Language.FINNISH, Language.ENGLISH})),
                ),
                presentation=Presentation(
                    experiences=frozenset({PresentationSystem.IMAX, PresentationSystem.PREMIERE}),
                    dimension=Dimension.THREE_D,
                    sound=frozenset({SoundAttribute.DOLBY_ATMOS}),
                ),
            ),
            screening(tmdb_id=42, date=day, ticket_url="https://example.com/unknown"),
            screening(tmdb_id=43, date=day, cinema_name="Annan Bio", ticket_url="https://example.com/other"),
            screening(tmdb_id=42, date=day, city="Göteborg", ticket_url="https://example.com/goteborg"),
        ],
        path=db,
    )
    out = tmp_path / "out"
    build._build_programme_pages(build._make_env(), build._load_data(out))

    for path, additional in {
        "stad/stockholm": {"other"},
        "stad/stockholm/bio": set(),
        "stad/stockholm/genre/drama": set(),
        "stad/stockholm/film/filmen": set(),
        "film/filmen": {"goteborg"},
    }.items():
        page = BeautifulSoup((out / path / "index.html").read_text(), "html.parser")
        show_link = page.select_one('a[href="https://example.com/imax"]')
        assert show_link["title"] == "Salong 2"
        assert "Salong 2" in show_link["aria-label"]
        inline = json.loads(page.select_one('head script[type="application/ld+json"]').string)
        assert not any(node["@type"] == "ScreeningEvent" for node in inline["@graph"])
        alternate = page.select_one('head link[rel="alternate"][type="application/ld+json"]')
        assert alternate["href"] == f"https://allabiografer.se/{path}/index.jsonld"
        calendar = page.select_one('head link[rel="alternate"][type="text/calendar"]')
        assert calendar["href"] == f"https://allabiografer.se/{path}/index.ics"
        payload = json.loads((out / path / "index.jsonld").read_text())
        assert payload["@context"] == "https://schema.org"
        graph = payload["@graph"]
        events = {node["offers"]["url"]: node for node in graph if node["@type"] == "ScreeningEvent"}
        assert set(events) == {f"https://example.com/{name}" for name in {"imax", "unknown"} | additional}
        movies = [node["@id"] for node in graph if node["@type"] == "Movie"]
        assert len(movies) == len(set(movies)) == (2 if "other" in additional else 1)
        assert all(event["workPresented"]["@id"] in movies for event in events.values())
        imax = events["https://example.com/imax"]
        assert imax["workPresented"] == {"@id": "https://allabiografer.se/film/filmen/#movie"}
        assert imax["videoFormat"] == "IMAX 3D"
        assert imax["description"] == "Salong 2, Dolby Atmos, Premiär"
        assert imax["inLanguage"] == ["sv"]
        assert imax["subtitleLanguage"] == ["en", "fi"]
        assert not {"videoFormat", "inLanguage", "subtitleLanguage"} & events["https://example.com/unknown"].keys()


def test_schedule_feeds_include_showtimes_beyond_display_window(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    write_movie(movie(42), path=db)
    write_screenings(
        [
            screening(
                tmdb_id=42,
                date=day + timedelta(days=30 if i == 100 else 0),
                time=time(12 + i // 60, i % 60),
                ticket_url=f"https://example.com/{i}",
            )
            for i in range(101)
        ],
        path=db,
    )
    out = tmp_path / "out"
    build._build_programme_pages(build._make_env(), build._load_data(out))
    city = out / "stad/stockholm"
    page = BeautifulSoup((city / "index.html").read_text(), "html.parser")
    inline = json.loads(page.select_one('script[type="application/ld+json"]').string)["@graph"]
    full = json.loads((city / "index.jsonld").read_text())["@graph"]
    assert not any(node["@type"] == "ScreeningEvent" for node in inline)
    urls = [f"https://example.com/{i}" for i in range(101)]
    assert [node["offers"]["url"] for node in full if node["@type"] == "ScreeningEvent"] == urls
    ics = (city / "index.ics").read_bytes()
    assert ics.startswith(b"BEGIN:VCALENDAR\r\n")
    assert ics.endswith(b"END:VCALENDAR\r\n")
    assert all(len(line) <= 75 for line in ics.split(b"\r\n"))
    lines = ics.decode().replace("\r\n ", "").splitlines()
    assert [line.removeprefix("URL:") for line in lines if line.startswith("URL:")] == urls
    assert len({line for line in lines if line.startswith("UID:")}) == 101
    assert not any(line.startswith("DTEND:") for line in lines)
    assert urls[-1] not in {a["href"] for a in page.select("a[data-start]")}
    assert f"({urls[-1]})" not in (city / "index.md").read_text()


def test_load_data_ignores_synthetic_ids(db, tmp_path):
    write_screenings(
        [
            screening(title=UNTITLED, ticket_url="https://example.com/a"),
            screening(tmdb_id=42, ticket_url="https://example.com/b"),
        ],
        path=db,
    )
    write_movie(movie(42), path=db)

    sd = build._load_data(tmp_path / "out")

    assert len(sd.screenings) == 2
    assert sd.movies[42].title_sv == "Filmen"
    synthetic = [m for tmdb_id, m in sd.movies.items() if tmdb_id < 0]
    assert len(synthetic) == 1
    assert synthetic[0].title_sv == UNTITLED


def film(title: str, **kwargs) -> Film:
    defaults = {
        "key": film_key("bio_se", title),
        "source": "bio_se",
        "title": title,
        "overview": "Handling från biografen.",
        "runtime": 95,
        "poster_url": "https://bio.se/p.jpg",
    }
    return Film(**{**defaults, **kwargs})


def test_site_film_fills_title_only_screening(db, tmp_path):
    f = film(UNTITLED)
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"img", "image/jpeg", path=db)
    write_screenings([screening(title=UNTITLED, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert neg_id < 0
    assert sd.movies[neg_id].overview_sv == "Handling från biografen."
    assert sd.movies[neg_id].runtime == 95
    assert sd.poster_keys[neg_id] == poster_key_for_film(f.key)


def test_site_film_fills_gaps_in_tmdb_movie(db, tmp_path):
    f = film("Filmen")
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"img", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert sd.movies[42].overview_sv == "Handling från biografen."
    assert sd.movies[42].runtime == 95
    assert sd.poster_keys[42] == poster_key_for_film(f.key)


def test_tmdb_poster_wins_over_site_poster(db, tmp_path):
    f = film("Filmen")
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"site", "image/jpeg", path=db)
    write_poster(42, b"tmdb", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert sd.poster_keys[42] == "42"


def test_poster_url_skips_undecodable_image(db, tmp_path):
    f = film("Filmen")
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"not an image", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, film_key=f.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert build._poster_url(sd, 42) is None


def other_film(title: str, **kwargs) -> Film:
    return film(title, key=film_key("filmstaden_se", title), source="filmstaden_se", **kwargs)


def test_unmatched_film_does_not_borrow_metadata_from_an_unrelated_source(db, tmp_path):
    a = film(UNTITLED, overview="", runtime=None)
    b = other_film(UNTITLED, overview="Handling från annan kedja.")
    write_films([a, b], path=db)
    write_poster(poster_key_for_film(b.key), b"img", "image/jpeg", path=db)
    write_screenings([screening(title=UNTITLED, film_key=a.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].overview_sv == ""
    assert sd.movies[neg_id].runtime is None
    assert neg_id not in sd.poster_keys


def test_other_source_film_supplies_poster_for_tmdb_movie(db, tmp_path):
    a = film("Filmen")
    b = other_film("Filmen")
    write_films([a, b], path=db)
    write_poster(poster_key_for_film(b.key), b"img", "image/jpeg", path=db)
    write_movie(movie(42), path=db)
    write_screenings(
        [
            screening(tmdb_id=42, film_key=a.key),
            screening(tmdb_id=42, film_key=b.key, ticket_url="https://example.com/b"),
        ],
        path=db,
    )

    sd = build._load_data(tmp_path / "out")

    assert sd.poster_keys[42] == poster_key_for_film(b.key)


def test_tmdb_metadata_wins_over_pooled_films(db, tmp_path):
    a = film("Filmen", overview="Handling från biografen.")
    write_films([a], path=db)
    write_poster(poster_key_for_film(a.key), b"site", "image/jpeg", path=db)
    write_poster(42, b"tmdb", "image/jpeg", path=db)
    write_movie(
        Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "overview_sv": "Handling från TMDB."}),
        path=db,
    )
    write_screenings([screening(tmdb_id=42, film_key=a.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    assert sd.movies[42].overview_sv == "Handling från TMDB."
    assert sd.poster_keys[42] == "42"


@pytest.mark.parametrize(
    ("source_runtime", "expected_runtime"),
    [(None, None), (0, None), (174, 174), (175, 175), (179, 179), (185, 185), (186, 186), (326, 326)],
)
def test_programme_preserves_source_runtimes_without_changing_film_identity(
    db, tmp_path, source_runtime, expected_runtime
):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    extended = film("Fanny och Alexander", runtime=source_runtime)
    theatrical = other_film("Fanny och Alexander", runtime=180)
    write_films([extended, theatrical], path=db)
    write_movie(Movie.from_dict({"tmdb_id": 5961, "title_sv": extended.title, "runtime": 180}), path=db)
    write_screenings(
        [
            screening(tmdb_id=5961, title=f.title, film_key=f.key, date=day, ticket_url=f"https://example.com/{i}")
            for i, f in enumerate([extended, theatrical])
        ],
        path=db,
    )
    out = tmp_path / "out"
    build._build_programme_pages(build._make_env(), build._load_data(out))
    page = out / "stad/stockholm/film/fanny-och-alexander"
    html = BeautifulSoup((page / "index.html").read_text(), "html.parser")
    assert len(html.select(".schedule-cell time")) == 2
    expected_blocks = 1 if expected_runtime is None or abs(expected_runtime - 180) <= 5 else 2
    assert len(html.select("article.schedule-film")) == expected_blocks
    city_html = BeautifulSoup((out / "stad/stockholm/index.html").read_text(), "html.parser")
    assert len(city_html.select("article.schedule-film")) == expected_blocks
    ids = [element["id"] for element in html.select("[id]")]
    assert len(ids) == len(set(ids))
    graph = json.loads((page / "index.jsonld").read_text())["@graph"]
    events = {node["offers"]["url"]: node for node in graph if node["@type"] == "ScreeningEvent"}
    assert len({event["workPresented"]["@id"] for event in events.values()}) == 1
    if expected_runtime is None:
        assert "endDate" not in events["https://example.com/0"]
        assert "duration" not in graph[0]
    else:
        assert (
            events["https://example.com/0"]["endDate"][11:16]
            == {174: "21:24", 175: "21:25", 179: "21:29", 185: "21:35", 186: "21:36", 326: "23:56"}[source_runtime]
        )
    assert events["https://example.com/1"]["endDate"][11:16] == "21:30"
    if source_runtime == 326:
        assert "5 tim. 26 min." in (page / "index.md").read_text()
        assert "5 tim. 26 min." in html.get_text()
        assert "3 tim." in html.get_text()
        assert "0 min." not in html.get_text()
        assert "duration" not in graph[0]
    assert all(s.tmdb_id == 5961 for s in read_screenings(path=db))


@pytest.mark.parametrize("runtimes", [(None, 108, 113, 118), (118, 113, 108, None)])
def test_programme_runtime_tolerance_does_not_chain(db, tmp_path, runtimes):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    films = [
        Film(key=f"source{i}:filmen", source=f"source{i}", title="Filmen", runtime=r) for i, r in enumerate(runtimes)
    ]
    write_films(films, path=db)
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "runtime": 113}), path=db)
    write_screenings(
        [
            screening(
                tmdb_id=42,
                title=f.title,
                film_key=f.key,
                date=day,
                cinema_name=f"Bio {f.runtime}",
                ticket_url=f"https://example.com/{f.runtime}",
            )
            for f in films
        ],
        path=db,
    )
    out = tmp_path / "out"
    build._build_programme_pages(build._make_env(), build._load_data(out))
    html = BeautifulSoup((out / "stad/stockholm/index.html").read_text(), "html.parser")
    blocks = html.select("article.schedule-film")
    assert len(blocks) == 2
    assert [a.get_text() for a in blocks[0].select(".cinema-name > a")] == ["Bio 108", "Bio 113", "Bio None"]
    assert [a.get_text() for a in blocks[1].select(".cinema-name > a")] == ["Bio 118"]


def test_title_only_screening_without_film_key_does_not_guess_metadata(db, tmp_path):
    f = film(UNTITLED)
    write_films([f], path=db)
    write_poster(poster_key_for_film(f.key), b"img", "image/jpeg", path=db)
    write_screenings([screening(title=UNTITLED)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].title_sv == UNTITLED
    assert sd.movies[neg_id].overview_sv == ""
    assert neg_id not in sd.poster_keys


def test_same_title_works_keep_their_metadata_screenings_and_page_links(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    musical = film("Kinky Boots", runtime=135, overview="West End recording.", age_rating="Barntillåten")
    short = other_film("Kinky Boots", runtime=10, overview="An unrelated short.")
    write_films([musical, short], path=db)
    for identifier, runtime, overview in [(16367, 107, "2005 feature."), (42, 121, "Different adaptation.")]:
        write_movie(
            Movie.from_dict(
                {"tmdb_id": identifier, "title_sv": "Kinky Boots", "runtime": runtime, "overview_sv": overview}
            ),
            path=db,
        )
    write_screenings(
        [
            screening(title="Kinky Boots", film_key=musical.key, date=day, ticket_url="https://example.com/musical"),
            screening(title="Kinky Boots", film_key=short.key, date=day, ticket_url="https://example.com/short"),
            screening(tmdb_id=16367, date=day, ticket_url="https://example.com/feature"),
            screening(tmdb_id=42, date=day, ticket_url="https://example.com/adaptation"),
        ],
        path=db,
    )
    out = tmp_path / "out"
    sd = build._load_data(out)
    env = build._make_env()
    build._build_programme_pages(env, sd)
    graph = json.loads((out / "stad/stockholm/index.jsonld").read_text())["@graph"]
    movies = {node["@id"]: node for node in graph if node["@type"] == "Movie"}
    rows = {node["offers"]["url"].rsplit("/", 1)[-1]: node for node in graph if node["@type"] == "ScreeningEvent"}
    expected = {
        "musical": (135, "West End recording."),
        "short": (10, "An unrelated short."),
        "feature": (107, "2005 feature."),
        "adaptation": (121, "Different adaptation."),
    }
    assert set(rows) == set(expected)
    assert len({row["workPresented"]["@id"] for row in rows.values()}) == 4
    for name, (runtime, synopsis) in expected.items():
        row = rows[name]
        assert (datetime.fromisoformat(row["endDate"]) - datetime.fromisoformat(row["startDate"])) == timedelta(
            minutes=runtime
        )
        path = movies[row["workPresented"]["@id"]]["url"].removeprefix(build.BASE_URL).strip("/")
        for page_path in (path, f"stad/stockholm/{path}"):
            page = BeautifulSoup((out / page_path / "index.html").read_text(), "html.parser")
            assert [p.get_text() for p in page.select(".synopsis")] == [synopsis]
            assert {a["href"] for a in page.select("a[data-start]")} == {row["offers"]["url"]}


def test_source_with_more_showings_supplies_metadata(db, tmp_path):
    own = film(
        "Heart of the beast",
        key=film_key("nortic_se", "Heart of the beast"),
        source="nortic_se",
        overview="Eventuellt kvarvarande biljetter säljs vid entrén. Serviceavgift 15kr.",
    )
    other = other_film("Heart of the Beast", overview="Handling från distributören.")
    write_films([own, other], path=db)
    write_screenings([screening(title="Heart of the beast", film_key=own.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].title_sv == own.title
    assert sd.movies[neg_id].overview_sv == own.overview


def test_source_with_showings_outranks_unused_source(db, tmp_path):
    own = film(
        UNTITLED,
        key=film_key("zzz_se", UNTITLED),
        source="zzz_se",
        overview="Handling från egen källa.",
    )
    other = film(
        UNTITLED,
        key=film_key("aaa_se", UNTITLED),
        source="aaa_se",
        overview="Handling från annan källa.",
    )
    write_films([own, other], path=db)
    write_screenings([screening(title=UNTITLED, film_key=own.key)], path=db)

    sd = build._load_data(tmp_path / "out")

    neg_id = sd.screenings[0].tmdb_id
    assert sd.movies[neg_id].overview_sv == "Handling från egen källa."


@pytest.mark.parametrize("directors", [None, [], ["A & B", "<Co-director>"]])
def test_programme_directors_go_in_the_details_line(db, tmp_path, directors):
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 42,
                "title_sv": "Filmen",
                "genres": ["Drama"],
                "directors": directors,
                "release_date": "2026-01-01",
            }
        ),
        path=db,
    )
    write_screenings(
        [
            screening(
                tmdb_id=42,
                date=datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1),
                version=ContentVersion(audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH}))),
            )
        ],
        path=db,
    )
    sd = build._load_data(tmp_path / "out")
    out = tmp_path / "out" / "index.html"
    build._write_programme(build._make_env(), sd, sd.screenings, title="T", breadcrumbs="", out_path=out, canonical="/")
    meta = BeautifulSoup(out.read_text(), "html.parser").select_one(".film-meta")
    assert meta.get_text() == (
        "Drama • A & B, <Co-director> • 2026 • Engelskt tal" if directors else "Drama • 2026 • Engelskt tal"
    )
    assert meta.find() is None


def test_programme_synopsis_has_expand_toggle(db, tmp_path):
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "overview_sv": "Handling."}), path=db)
    write_screenings(
        [
            screening(tmdb_id=42, title="Cinema's title", date=datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)),
            screening(
                tmdb_id=42,
                title="Cinema's title",
                date=datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1),
                ticket_url="https://example.com/imax",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
        ],
        path=db,
    )
    sd = build._load_data(tmp_path / "out")
    out = tmp_path / "out" / "index.html"
    build._write_programme(build._make_env(), sd, sd.screenings, title="T", breadcrumbs="", out_path=out, canonical="/")
    html = out.read_text()
    assert 'class="synopsis" id="synopsis-filmen"' in html
    assert 'data-more="filmen" aria-controls="synopsis-filmen"' in html
    assert "/i/synopsis.js?v=" in html
    soup = BeautifulSoup(html, "html.parser")
    for anchor in ("film-filmen", "film-cinema-s-title"):
        matches = soup.select(f"#{anchor}")
        assert len(matches) == 1
        assert matches[0].find_parent("article").select_one("h2").get_text() == "Filmen"


@pytest.mark.parametrize(
    ("city", "cinema", "expected_cinema_title"),
    [
        ("Örebro", "Filmstaden Örebro", "Filmstaden Örebro – program och speltider"),
        ("Stockholm", "Grand", "Grand i Stockholm – program och speltider"),
        ("Göteborg", "Göteborg Bio", "Göteborg Bio – program och speltider"),
        ("Örebro", "BIO ÖREBRO", "BIO ÖREBRO – program och speltider"),
        ("Lund", "Lundsbrunn Bio", "Lundsbrunn Bio i Lund – program och speltider"),
    ],
)
def test_city_and_cinema_page_titles(db, tmp_path, city, cinema, expected_cinema_title):
    write_movie(movie(42), path=db)
    write_screenings([screening(tmdb_id=42, city=city, cinema_name=cinema)], path=db)
    out = tmp_path / "out"
    sd = build._load_data(out)
    build._build_programme_pages(build._make_env(), sd)

    city_dir = out / "stad" / sd.city_slugs[city]
    cinema_dir = city_dir / sd.cinema_slugs[(city, cinema)]
    for directory, expected in [
        (city_dir, f"Bio i {city} – program för alla biografer"),
        (cinema_dir, expected_cinema_title),
    ]:
        page = BeautifulSoup((directory / "index.html").read_text(), "html.parser")
        assert page.title.string == expected
        assert page.find("meta", property="og:title")["content"] == expected
        assert page.find("meta", attrs={"name": "twitter:title"})["content"] == expected
        image_url = page.find("meta", property="og:image")["content"]
        assert image_url.startswith(f"{build.BASE_URL}/og/")
        assert page.find("meta", attrs={"name": "twitter:image"})["content"] == image_url
        assert page.find("meta", property="og:image:alt")["content"] == expected
        assert page.find("meta", property="og:image:width")["content"] == "1200"
        assert page.find("meta", property="og:image:height")["content"] == "630"
        with Image.open(out / image_url.removeprefix(build.BASE_URL).lstrip("/")) as image:
            assert image.format == "JPEG"
            assert image.size == (1200, 630)


@pytest.mark.parametrize("size", [(40, 160), (160, 40)])
def test_sharing_card_preserves_entire_poster_and_versions_content(tmp_path, size):
    poster = tmp_path / "poster.png"
    art = Image.new("RGB", size, "#00FF00")
    art.paste("#FF0000", (0, 0, size[0], size[1] // 4))
    art.paste("#0000FF", (0, size[1] * 3 // 4, size[0], size[1]))
    art.save(poster)
    options = {
        "title": "Mordet på Jesse James av ynkryggen Robert Ford",
        "subtitle": "Speltider i Örnsköldsvik",
        "poster": poster,
    }
    url = write_card(tmp_path, **options)
    assert write_card(tmp_path, **options) == url
    assert write_card(tmp_path, **{**options, "subtitle": "Speltider i Göteborg"}) != url
    with Image.open(tmp_path / url.lstrip("/")) as image:
        # Both end bands survive even for very tall/wide posters. A centre crop
        # would remove them. Allow JPEG variation without assuming a position.
        colors = image.getcolors(image.width * image.height)
        assert sum(count for count, (r, g, b) in colors if r > 240 and g < 15 and b < 15) > 100
        assert sum(count for count, (r, g, b) in colors if b > 240 and r < 15 and g < 15) > 100
    art.paste("#FFFF00", (0, 0, *size))
    art.save(poster)
    assert write_card(tmp_path, **options) != url


def test_sharing_card_falls_back_without_artwork_and_versions_festival_year(tmp_path):
    options = {"title": "Göteborg Film Festival Prisma", "subtitle": "Program och eget schema"}
    url = write_card(tmp_path, **options, year=2026)
    assert write_card(tmp_path, **options, year=2027) != url
    assert write_card(tmp_path, **options, year=2026, poster=tmp_path / "missing.jpg") == url
    broken = tmp_path / "broken.jpg"
    broken.write_text("unreadable artwork")
    assert write_card(tmp_path, **options, year=2026, poster=broken) == url


@pytest.mark.parametrize("cinema_count", [0, 1, 2])
def test_city_film_description_uses_local_schedule(db, tmp_path, cinema_count):
    synopsis = "En berättelse om en familj."
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "overview_sv": synopsis}), path=db)
    today = datetime.now(tz=SWEDEN_TZ).date()
    write_screenings(
        [
            screening(
                tmdb_id=42,
                cinema_name=f"Bio {i}",
                date=today + timedelta(days=1),
                ticket_url=f"https://example.com/{i}/{j}",
                time=time(18 + j),
            )
            for i in range(cinema_count)
            for j in range(2)
        ]
        + [screening(tmdb_id=42, cinema_name="Senare bio", date=today + timedelta(days=14))],
        path=db,
    )
    out = tmp_path / "out"
    sd = build._load_data(out)
    build._build_programme_pages(build._make_env(), sd)

    city_page = BeautifulSoup((out / "stad/stockholm/film/filmen/index.html").read_text(), "html.parser")
    description = city_page.find("meta", attrs={"name": "description"})["content"]
    assert "Filmen" in description
    assert "Stockholm" in description
    assert synopsis not in description
    if cinema_count:
        assert (
            f"Visas på {cinema_count} {'biograf' if cinema_count == 1 else 'biografer'} de närmaste två veckorna"
            in description
        )
        assert synopsis in city_page.get_text()
    else:
        assert "Inga visningar de närmaste två veckorna" in description
    assert city_page.find("meta", property="og:description")["content"] == description

    nationwide_page = BeautifulSoup((out / "film/filmen/index.html").read_text(), "html.parser")
    assert nationwide_page.find("meta", attrs={"name": "description"})["content"] == synopsis

    programme = BeautifulSoup((out / "stad/stockholm/index.html").read_text(), "html.parser")
    city_description = programme.find("meta", attrs={"name": "description"})["content"]
    if cinema_count:
        assert (
            f"1 film på {cinema_count} {'biograf' if cinema_count == 1 else 'biografer'} de närmaste två veckorna"
            in city_description
        )
        cinema_page = BeautifulSoup((out / "stad/stockholm/bio-0/index.html").read_text(), "html.parser")
        assert (
            cinema_page.find("meta", attrs={"name": "description"})["content"]
            == "Bio 0 i Stockholm: program och speltider för 1 film de närmaste två veckorna. "
            "Se visningar och hitta biljetter."
        )
    else:
        assert city_description == "Bio i Stockholm. Inga publicerade visningar de närmaste två veckorna."
    assert programme.find("meta", property="og:description")["content"] == city_description
    later_cinema = BeautifulSoup((out / "stad/stockholm/senare-bio/index.html").read_text(), "html.parser")
    assert (
        later_cinema.find("meta", attrs={"name": "description"})["content"]
        == "Senare bio i Stockholm. Inga publicerade visningar de närmaste två veckorna."
    )

    graph = json.loads((out / "film/filmen/index.jsonld").read_text())["@graph"]
    events = [node for node in graph if node["@type"] == "ScreeningEvent"]
    assert {node["offers"]["url"] for node in events} == {"https://example.com/1"} | {
        link["href"] for link in nationwide_page.select("a[data-start]")
    }
    assert all("availability" not in node["offers"] for node in events)


@pytest.mark.parametrize("first_offset", [13, 14, 30])
def test_film_pages_show_the_next_booked_day_when_outside_the_programme(db, tmp_path, first_offset):
    today = datetime.now(tz=SWEDEN_TZ).date()
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 42,
                "title_sv": "Filmen",
                "overview_sv": "En framtida resa.",
                "runtime": 97,
                "genres": ["Drama"],
            }
        ),
        path=db,
    )
    write_screenings(
        [
            screening(tmdb_id=42, city="Göteborg", date=today + timedelta(days=first_offset), time=time(13, 15)),
            screening(
                tmdb_id=42,
                date=today + timedelta(days=first_offset + 3),
                time=time(21, 45),
                ticket_url="https://example.com/stockholm",
            ),
            screening(
                tmdb_id=42,
                date=today + timedelta(days=first_offset + 8),
                ticket_url="https://example.com/later",
            ),
        ],
        path=db,
    )
    out = tmp_path / "out"
    sd = build._load_data(out)
    build._build_programme_pages(build._make_env(), sd)

    for path, offset, label, ticket in [
        ("film/filmen", first_offset, "13:15", "https://example.com/1"),
        ("stad/stockholm/film/filmen", first_offset + 3, "21:45", "https://example.com/stockholm"),
    ]:
        day = today + timedelta(days=offset)
        page = BeautifulSoup((out / path / "index.html").read_text(), "html.parser")
        assert page.select_one(".synopsis").get_text() == "En framtida resa."
        assert "1 tim. 37 min." in page.select_one(".film-meta").get_text()
        assert {a["href"] for a in page.select("a[data-start]")} == {ticket}
        graph = json.loads((out / path / "index.jsonld").read_text())["@graph"]
        events = [node for node in graph if node["@type"] == "ScreeningEvent"]
        assert (events[0]["offers"]["url"], events[0]["startDate"]) == (
            ticket,
            page.select_one("a[data-start]")["data-start"],
        )
        assert events[-1]["offers"]["url"] == "https://example.com/later"
        assert [t["datetime"] for t in page.select(".schedule-dates time")] == [day.isoformat()]
        note = page.select_one(".programme-note")
        assert bool(note) == (offset >= 14)
        md = (out / path / "index.md").read_text()
        assert "En framtida resa." in md
        assert (f"{day.isoformat()}: [{label}]({ticket})" in md) == (offset < 14)
        if note:
            assert "Inga visningar de närmaste två veckorna" in note.get_text()
            assert str(day.year) in note.get_text()
            assert md.count("Inga visningar de närmaste två veckorna") == 1

    city = BeautifulSoup((out / "stad/stockholm/index.html").read_text(), "html.parser")
    assert city.select_one(".programme-note") is None
    assert not city.select(".schedule-film")
    graph = json.loads((out / "stad/stockholm/index.jsonld").read_text())["@graph"]
    assert sum(node["@type"] == "ScreeningEvent" for node in graph) == 2


def _blocks(db, tmp_path, screenings):
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen"}), path=db)
    write_screenings(screenings, path=db)
    sd = build._load_data(tmp_path / "out")
    days = build._compute_days(sd.screenings)
    return build._prepare_programme_blocks(sd, sd.screenings, days, city="Stockholm")


def test_formats_split_a_film_into_variant_blocks(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(tmdb_id=42, date=day, ticket_url="https://example.com/a"),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/b",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/c",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
        ],
    )
    assert {(b["film_title"], b["variant"]) for b in blocks} == {
        ("Filmen", "IMAX"),
        ("Filmen", ""),
    }
    assert len({b["film_id"] for b in blocks}) == 2


def test_language_labels_only_films_playing_in_several(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/a",
                version=ContentVersion(audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
            ),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/b",
                version=ContentVersion(audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
            ),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/c",
                version=ContentVersion(audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH}))),
            ),
        ],
    )
    assert {b["variant"]: b["mi"] for b in blocks} == {
        "Svenskt tal": "Svenskt tal",
        "Originalversion · Engelskt tal": "Engelskt tal",
    }


def test_language_and_subtitles_go_in_the_details_line(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/a",
                version=ContentVersion(
                    audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH})),
                    subtitles=SubtitleVersion(frozenset({Language.SWEDISH})),
                ),
            ),
            # Unknown language joins the film's only known one.
            screening(tmdb_id=42, date=day, ticket_url="https://example.com/b"),
        ],
    )
    assert [(b["variant"], b["mi"]) for b in blocks] == [("", "Engelskt tal • Svensk text")]


def test_programme_shows_formats_for_the_same_film(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "overview_sv": "En resa."}), path=db)
    write_screenings(
        [
            screening(tmdb_id=42, date=day, time=time(17, 15), ticket_url="https://example.com/ordinary"),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/imax",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
        ],
        path=db,
    )
    sd = build._load_data(tmp_path / "out")
    out = tmp_path / "out" / "index.html"
    build._write_programme(build._make_env(), sd, sd.screenings, title="T", breadcrumbs="", out_path=out, canonical="/")
    assert '<a href="/film/filmen/" title="Filmen">Filmen</a> <span class="film-variant">(IMAX)</span>' in (
        out.read_text()
    )
    markdown = out.with_suffix(".md").read_text()
    assert [line for line in markdown.splitlines() if line.startswith("## ")] == ["## [Filmen](/film/filmen/index.md)"]
    assert markdown.count("En resa.") == 1
    ordinary, imax = markdown.split("\n### IMAX\n")
    assert f"- {day}: [17:15](https://example.com/ordinary)" in ordinary
    assert f"- {day}: [18:30](https://example.com/imax)" in imax


def test_variants_of_a_film_are_adjacent(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    write_movie(Movie.from_dict({"tmdb_id": 7, "title_sv": "Annan"}), path=db)
    blocks = _blocks(
        db,
        tmp_path,
        [
            *(screening(tmdb_id=42, date=day, ticket_url=f"https://example.com/a{i}") for i in range(3)),
            *(screening(tmdb_id=7, date=day, ticket_url=f"https://example.com/b{i}") for i in range(2)),
            screening(
                tmdb_id=42,
                date=day,
                ticket_url="https://example.com/c",
                presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX})),
            ),
        ],
    )
    assert [b["film_title"] for b in blocks] == ["Filmen", "Filmen", "Annan"]
    assert {b["variant"] for b in blocks[:2]} == {"", "IMAX"}


def test_unsubtitled_reads_ej_textad(db, tmp_path):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    blocks = _blocks(
        db,
        tmp_path,
        [
            screening(
                tmdb_id=42,
                date=day,
                version=ContentVersion(
                    audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH})),
                    subtitles=SubtitleVersion(frozenset()),
                ),
            )
        ],
    )
    assert blocks[0]["mi"] == "Engelskt tal • Ej textad"


@pytest.mark.parametrize(
    ("city", "cinema", "other_source"),
    [
        ("Stockholm", "Biocafé Tellus", "nortic_se"),
        ("Malmö", "Hypnos Theatre", "hypnostheatre_com"),
        ("Götene", "Bio Göta Lejon", "nortic_se"),
    ],
)
def test_cross_source_screenings_share_a_programme_without_duplicate_showtimes(
    db, tmp_path, city, cinema, other_source
):
    day = datetime.now(tz=SWEDEN_TZ).date() + timedelta(days=1)
    known = {
        "version": ContentVersion(
            audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH})),
            subtitles=SubtitleVersion(frozenset({Language.SWEDISH})),
        ),
        "presentation": Presentation(dimension=Dimension.TWO_D),
        "screen": "Salongen",
    }
    write_films(
        [
            Film(key="bio_se:filmen", source="bio_se", title="Filmen", runtime=97),
            Film(key=f"{other_source}:filmen", source=other_source, title="Filmen"),
        ],
        path=db,
    )
    write_movie(movie(42), path=db)
    write_venue(Venue(city=city, name=cinema, address="Gatan 1"), path=db)
    write_screenings(
        [
            screening(
                tmdb_id=42,
                city=city,
                cinema_name=cinema,
                date=day,
                source="bio_se",
                film_key="bio_se:filmen",
                ticket_url="https://bio.se/biografer/cinema",
                **known,
            ),
            screening(
                tmdb_id=42,
                city=city,
                cinema_name=cinema,
                date=day,
                source=other_source,
                film_key=f"{other_source}:filmen",
                ticket_url="https://tickets.nortic.se/ticket/show/1",
            ),
            screening(
                tmdb_id=42,
                city=city,
                cinema_name=cinema,
                date=day,
                time=time(19, 30),
                source="bio_se",
                film_key="bio_se:filmen",
                ticket_url="https://bio.se/bokning/2",
            ),
            screening(
                tmdb_id=42,
                city=city,
                cinema_name=cinema,
                date=day,
                time=time(20, 30),
                source=other_source,
                film_key=f"{other_source}:filmen",
                ticket_url="https://tickets.nortic.se/ticket/show/3",
            ),
        ],
        path=db,
    )
    out = tmp_path / "out"
    sd = build._load_data(out)
    build._build_programme_pages(build._make_env(), sd)
    city_dir = out / "stad" / build._slugify_sv(city)
    graph = json.loads((city_dir / "index.jsonld").read_text())["@graph"]
    events = [node for node in graph if node["@type"] == "ScreeningEvent"]
    assert [event["startDate"][11:16] for event in events] == ["18:30", "19:30", "20:30"]
    first = events[0]
    assert first["offers"]["url"] == "https://tickets.nortic.se/ticket/show/1"
    assert "endDate" not in first
    assert first["inLanguage"] == ["en"]
    assert first["subtitleLanguage"] == ["sv"]
    assert first["videoFormat"] == "2D"
    assert sd.screenings[0].screen == "Salongen"
    html = BeautifulSoup((city_dir / "index.html").read_text(), "html.parser")
    assert len(html.select(".schedule-cell time")) == 3
    assert len(read_screenings(path=db)) == 4  # Source ownership is unchanged in storage.


@pytest.mark.parametrize(
    "difference",
    ["source", "hall", "language", "dimension", "runtime", "ambiguous_hall", "ambiguous_language", "ambiguous_runtime"],
)
def test_cross_source_deduplication_keeps_distinct_screenings(db, tmp_path, difference):
    first = {"source": "bio_se", "screen": "1"}
    second = {"source": "nortic_se", "screen": "1"}
    if difference == "source":
        second["source"] = "bio_se"
    elif difference.endswith("hall"):
        second["screen"] = "2"
    elif difference.endswith("language"):
        first["version"] = ContentVersion(audio=AudioVersion(languages=frozenset({Language.ENGLISH})))
        second["version"] = ContentVersion(audio=AudioVersion(languages=frozenset({Language.SWEDISH})))
    elif difference.endswith("runtime"):
        first["film_key"], second["film_key"] = "bio_se:filmen", "nortic_se:filmen"
        write_films(
            [
                Film(key=key, source=source, title="Filmen", runtime=length)
                for key, source, length in [(first["film_key"], "bio_se", 97), (second["film_key"], "nortic_se", 143)]
            ],
            path=db,
        )
    else:
        first["presentation"] = Presentation(dimension=Dimension.TWO_D)
        second["presentation"] = Presentation(dimension=Dimension.THREE_D)
    observations = [first, second]
    if difference.startswith("ambiguous"):
        observations.append({"source": "local"})
    if difference == "ambiguous_runtime":
        observations[-1]["film_key"] = "local:filmen"
        write_films([Film(key="local:filmen", source="local", title="Filmen")], path=db)
    write_movie(movie(42), path=db)
    write_screenings(
        [screening(tmdb_id=42, ticket_url=f"https://example.com/{i}", **facts) for i, facts in enumerate(observations)],
        path=db,
    )
    out = tmp_path / "out"
    sd = build._load_data(out)
    sd.today += timedelta(days=30)
    build._build_programme_pages(build._make_env(), sd)
    graph = json.loads((out / "stad/stockholm/index.jsonld").read_text())["@graph"]
    assert sum(node["@type"] == "ScreeningEvent" for node in graph) == len(observations)


def test_schedule_feeds_preserve_timezone_offsets_across_daylight_saving(db, tmp_path):
    day = date(2030, 3, 24)
    write_movie(Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen", "runtime": 97}), path=db)
    write_venue(Venue(city="Göteborg", name="Bio", address="Gatan 3"), path=db)
    write_screenings(
        [
            screening(
                tmdb_id=42,
                city="Göteborg",
                date=day + timedelta(days=1),
                time=time(12 + i // 60, i % 60),
                ticket_url=f"https://example.com/{i}",
                source="chain",
                raw_attributes=("Slutsålt",) if i == 0 else (),  # Previously stored observation.
            )
            for i in range(101)
        ]
        + [
            screening(
                city="Göteborg",
                date=day,
                time=time(9),
                title=UNTITLED,
                source="local",
                film_key=film_key("local", UNTITLED),
            ),
            screening(
                tmdb_id=42,
                city="Göteborg",
                cinema_name="Salong Ö",
                date=day + timedelta(days=13),
                time=time(20, 15),
                source="chain",
                screen="2",
                version=ContentVersion(
                    audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH})),
                    subtitles=SubtitleVersion(frozenset()),
                ),
                presentation=Presentation(dimension=Dimension.THREE_D),
                accessibility=Accessibility(frozenset({AccessibilityFeature.AUDIO_DESCRIPTION})),
            ),
            screening(tmdb_id=42, city="Göteborg", date=day - timedelta(days=1)),
            screening(tmdb_id=42, city="Göteborg", date=day + timedelta(days=14)),
            screening(tmdb_id=42, city="Malmö", date=day),
            screening(tmdb_id=42, city="Umeå", date=day + timedelta(days=14)),
        ],
        path=db,
    )
    out = tmp_path / "out"
    sd = build._load_data(out)
    sd.today = day
    sd.generated_at = datetime(2030, 3, 24, 8, tzinfo=SWEDEN_TZ)
    build._build_programme_pages(build._make_env(), sd)

    graph = json.loads((out / "stad/göteborg/index.jsonld").read_text())["@graph"]
    starts = {node["startDate"] for node in graph if node["@type"] == "ScreeningEvent"}
    assert {"2030-03-24T09:00:00+01:00", "2030-04-06T20:15:00+02:00"} <= starts
    calendar = (out / "stad/göteborg/index.ics").read_bytes()
    assert b"DTSTART:20300324T080000Z\r\n" in calendar
    assert b"DTSTART:20300406T181500Z\r\n" in calendar
    html = BeautifulSoup((out / "stad/göteborg/index.html").read_text(), "html.parser")
    assert len(html.select(".schedule-cell time")) == 103
    ticket = html.select_one('.schedule-cell a[href="https://example.com/0"]')
    assert ticket.time.string == "12:00"
    assert "sold-out" not in ticket.get("class", [])
    assert "slutsålt" not in str(ticket).casefold()
