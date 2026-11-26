import shutil
from datetime import date

import pytest

from allabiografer.graph import DATA, Graph
from allabiografer.parsing import PREFIX

DAY = date(2026, 12, 1)


@pytest.fixture
def graph(tmp_path):
    for kind in ("MovieTheater", "City", "DataFeed"):
        shutil.copytree(DATA / "schema" / kind, tmp_path / "schema" / kind)
    return Graph(tmp_path)


@pytest.fixture
def parsed():
    return parse_dataset


def parse_dataset(graph, adapter, feeds, films, *, day=DAY):
    """A parse Dataset: `films` maps a movie ID to (fields, [(feed, start)]) or (fields, [(feed, start, extra)])."""
    movies, shows = [], {feed: [] for feed in feeds}
    for movie_id, (fields, listed) in films.items():
        movie = graph.put(
            "Movie", {"identifier": {"propertyID": PREFIX + adapter, "value": movie_id}, "isBasedOn": "x", **fields}
        )
        movies.append(movie)
        for feed, start, *extra in listed:
            registry = graph.read(graph.path("DataFeed", feed))
            cinema = graph.resolve(graph.path("DataFeed", feed), registry["about"])
            screening = {
                "identifier": {"propertyID": PREFIX + adapter, "value": f"{movie_id}-{feed}-{start}"},
                "name": fields["name"],
                "startDate": start,
                "workPresented": graph.ref(movie),
                "location": graph.ref(cinema),
                "offers": {"@type": "Offer", "url": "https://example.org/tickets"},
                **({"organizer": registry["publisher"]} if "publisher" in registry else {}),
                **(extra[0] if extra else {}),
            }
            shows[feed].append(graph.put("ScreeningEvent", screening))
    snapshots = []
    for feed, screenings in shows.items():
        path = graph.path("DataFeed", feed)
        snapshots.append(
            graph.put(
                "Dataset",
                {
                    "name": feed,
                    "isBasedOn": graph.ref(path),
                    "about": graph.ref(graph.resolve(path, graph.read(path)["about"])),
                    "temporalCoverage": day.isoformat(),
                    "hasPart": [graph.ref(item) for item in screenings],
                },
            )
        )
    return graph.put(
        "Dataset",
        {
            "temporalCoverage": day.isoformat(),
            "about": [graph.ref(graph.path("DataFeed", feed)) for feed in feeds],
            "hasPart": [graph.ref(path) for path in movies + snapshots],
        },
    )
