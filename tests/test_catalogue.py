"""Public catalogue contracts: consolidation, URL history, and saved schedules."""

import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import build
from build import SWEDEN_TZ
from build.catalogue import read_catalogue, reconcile
from parse.queries import write_requests
from store import Film, Movie, Screening, film_key, read_screenings, write_films, write_movie, write_screenings


@pytest.fixture
def db(tmp_path):
    return tmp_path / "catalogue.db"


def add(db, source, *, title="Same film", runtime=None, year="", identifier=None, day=1, overview="", url=""):
    film = Film(
        key=film_key(source, title),
        source=source,
        title=title,
        runtime=runtime,
        release_date=year,
        overview=overview,
        url=url,
    )
    write_films([film], path=db)
    write_screenings(
        [
            Screening(
                tmdb_id=identifier,
                title=title,
                film_key=film.key,
                source=source,
                date=datetime.now(SWEDEN_TZ).date() + timedelta(days=day),
                time=time(18, 30),
                city="Stockholm",
                cinema_name="Bio",
                ticket_url=f"https://example.com/{source}",
            )
        ],
        path=db,
    )
    return film


def catalogue(db):
    return read_catalogue(Path("unused"), path=db)


def test_biopasset_applies_only_to_the_tagged_screening(db):
    source = "filmstaden_se"
    film = add(db, source)
    show = next(s for s in read_screenings(path=db) if s.film_key == film.key)
    tagged = replace(show, raw_attributes=("Biopasset 5",))
    ordinary = replace(show, time=time(20), raw_attributes=())
    write_screenings([tagged, ordinary], path=db, source=source)

    reconcile(path=db)

    assert {s.time: sorted(s.presentation.experiences) for s in catalogue(db).screenings} == {
        time(18, 30): ["Biopasset"],
        time(20): [],
    }


def test_audited_labels_follow_session_attributes(db):
    expected = {}
    for source in ("bio_se", "filmstaden_se"):
        film = add(db, source, title=source)
        show = next(s for s in read_screenings(path=db) if s.film_key == film.key)
        if source == "bio_se":
            show = replace(show, city="Lidköping", cinema_name="Lidköping Folkan")
            attributes = ("Föreställning där Cineville-kortet gäller", "Frallfika ingår")
            expected[source, time(18, 30)] = (["Cineville", "Frallfika ingår"], [])
        else:
            attributes = ("Syntolkning via app",)
            expected[source, time(18, 30)] = ([], ["Syntolkning via app"])
        expected[source, time(20)] = ([], [])
        write_screenings(
            [replace(show, raw_attributes=attributes), replace(show, time=time(20))], path=db, source=source
        )

    reconcile(path=db)

    assert {
        (s.source, s.time): (sorted(s.presentation.experiences), sorted(s.accessibility.features))
        for s in catalogue(db).screenings
    } == expected


def test_hypnos_operator_listing_keeps_its_runtime_and_direct_booking(db):
    day = datetime.now(SWEDEN_TZ).date() + timedelta(days=1)
    title = "La Chimera"
    operator = "hypnostheatre_com"
    broker = "bio_se"
    direct = "https://bio.se/bokning/cinemaId/31791/sessionId/77"
    write_movie(
        Movie.from_dict({"tmdb_id": 837335, "title_sv": title, "release_date": "2023", "runtime": 131}), path=db
    )
    for source, length, url in (
        (operator, 133, "https://bio.se/biografer/hypnos"),
        (broker, 130, direct),
    ):
        film = add(db, source, title=title, year="2023", runtime=length, identifier=837335)
        show = Screening(
            tmdb_id=837335,
            title=title,
            film_key=film.key,
            source=source,
            city="Malmö",
            cinema_name="Hypnos Theatre",
            date=day,
            time=time(19, 30),
            ticket_url=url,
        )
        extra = [replace(show, time=time(21), ticket_url=direct.removesuffix("77") + "79")] if source == broker else []
        write_screenings([show, *extra], path=db, source=source)

    reconcile(path=db, today=day)
    sd = read_catalogue(Path("unused"), path=db, today=day)
    assert [(s.source, s.ticket_url, build._screening_runtime(sd, s)) for s in sd.screenings] == [
        (operator, direct, 133),
    ]
    assert sorted(sd.screenings[0].version.subtitles.languages) == ["Engelska"]


def test_goteborg_audit_metadata_preserves_sessions_and_is_scoped(db):
    from datetime import date

    day = date(2026, 11, 21)
    film = Film(key="bioroy_se:sense and sensibility", title="Sense and Sensibility", source="bioroy_se", runtime=131)
    write_films([film], path=db)
    tea = Screening(
        tmdb_id=None,
        date=day,
        time=time(11, 30),
        ticket_url="https://secure.tickster.com/7ba2gljn3tf3wh7",
        cinema_name="Bio Roy",
        city="Göteborg",
        source="folkets_hus_och_parker",
        title=film.title,
        film_key=film.key,
        raw_attributes=("Afternoon Tea",),
    )
    ordinary = replace(tea, time=time(19), ticket_url="https://example.com/regular", raw_attributes=())
    write_screenings([tea, ordinary], path=db, source=tea.source)
    reconcile(path=db, today=day)
    sd = read_catalogue(Path("unused"), path=db, today=day)
    shows = sorted(sd.screenings, key=lambda s: s.time)
    assert [(s.time, s.ticket_url, sorted(s.presentation.experiences)) for s in shows] == [
        (time(11, 30), tea.ticket_url, ["Afternoon Tea"]),
        (time(19), ordinary.ticket_url, []),
    ]
    assert len({s.tmdb_id for s in shows}) == 1


def test_dune_provider_corrections_join_existing_pages(db):
    from parse.parsers import bio_se, osbyborgen_se

    title = "Dune: Part Three"
    identifier = 1170608
    write_movie(
        Movie.from_dict({"tmdb_id": identifier, "title_sv": title, "runtime": 150, "directors": ["Denis Villeneuve"]}),
        path=db,
    )
    add(db, "bio_se", title=title, runtime=90, day=1)
    add(db, "osbyborgen_se", title=title, day=2)
    add(db, "confirmed", title=title, runtime=150, identifier=identifier, day=3)
    reconcile(path=db)
    old_slugs = set(catalogue(db).film_slugs.values())
    assert len(old_slugs) == 3

    write_films(
        [
            bio_se._film({"id": 42095, "run_time": "90", "synopsis": "Regi: Denis Villeneuve."}, title),
            osbyborgen_se._film(
                {"f_id": 311, "f_title": title},
                {"f_synopsis": "Filmen är den tredje och sista delen i Denis Villeneuves sci-fi-trilogi."},
            ),
        ],
        path=db,
    )
    reconcile(path=db)
    result = catalogue(db)
    assert set(result.film_slugs.values()) == {"dune-part-three"}
    assert {result.film_aliases[slug] for slug in old_slugs - {"dune-part-three"}} == {"dune-part-three"}
    assert len(result.screenings) == 3


@pytest.mark.parametrize(
    ("name", "expected"), [("Hirokazu Koreeda", 1553969), ("Hirokazu Kore-eda", 1553969), ("Other Director", None)]
)
def test_sheep_in_the_box_matches_transliterated_director_credits(db, name, expected):
    title = "Sheep in the Box"
    film = add(db, "bioaspen_se", title=title, runtime=126)
    write_films([replace(film, directors=[name])], path=db)
    write_movie(
        Movie.from_dict({"tmdb_id": 1553969, "title_sv": title, "directors": ["是枝裕和"], "runtime": 126}), path=db
    )
    reconcile(path=db)
    assert list(catalogue(db).tmdb_ids.values()) == [expected]


@pytest.mark.parametrize(("runtime", "expected"), [(123, 1481789), (124, None)])
def test_javla_karlar_keeps_cinema_runtime_without_losing_identity(db, runtime, expected):
    title = "Jävla karlar"
    overview = (
        "Julen 1983. Efter ännu ett våldsamt gräl avslöjar sjuårige Andrevs mamma en hemlighet för honom: "
        "hans pappa är faktiskt inte hans pappa. I stället för att bli förkrossad blir Andrev exalterad över "
        "de möjligheter avslöjandet innebär."
    )
    peer = add(db, "filmstaden_se", title=title, runtime=108, overview=overview)
    cinema = add(
        db,
        "biofagelbla_se",
        title=title,
        runtime=runtime,
        overview=overview,
        day=2,
        url="https://biofagelbla.se/movie/bloody-men/",
    )
    write_films([replace(peer, directors=["Jens Sjögren"])], path=db)
    write_movie(
        Movie.from_dict({"tmdb_id": 1481789, "title_sv": title, "directors": ["Jens Sjögren"], "runtime": 108}), path=db
    )
    reconcile(path=db)
    sd = catalogue(db)
    assert list(sd.tmdb_ids.values()) == [expected]
    assert sd.films[cinema.key].runtime == runtime


def test_saved_catalogue_builds_without_source_fetch_dependencies(db, tmp_path):
    film = add(db, "a", runtime=103, year="2026", overview="A preserved film synopsis.")
    reconcile(path=db)
    slug = next(iter(catalogue(db).film_slugs.values()))
    output = tmp_path / "site"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "sys.path.insert(0, sys.argv.pop(1)); "
            "sys.modules.update(dict.fromkeys(('requests', 'bs4', 'curl_cffi', 'playwright'))); "
            "from build import main; main()",
            str(Path(build.__file__).resolve().parents[1]),
            str(output),
            "--db",
            str(db),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    page = BeautifulSoup((output / "film" / slug / "index.html").read_text(), "html.parser")
    assert page.select_one(".film-title").get_text(strip=True) == film.title
    assert len(page.select("a[data-start]")) == 1


@pytest.mark.parametrize("refresh", [False, True])
def test_known_pages_survive_last_screening_without_publishing_old_tickets(db, tmp_path, refresh):
    film = add(db, "a", runtime=103, year="2026", overview="A preserved film synopsis.")
    # Old raw imports may contain superseded place names that were never in the
    # catalogue. Retention is not permission to recreate arbitrary raw URLs.
    original = read_screenings(path=db)[0]
    write_screenings([replace(original, city="Legacy city", date=original.date - timedelta(days=10))], path=db)
    reconcile(path=db)
    before = catalogue(db)
    slug = next(iter(before.film_slugs.values()))
    later = before.today + timedelta(days=3)
    if refresh:
        # Source refreshes can remove screenings entirely, not just expire them.
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM screenings")
        reconcile(path=db, today=later)
    sd = read_catalogue(tmp_path / "site", path=db, today=later)
    assert not sd.screenings
    build._build_programme_pages(build._make_env(), sd)
    build._write_sitemap(sd)
    for prefix in ("film", "stad/stockholm/film"):
        path = sd.out_dir / prefix / slug / "index.html"
        page = BeautifulSoup(path.read_text(), "html.parser")
        assert page.select_one(".film-title").get_text(strip=True) == film.title
        assert film.overview in page.get_text()
        assert "Inga kommande visningar publicerade." in page.get_text()
        assert not page.select(".schedule-header, .schedule-dates, .schedule-cell, .schedule-film, .poster-placeholder")
        assert not page.select("a[data-start]")
        assert not page.select('meta[name="robots"][content*="noindex"]')
        assert page.select_one('link[rel="canonical"]')["href"] == f"https://allabiografer.se/{prefix}/{slug}/"
        graphs = [json.loads(node.string) for node in page.select('script[type="application/ld+json"]')]
        assert not any(node["@type"] == "ScreeningEvent" for graph in graphs for node in graph.get("@graph", []))
        assert film.overview in path.with_suffix(".md").read_text()
        assert f"/{prefix}/{slug}/" in (sd.out_dir / "sitemap.xml").read_text()
    assert (sd.out_dir / "stad/stockholm/index.html").is_file()
    assert (sd.out_dir / "stad/stockholm/bio/index.html").is_file()
    for path in ("stad/stockholm/index.html", "stad/stockholm/bio/index.html"):
        page = BeautifulSoup((sd.out_dir / path).read_text(), "html.parser")
        assert page.h1 is not None
        assert not page.select(".schedule-header, .schedule-dates, .schedule-cell")
    graph = json.loads((sd.out_dir / "stad/stockholm/index.jsonld").read_text())["@graph"]
    assert not any(node["@type"] == "ScreeningEvent" for node in graph)
    assert not (sd.out_dir / "film/unknown/index.html").exists()
    assert not (sd.out_dir / "stad/legacy-city/index.html").exists()


def test_unmatched_sources_join_with_year_and_runtime_but_not_title_alone(db):
    add(db, "a", runtime=105, year="2026-11-27", day=1)
    add(db, "b", runtime=106, year="2026-12-02", day=2)
    add(db, "c", day=3)

    stats = reconcile(path=db)
    sd = catalogue(db)

    assert stats["films"] == 2
    assert len(sd.screenings) == 3
    identities = {s.source: s.tmdb_id for s in sd.screenings}
    assert identities["a"] == identities["b"] != identities["c"]
    assert set(sd.film_slugs.values()) == {"same-film", "same-film-2"}
    assert all(value is None for value in sd.tmdb_ids.values())
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM reconciliation_candidates").fetchone()[0] > 0
        evidence = [json.loads(row[0])["matches"] for row in conn.execute("SELECT data FROM catalogue_members")]
        assert any(match["reason"] == "title_year_runtime" for matches in evidence for match in matches)


@pytest.mark.parametrize(
    ("title", "labelled"),
    [
        ("An Island Mystery", "Filmfeber: An Island Mystery"),
        ("An Island Mystery", "An Island Mystery (Live på bio)"),
        ("An Island Mystery", "An Island Mystery: Bioupplevelsen"),
        ("An Island Mystery", "An Island Mystery Cinema Experience"),
    ],
)
def test_programme_labels_discover_matches_without_becoming_identity_evidence(db, title, labelled):
    plot = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    add(db, "a", title=title, runtime=103, overview=plot, day=1)
    labelled_film = add(db, "b", title=labelled, runtime=105, overview=plot, day=2)
    # A normalized title alone cannot join a sparse record or a different cut.
    add(db, "sparse", title=labelled, day=3)
    add(db, "cut", title=labelled, runtime=150, overview=plot, day=4)
    add(db, "sequel", title=f"{title}: A New Chapter", runtime=103, overview=plot, day=5)

    assert reconcile(path=db)["films"] == 4
    sd = catalogue(db)
    identities = {s.source: s.tmdb_id for s in sd.screenings}
    assert identities["a"] == identities["b"]
    assert len({identities[s] for s in ("a", "sparse", "cut", "sequel")}) == 4
    assert len(sd.screenings) == 5

    # A subsequent source import now emits a clean key. Historical labelled
    # observations must not resurrect the duplicate or lose its URL history.
    refreshed = replace(labelled_film, key=film_key("b", title), title=title)
    write_films([refreshed], path=db)
    screening = next(s for s in read_screenings(path=db) if s.source == "b")
    write_screenings([replace(screening, title=title, film_key=refreshed.key)], path=db, source="b")
    assert reconcile(path=db)["films"] == 4
    assert catalogue(db).film_slugs == sd.film_slugs
    assert len(catalogue(db).screenings) == 5


def test_tmdb_identity_joins_translations_and_editions_without_inventing_tmdb_ids(db, tmp_path):
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 5961,
                "title_sv": "Fanny och Alexander",
                "title_original": "Fanny and Alexander",
                "runtime": 180,
                "release_date": "1982-12-17",
            }
        ),
        path=db,
    )
    add(
        db,
        "a",
        title="Fanny och Alexander",
        runtime=326,
        year="1982",
        overview="Den fem timmar långa versionen.",
        identifier=5961,
    )
    add(db, "b", title="Fanny and Alexander", runtime=180, year="1982", identifier=5961)

    reconcile(path=db)
    sd = catalogue(db)
    assert len(sd.movies) == 1
    assert len(sd.screenings) == 2
    assert list(sd.tmdb_ids.values()) == [5961]
    sd.out_dir = tmp_path / "site"
    build._build_programme_pages(build._make_env(), sd)
    graph = json.loads((sd.out_dir / "stad/stockholm/index.jsonld").read_text())["@graph"]
    events = [node for node in graph if node["@type"] == "ScreeningEvent"]
    assert {
        (datetime.fromisoformat(node["endDate"]) - datetime.fromisoformat(node["startDate"])).total_seconds() / 60
        for node in events
    } == {180, 326}
    assert len({node["workPresented"]["@id"] for node in events}) == 1


def test_same_title_different_works_and_ambiguous_bridge_remain_separate(db):
    for identifier, runtime in ((42, 121), (16367, 107)):
        write_movie(Movie.from_dict({"tmdb_id": identifier, "title_sv": "Kinky Boots", "runtime": runtime}), path=db)
    add(db, "feature", title="Kinky Boots", identifier=16367)
    add(db, "adaptation", title="Kinky Boots", identifier=42)
    add(db, "musical", title="Kinky Boots", runtime=135)
    add(db, "short", title="Kinky Boots", runtime=10)

    assert reconcile(path=db)["films"] == 4
    assert len(set(catalogue(db).film_slugs.values())) == 4


def test_runtime_similarity_chain_does_not_merge_transitively(db):
    for source, runtime in (("a", 131), ("b", 133), ("c", 135)):
        add(db, source, runtime=runtime, year="2026", day=runtime)

    assert reconcile(path=db)["films"] == 3
    before = catalogue(db).film_slugs
    assert reconcile(path=db)["films"] == 3
    assert catalogue(db).film_slugs == before
    with sqlite3.connect(db) as conn:
        reasons = {row[0] for row in conn.execute("SELECT reason FROM reconciliation_candidates")}
    assert "ambiguous_chain" in reasons


def test_source_film_url_survives_partial_tmdb_enrichment_and_other_edition_runtimes(db):
    write_movie(
        Movie.from_dict({"tmdb_id": 77, "title_sv": "Same film", "runtime": 150, "release_date": "2026-01-01"}), path=db
    )
    add(
        db,
        "a",
        runtime=90,
        year="2026",
        overview="The cinema's bioversion.",
        identifier=77,
        url="https://cinema.test/film/123",
        day=1,
    )
    add(db, "b", runtime=145, year="2026", identifier=77, day=2)
    add(
        db, "a", runtime=90, year="2026", overview="The cinema's bioversion.", url="https://cinema.test/film/123", day=3
    )

    assert reconcile(path=db)["films"] == 1
    assert len(catalogue(db).screenings) == 3


def test_conflicting_unsubstantiated_ids_do_not_choose_a_tmdb_winner(db):
    add(db, "a", identifier=77, url="https://cinema.test/film/123", day=1)
    add(db, "a", identifier=88, url="https://cinema.test/film/123", day=2)
    add(db, "a", url="https://cinema.test/film/123", day=3)

    assert reconcile(path=db)["films"] == 1
    assert list(catalogue(db).tmdb_ids.values()) == [None]
    with sqlite3.connect(db) as conn:
        decision = json.loads(conn.execute("SELECT data FROM catalogue_tmdb_matches").fetchone()[0])
    assert {c["tmdb_id"] for c in decision["candidates"]} == {77, 88}
    assert all(c["rejected"] for c in decision["candidates"])


def test_inferred_runtime_does_not_veto_agreeing_source_metadata(db):
    overview = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    write_movie(Movie.from_dict({"tmdb_id": 77, "title_sv": "Same film", "runtime": 103}), path=db)
    add(db, "a", runtime=109, identifier=77, overview=overview, day=1)
    add(db, "b", identifier=77, overview=overview, day=2)
    add(db, "c", runtime=109, overview=overview, day=3)

    assert reconcile(path=db)["films"] == 1


@pytest.mark.parametrize(
    ("runtime", "year", "title", "films"),
    [
        (105, "", "Same film", 1),
        (125, "", "Same film", 1),
        (132, "", "Same film", 1),
        (133, "", "Same film", 2),
        (188, "", "Same film", 2),
        (105, "1995", "Same film", 2),
        (105, "", "Another film", 2),
    ],
)
def test_substantial_synopsis_containment_with_programme_lengths_and_identity_controls(db, runtime, year, title, films):
    synopsis = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    add(db, "a", runtime=106, year="2026", overview=synopsis, day=1)
    add(db, "b", title=title, runtime=runtime, year=year, overview=synopsis + " Directed by Alex Smith.", day=2)

    assert reconcile(path=db)["films"] == films


def test_short_generic_synopsis_is_not_identity_evidence(db):
    for source, day in [("a", 1), ("b", 2)]:
        add(
            db, source, runtime=100, overview="An unforgettable cinematic experience. Book your tickets today.", day=day
        )

    assert reconcile(path=db)["films"] == 2


@pytest.mark.parametrize(
    ("first_suffix", "second_suffix", "runtime", "films"),
    [
        ("", "", None, 1),
        ("", " Book tickets at the cinema.", None, 1),
        ("", "", 102, 1),
        ("", "", 103, 2),
        (" The expedition reaches a remote island.", " A contradictory ending changes the story.", None, 2),
    ],
)
def test_complete_short_synopsis_but_not_a_shared_short_fragment_identifies_film(
    db, first_suffix, second_suffix, runtime, films
):
    # Nineteen words, over 100 characters: specific enough as a complete synopsis,
    # but not enough as a fragment in two otherwise different descriptions.
    story = (
        "Den här julen ställs en arg fågel inför sin största utmaning hittills "
        "att överleva faderskapet och samtidigt rädda världen"
    )
    add(db, "a", runtime=100, overview=story + first_suffix, day=1)
    add(db, "b", runtime=runtime, overview=story + second_suffix, day=2)

    assert reconcile(path=db)["films"] == films


def test_source_introductions_and_trailing_credits_do_not_hide_shared_synopsis(db):
    story = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    add(db, "a", runtime=132, overview="Preview this Sunday. " + story, day=1)
    add(db, "b", runtime=138, overview=story + " Based on an award-winning novel.", day=2)
    add(db, "c", runtime=138, overview="Preview this Sunday. An unrelated adventure about a detective.", day=3)

    assert reconcile(path=db)["films"] == 2
    identities = {s.source: s.tmdb_id for s in catalogue(db).screenings}
    assert identities["a"] == identities["b"] != identities["c"]


def test_confirmed_title_aliases_share_the_works_synopsis_evidence(db):
    story = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    write_movie(
        Movie.from_dict(
            {"tmdb_id": 77, "title_sv": "Local title", "title_original": "International title", "runtime": 100}
        ),
        path=db,
    )
    add(db, "a", title="Local title", runtime=100, identifier=77, overview=story, day=1)
    add(db, "b", title="International title", runtime=100, identifier=77, day=2)
    add(db, "c", title="International title", runtime=100, overview=story, day=3)

    assert reconcile(path=db)["films"] == 1


def test_newly_confirmed_aliases_are_reconsidered_until_reconciliation_settles(db):
    story = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    add(db, "a", title="Local title", runtime=100, year="2026", overview=story, day=1)
    alias = add(db, "b", title="International title", runtime=100, year="2026", day=2)
    write_films([replace(alias, title_original="Local title")], path=db)
    add(db, "c", title="International title", overview=story, day=3)

    assert reconcile(path=db)["films"] == 1
    assert reconcile(path=db)["films"] == 1


def test_strong_programme_identity_precedes_weaker_year_runtime_matching(db):
    story = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    add(db, "a", runtime=109, year="2026", day=1)
    add(db, "b", runtime=109, year="2026", overview=story, day=2)
    add(db, "c", runtime=120, overview=story, day=3)

    assert reconcile(path=db)["films"] == 1


@pytest.mark.parametrize(("director", "films"), [("Robin Smith", 1), ("Someone Else", 2)])
def test_explicit_director_credit_corroborates_substantial_shared_text(db, director, films):
    story = (
        "A young architect returns to her childhood home with her family and discovers a hidden world "
        "behind the familiar rooms, forcing them to confront an extraordinary secret together."
    )
    first = (
        "This ambitious documentary traces an expedition across the northern mountains, following the team "
        "as they prepare supplies, study weather patterns, and meet local guides who share stories of past "
        "journeys. Their journey is recorded through interviews and intimate observations of everyday life. "
    )
    second = (
        "An acclaimed ensemble brings remarkable warmth and humour to this intimate portrait of a community "
        "in transition. With distinctive visual storytelling and an unforgettable original score, the film "
        "explores the choices that connect neighbours and strangers through unexpected encounters "
        "and lasting friendships. "
    )
    write_movie(
        Movie.from_dict({"tmdb_id": 77, "title_sv": "Same film", "runtime": 100, "directors": ["Robin Smith"]}), path=db
    )
    add(db, "a", runtime=100, identifier=77, overview=first + story, day=1)
    add(db, "b", overview=second + story + f" Regi {director}.", day=2)

    assert reconcile(path=db)["films"] == films


def test_candidates_only_reference_separate_final_film_identities(db):
    add(db, "a", runtime=105, year="2026", day=1)
    add(db, "b", runtime=106, year="2026", day=2)
    # This member matches a's showtime; b connects through a, not directly to c.
    add(db, "c", day=1)
    assert reconcile(path=db)["films"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM reconciliation_candidates").fetchone()[0] == 0


def test_slug_survives_title_changes_tmdb_enrichment_and_competitor_expiry(db):
    film = add(db, "a", runtime=100, year="2026")
    reconcile(path=db)
    before = catalogue(db)
    identity = next(iter(before.movies))
    original_slug = before.film_slugs[identity]

    write_requests({film.key: [{"title": film.title, "runtime": 100, "year": 2026}]}, source="a", path=db)
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 71,
                "title_sv": "Changed title",
                "title_original": "Same film",
                "runtime": 100,
                "release_date": "2026-01-01",
            }
        ),
        path=db,
    )
    reconcile(path=db)
    after = catalogue(db)
    assert list(after.movies) == [identity]
    assert after.movies[identity].title_sv == "Changed title"
    assert after.film_slugs[identity] == original_slug
    assert after.tmdb_ids[identity] == 71

    write_movie(Movie.from_dict({"tmdb_id": 72, "title_sv": "Same film", "runtime": 15}), path=db)
    add(db, "short", runtime=15, identifier=72)
    reconcile(path=db)
    before_expiry = catalogue(db).film_slugs
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM screenings WHERE source = 'short'")
    reconcile(path=db)
    assert catalogue(db).film_slugs[identity] == before_expiry[identity]
    assert catalogue(db).film_slugs[identity] == original_slug


def test_later_merge_keeps_first_slug_and_records_direct_alias(db, tmp_path):
    a = add(db, "a", day=1)
    b = add(db, "b", day=2)
    reconcile(path=db)
    assert len(catalogue(db).movies) == 2
    write_films([replace(film, runtime=104, release_date="2026") for film in (a, b)], path=db)

    reconcile(path=db)
    sd = catalogue(db)
    assert len(sd.movies) == 1
    assert list(sd.film_slugs.values()) == ["same-film"]
    assert sd.film_aliases["same-film-2"] == "same-film"
    reconcile(path=db)
    assert catalogue(db).film_aliases == sd.film_aliases

    later = sd.today + timedelta(days=3)
    reconcile(path=db, today=later)
    expired = read_catalogue(tmp_path / "site", path=db, today=later)
    assert expired.film_aliases == sd.film_aliases
    build._build_programme_pages(build._make_env(), expired)
    build._write_film_redirects(expired)
    redirects = (expired.out_dir / "film-redirects.map").read_text()
    assert '"/film/same-film-2/" "/film/same-film/";' in redirects
    assert '"/stad/stockholm/film/same-film-2/" "/stad/stockholm/film/same-film/";' in redirects

    # Evidence is reevaluated: a later correction can undo an incorrect join.
    write_films([replace(b, runtime=10, release_date="1995")], path=db)
    reconcile(path=db)
    assert len(catalogue(db).movies) == 2
    assert "same-film" in catalogue(db).film_slugs.values()


def test_shared_showtime_joins_sources_then_deduplicates_the_schedule(db):
    add(db, "a", title="Hexe", runtime=90)
    add(db, "b", title="Hexe", runtime=90)
    stats = reconcile(path=db)
    assert stats["source_screenings"] == 2
    assert stats["films"] == stats["screenings"] == 1


def test_expiring_shared_show_does_not_undo_confirmed_identity(db):
    write_movie(Movie.from_dict({"tmdb_id": 77, "title_sv": "Hexe", "runtime": 90}), path=db)
    add(db, "a", title="Hexe", runtime=90, identifier=77)
    add(db, "b", title="Hexe", runtime=90)
    add(db, "a", title="Hexe", runtime=90, identifier=77, day=30)
    reconcile(path=db)
    before = catalogue(db)
    assert len(before.movies) == 1

    reconcile(path=db, today=datetime.now(SWEDEN_TZ).date() + timedelta(days=2))
    assert catalogue(db).film_slugs == before.film_slugs
    with sqlite3.connect(db) as conn:
        # Expiry must not allocate a new identity for the now-inactive source.
        assert conn.execute("SELECT count(*) FROM catalogue_films").fetchone()[0] == 1
    reconcile(path=db)
    assert catalogue(db).film_aliases == before.film_aliases


def test_failed_snapshot_write_rolls_back_registry_and_preserves_schedule(db):
    add(db, "a", title="First")
    reconcile(path=db)
    before = catalogue(db)
    add(db, "b", title="Second")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TRIGGER prevent_publish BEFORE INSERT ON catalogue_snapshot BEGIN "
            "SELECT RAISE(ABORT, 'injected storage failure'); END"
        )
        count = conn.execute("SELECT count(*) FROM catalogue_films").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="injected storage failure"):
        reconcile(path=db)
    assert catalogue(db).film_slugs == before.film_slugs
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM catalogue_films").fetchone()[0] == count


def test_static_build_reads_saved_schedule_not_unreconciled_source_rows(db, tmp_path, monkeypatch):
    add(db, "a", title="Published film")
    reconcile(path=db)
    add(db, "b", title="Not published yet")
    out = tmp_path / "site"
    monkeypatch.setattr(sys, "argv", ["build", str(out), "--db", str(db)])
    build.main()
    assert (out / "film/published-film/index.html").is_file()
    assert not (out / "film/not-published-yet/index.html").exists()
    assert "not-published-yet" not in (out / "sitemap.xml").read_text()
    assert (out / "film-redirects.map").is_file()


def test_source_group_combines_year_and_runtime_before_matching_cached_tmdb(db):
    add(db, "a", year="2026", day=1)
    add(db, "b", runtime=99, day=1)
    write_movie(
        Movie.from_dict({"tmdb_id": 77, "title_sv": "Same film", "release_date": "2026-04-01", "runtime": 99}), path=db
    )
    reconcile(path=db)
    assert list(catalogue(db).tmdb_ids.values()) == [77]


def test_source_arrival_order_does_not_change_unenriched_titles_or_schedule(db):
    add(db, "a", runtime=100, year="2026", day=1)
    add(db, "b", title="Same film!", runtime=100, year="2026", day=2)
    reconcile(path=db)
    before = catalogue(db)
    rows = read_screenings(path=db)
    for source in ("a", "b"):
        write_screenings([], source=source, path=db)
    write_screenings(list(reversed(rows)), path=db)

    reconcile(path=db)
    after = catalogue(db)
    assert after.movies == before.movies
    assert after.screenings == before.screenings
    assert after.film_slugs == before.film_slugs


def test_incorrect_existing_tmdb_claim_does_not_contaminate_source_group(db):
    add(db, "a", runtime=100, year="2026", identifier=77)
    add(db, "b", runtime=100, year="2026")
    write_movie(
        Movie.from_dict({"tmdb_id": 77, "title_sv": "Unrelated film", "release_date": "1990-01-01", "runtime": 100}),
        path=db,
    )
    reconcile(path=db)
    sd = catalogue(db)
    assert len(sd.movies) == 1
    assert list(sd.tmdb_ids.values()) == [None]
    assert next(iter(sd.movies.values())).title_sv == "Same film"


def test_corrected_source_facts_replace_history_when_source_claim_changes(db):
    for identifier, year in ((7, "1984"), (8, "1985")):
        write_movie(
            Movie.from_dict({"tmdb_id": identifier, "title_sv": "Same film", "runtime": 100, "release_date": year}),
            path=db,
        )
    add(db, "a", runtime=100, year="1984", url="https://example.com/film")
    reconcile(path=db)
    before = catalogue(db)
    assert list(before.tmdb_ids.values()) == [7]

    write_screenings([], source="a", path=db)
    add(db, "a", runtime=100, year="1985", identifier=8, url="https://example.com/film")
    reconcile(path=db)
    after = catalogue(db)
    assert list(after.tmdb_ids.values()) == [8]
    assert after.film_slugs == before.film_slugs


def test_existing_tmdb_id_does_not_win_over_another_qualifying_candidate(db):
    add(db, "a", runtime=100, identifier=77)
    for identifier, year in ((77, 2026), (78, 1990)):
        write_movie(
            Movie.from_dict(
                {"tmdb_id": identifier, "title_sv": "Same film", "release_date": f"{year}-01-01", "runtime": 100}
            ),
            path=db,
        )
    reconcile(path=db)
    assert list(catalogue(db).tmdb_ids.values()) == [None]


def test_same_claimed_tmdb_id_cannot_join_conflicting_source_years(db):
    add(db, "a", runtime=100, year="1990", identifier=77, day=1)
    add(db, "b", runtime=100, year="2026", identifier=77, day=2)
    write_movie(
        Movie.from_dict({"tmdb_id": 77, "title_sv": "Same film", "release_date": "2026-01-01", "runtime": 100}), path=db
    )
    assert reconcile(path=db)["films"] == 2
    assert set(catalogue(db).tmdb_ids.values()) == {None, 77}


def test_later_alias_discovery_cannot_leave_an_earlier_false_unique_match(db, monkeypatch):
    from parse import tmdb

    add(db, "a", title="Reunion", runtime=100, day=1)
    add(db, "b", title="Later alias", runtime=100, day=2)
    write_movie(Movie.from_dict({"tmdb_id": 7, "title_sv": "Reunion", "runtime": 100}), path=db)

    def get(session, url, **params):
        if url.endswith("/search/movie"):
            identifier = 7 if params["query"] == "reunion" else 8
            return {"results": [{"id": identifier, "title": params["query"]}]}
        return {
            "id": int(url.rsplit("/", 1)[1]),
            "title": "Reunion",
            "runtime": 100,
            "original_title": "Later alias" if url.endswith("/8") else "First work",
            "original_language": "en",
            "spoken_languages": [],
            "credits": {"crew": []},
        }

    monkeypatch.setattr(tmdb, "_get", get)
    reconcile(path=db, enrich=True)
    sd = catalogue(db)
    identifiers = {s.source: sd.tmdb_ids[s.tmdb_id] for s in sd.screenings}
    assert identifiers == {"a": None, "b": 8}


@pytest.mark.parametrize(
    ("runtime", "year", "competitor", "expected"),
    [
        (105, "", False, 77),
        (None, "", False, None),
        (106, "", False, None),
        (105, "1984", False, None),
        (105, "", True, None),
    ],
)
def test_validated_source_titles_discover_candidates_but_still_need_independent_evidence(
    db, runtime, year, competitor, expected
):
    add(db, "a", title="Local title", runtime=runtime, year=year, day=1)
    known = add(db, "z", title="Local title", runtime=100, year="2026", day=2)
    write_films([replace(known, title_original="International title")], path=db)
    write_movie(
        Movie.from_dict(
            {"tmdb_id": 77, "title_sv": "International title", "runtime": 100, "release_date": "2026-01-01"}
        ),
        path=db,
    )
    if competitor:
        write_movie(
            Movie.from_dict({"tmdb_id": 88, "title_sv": "Local title", "runtime": 105, "release_date": "1984-01-01"}),
            path=db,
        )

    reconcile(path=db)
    sd = catalogue(db)
    assert {s.source: sd.tmdb_ids[s.tmdb_id] for s in sd.screenings} == {"a": expected, "z": 77}
    assert len(sd.movies) == (1 if expected else 2)
    reconcile(path=db)
    assert catalogue(db).film_slugs == sd.film_slugs


def test_outage_retains_only_an_unchanged_still_validated_association(db, monkeypatch):
    import requests

    from parse import tmdb

    film = add(db, "a", runtime=100, year="2020")
    write_movie(
        Movie.from_dict(
            {
                "tmdb_id": 7,
                "title_sv": "Same film",
                "runtime": 100,
                "release_date": "2020-01-01",
                "original_language": "en",
                "spoken_languages": [],
                "directors": [],
            }
        ),
        path=db,
    )
    reconcile(path=db)
    assert list(catalogue(db).tmdb_ids.values()) == [7]

    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("injected outage")

    monkeypatch.setattr(tmdb, "_get", unavailable)
    reconcile(path=db, enrich=True)
    assert list(catalogue(db).tmdb_ids.values()) == [7]
    write_films([replace(film, release_date="1990")], path=db)
    reconcile(path=db, enrich=True)
    assert list(catalogue(db).tmdb_ids.values()) == [None]
