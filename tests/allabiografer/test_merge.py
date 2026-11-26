import shutil
from datetime import date

import pytest

from allabiografer.graph import DATA, Graph
from allabiografer.merge import FILM, merge_datasets
from allabiografer.parsing import PREFIX

DAY = date(2026, 12, 1)


@pytest.fixture
def graph(tmp_path):
    shutil.copytree(DATA / "schema" / "MovieTheater", tmp_path / "schema" / "MovieTheater")
    return Graph(tmp_path)


def parsed(graph, adapter, cinemas, films, *, day=DAY):
    """A parse Dataset: `films` maps a movie ID to (fields, [(cinema, start)])."""
    parts = []
    about = [
        graph.ref(graph.path("MovieTheater", cinema)) | {"identifier": {"propertyID": PREFIX + adapter}}
        for cinema in cinemas
    ]
    for movie_id, (fields, shows) in films.items():
        movie = graph.put(
            "Movie", {"identifier": {"propertyID": PREFIX + adapter, "value": movie_id}, "isBasedOn": "x", **fields}
        )
        parts.append(movie)
        for cinema, start in shows:
            parts.append(
                graph.put(
                    "ScreeningEvent",
                    {
                        "name": fields["name"],
                        "startDate": start,
                        "workPresented": graph.ref(movie),
                        "location": graph.ref(graph.path("MovieTheater", cinema)),
                    },
                )
            )
    return graph.put(
        "Dataset",
        {"temporalCoverage": day.isoformat(), "about": about, "hasPart": [graph.ref(path) for path in parts]},
    )


def contents(graph, dataset):
    films, screenings = {}, []
    for reference in graph.read(dataset)["hasPart"]:
        path = graph.resolve(dataset, reference)
        entity = graph.read(path)
        if entity["@type"] == "Movie":
            films[path] = entity
        else:
            screenings.append(entity | {"film": films_of(graph, path, entity)})
    return films, screenings


def films_of(graph, path, screening):
    return films_of_name(graph.read(graph.resolve(path, screening["workPresented"])))


def test_cinemas_not_rerun_keep_previous_screenings(graph):
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


def test_partial_rerun_of_a_source_keeps_its_other_cinemas_on_one_film(graph):
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


def test_past_screenings_drop_and_failed_runs_need_no_input(graph):
    first = merge_datasets(
        graph,
        None,
        [parsed(graph, "x", ["Aspen"], {"b": ({"name": "Heat"}, [("Aspen", "2026-12-02T20:00:00+01:00")])})],
        DAY,
    )
    later = merge_datasets(graph, first, [], date(2026, 12, 5))
    films, screenings = contents(graph, later)
    assert screenings == []
    assert [films_of_name(film) for film in films.values()] == ["heat"]


def films_of_name(film):
    return next(item["value"] for item in film["identifier"] if item["propertyID"] == FILM)


def test_slugs_are_stable_and_never_reassigned(graph):
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


def test_joined_films_keep_the_oldest_slug_and_alias_the_other(graph):
    rio = parsed(graph, "a", ["Bio Rio"], {"1": ({"name": "Heat", "url": "https://x/heat"}, [])})
    aspen = parsed(graph, "b", ["Aspen"], {"2": ({"name": "Heat (1995)", "url": "https://y/heat"}, [])})
    first = merge_datasets(graph, None, [rio], DAY)
    second = merge_datasets(graph, first, [aspen], date(2026, 12, 2))
    # A shared identity link now proves both records are one film.
    aspen = parsed(
        graph, "b", ["Aspen"], {"2": ({"name": "Heat", "url": "https://y/heat", "sameAs": "https://x/heat"}, [])}
    )
    third = merge_datasets(graph, second, [aspen], date(2026, 12, 3))

    (film,) = contents(graph, third)[0].values()
    assert [(item["propertyID"], item["value"]) for item in film["identifier"]] == [
        (FILM, "heat"),
        ("allabiografer:film-alias", "heat-1995"),
    ]
