import json
from datetime import UTC, datetime
from urllib.parse import unquote

from v2.merge import merge
from v2.schedule import schedule_identifier
from v2.schema import Catalogue, entity_path
from v2.source._shared import catalogue_main


def read(path):
    return json.loads(path.read_bytes())


def target(origin, link):
    return (origin.parent / unquote(link["@id"])).resolve()


def test_parse_and_merge_share_schema_layout(tmp_path, monkeypatch):
    fetch = tmp_path / "fetch" / "1"
    inputs = fetch / "sources" / "example"
    inputs.mkdir(parents=True)
    capture = inputs / "rå data.json"
    capture.write_text("{}", encoding="utf-8")
    (inputs / "selection.json").write_text('[{"venue_id": "biograf"}]', encoding="utf-8")

    def rows(inputs, today):
        yield (
            ("annan-biograf", "Annan biograf", "Gatan 2", "Malmö"),
            "annan-visning",
            datetime(2026, 5, 3, 18, tzinfo=UTC),
            "https://example.org/tickets",
            [],
            [],
            "annan film",
            "rå data.json",
            {"name": "Annan film"},
        )
        yield (
            ("biograf", "Biografen", "Gatan 1", "Malmö"),
            "visning",
            datetime(2026, 5, 3, 18, tzinfo=UTC),
            "https://example.org/tickets",
            [],
            [],
            "en film",
            "rå data.json",
            {"name": "En film"},
        )

    monkeypatch.setattr("sys.argv", ["parse", str(fetch)])
    catalogue_main("example", rows)
    (parsed,) = tmp_path.glob("parse/*/sources/example/schema/Dataset/catalogue.jsonld")
    cinema = parsed.parents[1] / "MovieTheater" / "biograf.jsonld"
    assert read(cinema)["identifier"] == [
        {"@type": "PropertyValue", "propertyID": "allabiografer:schedule:example", "value": "biograf"}
    ]
    merged = merge([parsed])
    assert (merged.parents[1] / "MovieTheater" / "example-biograf.jsonld").is_file()
    assert merged.relative_to(tmp_path).parts[2:] == ("schema", "Dataset", "catalogue.jsonld")

    for catalogue, provenance in ((parsed, capture), (merged, parsed)):
        document = read(catalogue)
        assert document["@type"] == "Dataset"
        assert target(catalogue, document["isBasedOn"][0]) == provenance
        members = {}
        for item in document["mainEntity"]["itemListElement"]:
            path = target(catalogue, item)
            assert path.parent.parent == catalogue.parents[1]
            assert read(path)["@type"] == path.parent.name
            assert path.parent.name not in members
            members[path.parent.name] = path
        assert set(members) == {"City", "MovieTheater", "Movie", "ScreeningEvent"}
        movie = members["Movie"]
        screening = members["ScreeningEvent"]
        cinema = members["MovieTheater"]
        assert target(movie, read(movie)["isBasedOn"]) == capture
        assert target(screening, read(screening)["workPresented"]) == movie
        assert target(screening, read(screening)["location"]) == cinema
        assert target(cinema, read(cinema)["containedInPlace"]) == members["City"]


def test_merge_keeps_same_local_venue_id_from_two_sources(tmp_path):
    catalogues = []
    for source in ("bio_se", "other"):
        output = tmp_path / "parse" / "1" / "sources" / source
        catalogue = Catalogue(output)
        catalogue.node(
            output / entity_path("MovieTheater", "16484"),
            name=source,
            identifier=schedule_identifier(source, "16484"),
        )
        catalogues.append(catalogue.finish(name=source, based_on=[]))

    merged = merge(catalogues)
    paths = {target(merged, item) for item in read(merged)["mainEntity"]["itemListElement"]}
    assert {path.name: read(path)["name"] for path in paths} == {
        "bio_se-16484.jsonld": "bio_se",
        "other-16484.jsonld": "other",
    }
