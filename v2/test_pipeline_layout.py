import json
from datetime import UTC, datetime
from urllib.parse import unquote

from v2.merge import merge
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

    def rows(inputs, today):
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
    merged = merge([parsed])
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
            members[path.parent.name] = path
        assert set(members) == {"City", "MovieTheater", "Movie", "ScreeningEvent"}
        movie = members["Movie"]
        screening = members["ScreeningEvent"]
        cinema = members["MovieTheater"]
        assert target(movie, read(movie)["isBasedOn"]) == capture
        assert target(screening, read(screening)["workPresented"]) == movie
        assert target(screening, read(screening)["location"]) == cinema
        assert target(cinema, read(cinema)["containedInPlace"]) == members["City"]
