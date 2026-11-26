"""Merge saved source catalogues into a new on-disk JSON-LD graph."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname

from .movie_matching import groups
from .schedule import PREFIX, local_venue_id
from .schema import CATALOGUE, Catalogue, reference

TYPES = {"City", "MovieTheater", "Movie", "ScreeningEvent"}


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def rebase(value, original: Path, destination: Path, members: dict[str, Path]):
    if isinstance(value, list):
        return [rebase(item, original, destination, members) for item in value]
    if isinstance(value, dict):
        fields = {key: rebase(item, original, destination, members) for key, item in value.items() if key != "@id"}
        if "@id" in value:
            iri = value["@id"]
            target = urljoin(original.as_uri(), iri)
            if target in members:
                fields["@id"] = "" if not iri else reference(members[target], destination.parent)
            elif not urlsplit(iri).scheme:
                parts = urlsplit(target)
                path = Path(url2pathname(parts.path))
                if path.is_relative_to(original.parents[2]):
                    raise ValueError(f"Unlisted graph member {iri!r} in {original}")
                fields["@id"] = reference(path, destination.parent)
            else:
                fields["@id"] = iri
        return fields
    return value


def group_movies(graph: dict[Path, dict], originals: dict[Path, Path]) -> None:
    movies = {path.as_uri(): path for path in originals}
    slots = {key: set() for key in movies}
    screenings = []
    for path, entity in graph.items():
        if entity["@type"] != "ScreeningEvent":
            continue
        key = urljoin(path.as_uri(), entity["workPresented"]["@id"])
        cinema = urljoin(path.as_uri(), entity["location"]["@id"])
        start = datetime.fromisoformat(entity["startDate"]).astimezone(UTC).isoformat()
        slots[key].add((cinema, start))
        screenings.append((path, entity, key))

    selected = {}
    for group in groups({key: graph[path] for key, path in movies.items()}, slots):
        representative = movies[group[0]]
        for key in group:
            selected[key] = representative
        if len(group) == 1:
            continue
        movie = graph[representative]
        for key in group[1:]:
            for field, value in graph.pop(movies[key]).items():
                movie.setdefault(field, value)
        movie["isBasedOn"] = [{"@id": reference(originals[movies[key]], representative.parent)} for key in group]

    for path, entity, key in screenings:
        entity["workPresented"] = {"@id": reference(selected[key], path.parent)}


def merge(catalogues: list[Path]) -> Path:
    catalogues = sorted(path.resolve() for path in catalogues)
    if not catalogues:
        raise ValueError("Expected at least one source catalogue")
    root = None
    sources = set()
    graph = {}
    movie_originals = {}
    now = datetime.now(UTC)
    for catalogue in catalogues:
        if (
            len(catalogue.parents) < 7
            or not catalogue.match(str(CATALOGUE))
            or catalogue.parents[3].name != "sources"
            or not catalogue.parents[4].name.isdecimal()
            or catalogue.parents[5].name != "parse"
        ):
            raise ValueError(f"Expected parse/<timestamp>/sources/<source>/{CATALOGUE}: {catalogue}")
        job = catalogue.parents[2]
        if root is None:
            root = catalogue.parents[6]
            output = root / "merge" / str(int(now.timestamp()))
        elif catalogue.parents[6] != root:
            raise ValueError(f"Expected a source catalogue under {root}: {catalogue}")
        source = job.name
        if source in sources:
            raise ValueError(f"More than one input catalogue for {source}")
        sources.add(source)
        document = read(catalogue)
        members = {}
        entities = {}
        for entry in document["mainEntity"]["itemListElement"]:
            iri = entry["@id"]
            member_type, _, filename = url2pathname(iri).removeprefix("../").partition("/")
            original = job / "schema" / member_type / filename
            if (
                member_type not in TYPES
                or "/" in filename
                or original.suffix != ".jsonld"
                or iri != reference(original, catalogue.parent)
            ):
                raise ValueError(f"Invalid entity path in {catalogue}: {iri}")
            key = original.relative_to(job)
            entity = read(original)
            if entity.get("@type") != member_type or entity.get("@id") != "":
                raise ValueError(f"Unexpected entity type or ID in {original}")
            if member_type == "MovieTheater":
                identifiers = [item for item in entity.get("identifier", []) if item["propertyID"].startswith(PREFIX)]
                if identifiers:
                    if len(identifiers) != 1 or identifiers[0]["value"] != key.stem:
                        raise ValueError(f"Invalid schedule identifier in {original}")
                    adapter = identifiers[0]["propertyID"].removeprefix(PREFIX)
                    if adapter != source:
                        raise ValueError(f"Schedule adapter {adapter!r} does not match {source!r} in {original}")
                    key = key.with_name(f"{adapter}-{local_venue_id(adapter, key.stem)}.jsonld")
                else:
                    venue = local_venue_id(source, key.stem)
                    key = key.with_name(f"{source}-{venue}.jsonld")
            elif member_type in {"Movie", "ScreeningEvent"}:
                key = key.with_name(f"{source}-{key.name}")
            members[original.as_uri()] = output / key
            entities[original] = entity
        for original, entity in entities.items():
            destination = members[original.as_uri()]
            kind = destination.parent.name
            entity = rebase(entity, original, destination, members)
            if destination in graph and (kind != "City" or graph[destination] != entity):
                raise ValueError(f"Conflicting {kind} ID: {destination.stem}")
            graph[destination] = entity
            if kind == "Movie":
                movie_originals[destination] = original

    group_movies(graph, movie_originals)
    output.mkdir(parents=True)
    result = Catalogue(output)
    for path, entity in graph.items():
        result.record(path, entity)
    return result.finish(name="Merged cinema catalogue", dateCreated=now.isoformat(), based_on=catalogues)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path, nargs="+", help=f"Source {CATALOGUE} from a parse output")
    args = parser.parse_args()
    print(merge(args.catalogue).as_uri())


if __name__ == "__main__":
    main()
