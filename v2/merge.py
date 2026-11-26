"""Combine parse Datasets into one Dataset with movies reconciled across sources."""

from datetime import UTC, datetime
from pathlib import Path

from .graph import Graph
from .movie_matching import groups


def merge_datasets(graph: Graph, parsed: list[Path]) -> Path:
    movies: dict[Path, dict] = {}
    screenings: list[tuple[Path, dict]] = []
    places: dict[str, Path] = {}
    days = []
    for dataset_path in parsed:
        dataset = graph.read(dataset_path)
        days.append(dataset["temporalCoverage"])
        for cinema in dataset["about"]:
            places.setdefault(cinema["@id"], graph.resolve(dataset_path, cinema))
        for reference in dataset["hasPart"]:
            path = graph.resolve(dataset_path, reference)
            entity = graph.read(path)
            if entity["@type"] == "Movie":
                movies[path] = entity
            elif entity["@type"] == "ScreeningEvent":
                screenings.append((path, entity))
            else:
                raise ValueError(f"Unexpected {entity['@type']} in {dataset_path}")

    # The same cinema and start time is the strongest evidence that two records are one film.
    keys = {path: path.as_uri() for path in movies}
    slots = {key: set() for key in keys.values()}
    for path, screening in screenings:
        movie = graph.resolve(path, screening["workPresented"])
        cinema = graph.resolve(path, screening["location"])
        start = datetime.fromisoformat(screening["startDate"]).astimezone(UTC).isoformat()
        slots[keys[movie]].add((str(cinema), start))
    by_key = {key: path for path, key in keys.items()}
    merged = {}
    for group in groups({key: movies[path] for path, key in keys.items()}, slots):
        members = [by_key[key] for key in group]
        if len(members) == 1:
            merged[members[0]] = members[0]
            continue
        # Prefer the first record's values; later records only fill gaps.
        fields = {}
        for member in members:
            for field, value in movies[member].items():
                if field not in {"@context", "@id", "@type", "identifier", "isBasedOn"}:
                    fields.setdefault(field, value)
        combined = graph.put(
            "Movie",
            {
                **{key: value for key, value in fields.items() if key != "image"},
                "identifier": [movies[member]["identifier"] for member in members],
                "isBasedOn": [graph.ref(member) for member in members],
                **({"image": _rebase(graph, members, movies)} if "image" in fields else {}),
            },
        )
        for member in members:
            merged[member] = combined

    parts = []
    for path, screening in screenings:
        movie = graph.resolve(path, screening["workPresented"])
        if merged[movie] != movie:
            fields = {key: value for key, value in screening.items() if key not in {"@context", "@id", "@type"}}
            path = graph.put("ScreeningEvent", fields | {"workPresented": graph.ref(merged[movie])})
        parts.append(path)
    distinct_movies = sorted(set(merged.values()), key=str)
    return graph.put(
        "Dataset",
        {
            "name": "Merged screenings",
            "temporalCoverage": min(days) if len(set(days)) == 1 else f"{min(days)}/{max(days)}",
            "isBasedOn": [graph.ref(path) for path in parsed],
            "spatialCoverage": graph.ref(graph.path("Country", "Sverige")),
            "about": [graph.ref(path) for path in sorted(set(places.values()), key=str)],
            "hasPart": [graph.ref(path) for path in distinct_movies]
            + [graph.ref(path) for path in sorted(parts, key=str)],
        },
    )


def _rebase(graph: Graph, members: list[Path], movies: dict[Path, dict]):
    """First member's image, as a link valid from any Movie entity."""
    for member in members:
        if image := movies[member].get("image"):
            return graph.ref(graph.resolve(member, image)) if isinstance(image, dict) else image
    return None
