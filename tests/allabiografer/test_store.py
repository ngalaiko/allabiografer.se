import json

from conftest import DAY

from allabiografer.graph import Graph
from allabiografer.merge import merge_datasets
from allabiografer.prune import prune


def test_a_dataset_keeps_its_parts_in_one_compressed_document(graph, parsed):
    listed = {"a": ({"name": "Dune"}, [("Bio Rio", "2026-12-02T18:00:00+01:00")])}
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], listed)], DAY)

    entity = graph.read(merged)
    assert "hasPart" not in entity
    document = graph.read(graph.resolve(merged, entity["distribution"]))
    assert document["encodingFormat"] == "application/ld+json+zstd"
    content = json.loads(graph.content(document))
    assert [part["@type"] for part in content["hasPart"]] == ["Movie", "ScreeningEvent"]
    # Parts link to each other by fragment, and to entities relative to the Dataset.
    film, screening = content["hasPart"]
    assert screening["workPresented"] == {"@id": film["@id"]}
    assert graph.resolve(merged, screening["location"]) == graph.path("MovieTheater", "Bio Rio").resolve()
    # Only the Dataset entity, its document and the registry are written: no file per part.
    assert not (graph.schema / "ScreeningEvent").exists()
    assert not (graph.schema / "Movie").exists()


def test_a_rerun_rewrites_only_what_changed(graph, parsed):
    listed = {"a": ({"name": "Dune"}, [("Bio Rio", "2026-12-02T18:00:00+01:00")])}
    first = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], listed)], DAY)
    before = set(graph.schema.rglob("*.jsonld")) | set(graph.assets.iterdir())
    again = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], listed)], DAY)

    assert again == first
    assert set(graph.schema.rglob("*.jsonld")) | set(graph.assets.iterdir()) == before


def test_pruning_keeps_the_latest_runs_and_what_they_reach(tmp_path):
    graph = Graph(tmp_path)
    (tmp_path / "schema" / "City").mkdir(parents=True)
    (tmp_path / "schema" / "City" / "Göteborg.jsonld").write_text("{}")

    def run(name, end):
        data = graph.put_bytes(name.encode() * 100, "text/plain", name=name)
        dataset = graph.put_dataset({"name": name}, [{"@id": "#a", "@type": "Movie", "isBasedOn": graph.ref(data)}])
        graph.save(
            "UpdateAction",
            name,
            {
                "startTime": end,
                "endTime": end,
                "actionStatus": "https://schema.org/CompletedActionStatus",
                "result": graph.ref(dataset),
            },
        )
        return dataset, data

    old, old_data = run("old", "2026-12-01T00:00:00+00:00")
    new, new_data = run("new", "2026-12-02T00:00:00+00:00")

    prune(graph, keep=1)

    assert new.exists()
    assert new_data.exists()
    assert not old.exists()
    assert not old_data.exists()
    assert len(list(graph.assets.iterdir())) == 2  # The new run's data and document.
    assert (tmp_path / "schema" / "City" / "Göteborg.jsonld").exists()
