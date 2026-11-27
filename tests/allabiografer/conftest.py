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
        movie = {
            "@id": f"#movie-{movie_id}",
            "@type": "Movie",
            "identifier": {"propertyID": PREFIX + adapter, "value": movie_id},
            "isBasedOn": "x",
            **fields,
        }
        movies.append(movie)
        for feed, start, *extra in listed:
            registry = graph.read(graph.path("DataFeed", feed))
            cinema = graph.resolve(graph.path("DataFeed", feed), registry["about"])
            shows[feed].append(
                {
                    "@id": f"#screening-{movie_id}-{len(shows[feed])}-{feed}",
                    "@type": "ScreeningEvent",
                    "identifier": {"propertyID": PREFIX + adapter, "value": f"{movie_id}-{feed}-{start}"},
                    "name": fields["name"],
                    "startDate": start,
                    "workPresented": {"@id": movie["@id"]},
                    "location": graph.ref(cinema),
                    "offers": {"@type": "Offer", "url": "https://example.org/tickets"},
                    **({"organizer": registry["publisher"]} if "publisher" in registry else {}),
                    **(extra[0] if extra else {}),
                }
            )
    snapshots = []
    for feed, screenings in shows.items():
        path = graph.path("DataFeed", feed)
        snapshots.append(
            {"@id": f"#feed-{feed}", "@type": "Dataset", "isBasedOn": graph.ref(path), "hasPart": screenings}
        )
    capture = graph.put(
        "Dataset",
        {
            "name": f"{adapter} pages",
            "temporalCoverage": day.isoformat(),
            "about": [graph.ref(graph.path("DataFeed", feed)) for feed in feeds],
            "distribution": [],
        },
    )
    return graph.put_dataset({"name": f"{adapter} listings", "isBasedOn": graph.ref(capture)}, movies + snapshots)


def contents(graph, dataset):
    """A Dataset's films by fragment, and its screenings with their film's slug as `film`."""
    parts = graph.parts(dataset)
    films = {key: part for key, part in parts.items() if part["@type"] == "Movie"}
    screenings = [
        part | {"film": slug(films[part["workPresented"]["@id"][1:]])}
        for part in parts.values()
        if part["@type"] == "ScreeningEvent"
    ]
    return films, screenings


def slug(film):
    return next(item["value"] for item in film["identifier"] if item["propertyID"] == "allabiografer:film")
