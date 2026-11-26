from datetime import date

from conftest import contents
from conftest import slug as films_of_name

from allabiografer.merge import FILM, merge_datasets

DAY = date(2026, 12, 1)


def test_feeds_not_rerun_keep_previous_screenings(graph, parsed):
    first = merge_datasets(
        graph,
        None,
        [
            parsed(graph, "bio_se", ["Bio Rio"], {"a": ({"name": "Dune"}, [("Bio Rio", "2026-12-02T18:00:00+01:00")])}),
            parsed(graph, "x", ["Aspen"], {"b": ({"name": "Heat"}, [("Aspen", "2026-12-02T20:00:00+01:00")])}),
        ],
        DAY,
    )
    rerun = parsed(graph, "x", ["Aspen"], {"b": ({"name": "Heat"}, [("Aspen", "2026-12-03T20:00:00+01:00")])})
    second = merge_datasets(graph, first, [rerun], DAY)

    _, screenings = contents(graph, second)
    assert sorted((s["name"], s["startDate"]) for s in screenings) == [
        ("Dune", "2026-12-02T18:00:00+01:00"),
        ("Heat", "2026-12-03T20:00:00+01:00"),
    ]


def test_partial_rerun_of_a_source_keeps_its_other_feeds_on_one_film(graph, parsed):
    rio, aspen = ("Bio Rio", "2026-12-02T18:00:00+01:00"), ("Aspen", "2026-12-02T20:00:00+01:00")
    both = parsed(graph, "x", ["Bio Rio", "Aspen"], {"a": ({"name": "Dune"}, [rio, aspen])})
    first = merge_datasets(graph, None, [both], DAY)
    # The same source movie, re-parsed with changed details, for one of the source's cinemas.
    rerun = parsed(graph, "x", ["Bio Rio"], {"a": ({"name": "Dune", "duration": "PT155M"}, [rio])})
    second = merge_datasets(graph, first, [rerun], DAY)

    films, screenings = contents(graph, second)
    assert [film["duration"] for film in films.values()] == ["PT155M"]
    assert sorted((s["location"]["@id"], s["film"]) for s in screenings) == [
        ("../MovieTheater/Aspen.jsonld", "dune"),
        ("../MovieTheater/Bio%20Rio.jsonld", "dune"),
    ]


def test_old_screenings_drop_and_failed_runs_need_no_input(graph, parsed):
    first = merge_datasets(
        graph,
        None,
        [parsed(graph, "x", ["Aspen"], {"b": ({"name": "Heat"}, [("Aspen", "2026-12-02T20:00:00+01:00")])})],
        DAY,
    )
    later = merge_datasets(graph, first, [], date(2027, 1, 5))
    films, screenings = contents(graph, later)
    assert screenings == []
    assert [films_of_name(film) for film in films.values()] == ["heat"]


def test_slugs_are_stable_and_never_reassigned(graph, parsed):
    dune = ("Bio Rio", "2026-12-02T18:00:00+01:00")
    first = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], {"a": ({"name": "Dune"}, [dune])})], DAY)
    renamed = parsed(graph, "x", ["Bio Rio"], {"a": ({"name": "Dune: Part Two"}, [dune])})
    second = merge_datasets(graph, first, [renamed], DAY)
    other = parsed(graph, "x", ["Bio Rio"], {"c": ({"name": "Dune"}, [("Bio Rio", "2026-12-04T18:00:00+01:00")])})
    third = merge_datasets(graph, second, [other], DAY)

    assert [films_of_name(film) for film in contents(graph, second)[0].values()] == ["dune"]
    assert sorted(films_of_name(film) for film in contents(graph, third)[0].values()) == ["dune", "dune-2"]
    film = next(iter(contents(graph, second)[0].values()))
    assert film["url"] == "https://allabiografer.se/film/dune/"
    assert film["name"] == "Dune: Part Two"


def test_joined_films_keep_the_oldest_slug_and_alias_the_other(graph, parsed):
    plot = "En polis jagar en bankrånare genom Los Angeles medan båda försöker hålla ihop sina liv. " * 3
    rio = parsed(graph, "a", ["Bio Rio"], {"1": ({"name": "Heat", "description": plot}, [])})
    aspen = parsed(graph, "b", ["Aspen"], {"2": ({"name": "Heta nätter"}, [])})
    first = merge_datasets(graph, None, [rio], DAY)
    second = merge_datasets(graph, first, [aspen], date(2026, 12, 2))
    assert len(contents(graph, second)[0]) == 2
    # The second listing now carries the same distributor synopsis: one film.
    aspen = parsed(graph, "b", ["Aspen"], {"2": ({"name": "Heta nätter", "description": plot}, [])})
    third = merge_datasets(graph, second, [aspen], date(2026, 12, 3))

    (film,) = contents(graph, third)[0].values()
    assert [(item["propertyID"], item["value"]) for item in film["identifier"]] == [
        (FILM, "heat"),
        ("allabiografer:film-alias", "heta-nätter"),
    ]


def test_a_cinema_shows_every_feed_and_a_show_listed_twice_once(graph, parsed):
    """Arboga Bio and Arboga Bio Kontrast publish separately; both play at Arboga Bio."""
    own = ("Arboga Bio", "2026-12-02T18:00:00+01:00")
    kontrast = ("Arboga Bio Kontrast", "2026-12-07T19:00:00+01:00")
    both = [("Arboga Bio", "2026-12-03T19:00:00+01:00"), ("Arboga Bio Kontrast", "2026-12-03T19:00:00+01:00")]
    films = {"a": ({"name": "Dune"}, [own]), "b": ({"name": "Bad Apples"}, [kontrast, *both])}
    merged = merge_datasets(graph, None, [parsed(graph, "bio_se", ["Arboga Bio", "Arboga Bio Kontrast"], films)], DAY)

    _, screenings = contents(graph, merged)
    assert sorted((s["film"], s["startDate"], s["location"]["@id"], "organizer" in s) for s in screenings) == [
        ("bad-apples", "2026-12-03T19:00:00+01:00", "../MovieTheater/Arboga%20Bio.jsonld", False),
        ("bad-apples", "2026-12-07T19:00:00+01:00", "../MovieTheater/Arboga%20Bio.jsonld", True),
        ("dune", "2026-12-02T18:00:00+01:00", "../MovieTheater/Arboga%20Bio.jsonld", False),
    ]
    assert graph.read(merged)["about"] == [{"@id": "../MovieTheater/Arboga%20Bio.jsonld"}]


def test_a_failed_feed_keeps_its_screenings_without_touching_the_cinemas_other_feeds(graph, parsed):
    own = {"a": ({"name": "Dune"}, [("Arboga Bio", "2026-12-02T18:00:00+01:00")])}
    kontrast = {"b": ({"name": "Bad Apples"}, [("Arboga Bio Kontrast", "2026-12-07T19:00:00+01:00")])}
    first = merge_datasets(
        graph,
        None,
        [parsed(graph, "x", ["Arboga Bio"], own), parsed(graph, "y", ["Arboga Bio Kontrast"], kontrast)],
        DAY,
    )
    # The cinema's own feed is re-run and now lists nothing; Kontrast's adapter failed.
    second = merge_datasets(graph, first, [parsed(graph, "x", ["Arboga Bio"], {})], DAY)

    _, screenings = contents(graph, second)
    assert [s["film"] for s in screenings] == ["bad-apples"]


def test_past_screenings_are_kept_for_thirty_days(graph, parsed):
    from datetime import timedelta

    listed = {"a": ({"name": "Heat"}, [("Aspen", "2026-12-02T20:00:00+01:00")])}
    first = merge_datasets(graph, None, [parsed(graph, "x", ["Aspen"], listed)], DAY)
    # The feed no longer lists the past show; the merged result remembers it.
    later = merge_datasets(graph, first, [parsed(graph, "x", ["Aspen"], {})], date(2026, 12, 10))
    assert [s["startDate"] for s in contents(graph, later)[1]] == ["2026-12-02T20:00:00+01:00"]
    gone = merge_datasets(graph, later, [], date(2026, 12, 2) + timedelta(days=31))
    assert contents(graph, gone)[1] == []
