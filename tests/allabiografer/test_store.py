import json
from datetime import date

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


def test_a_bucket_store_runs_merge_and_prune_without_local_objects(tmp_path, parsed):
    import shutil

    import boto3
    from moto import mock_aws

    from allabiografer.graph import DATA
    from allabiografer.store import BucketStore

    for kind in ("MovieTheater", "City", "DataFeed"):
        shutil.copytree(DATA / "schema" / kind, tmp_path / "schema" / kind)
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="store")
        graph = Graph(tmp_path, BucketStore(client, "store", cache=tmp_path / ".cache"))
        listed = {"a": ({"name": "Dune"}, [("Bio Rio", "2026-12-02T18:00:00+01:00")])}
        merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], listed)], DAY)
        graph.save(
            "UpdateAction",
            "run",
            {
                "startTime": "2026-12-01T00:00:00+00:00",
                "endTime": "2026-12-01T00:00:00+00:00",
                "actionStatus": "https://schema.org/CompletedActionStatus",
                "result": graph.ref(merged),
            },
        )
        stray = graph.put_bytes(b"left behind" * 100, "text/plain", name="stray")
        graph.store.flush()

        keys = {item["Key"] for item in client.list_objects_v2(Bucket="store")["Contents"]}
        assert {key.split("/")[0] for key in keys} == {"schema", "assets"}
        # Generated objects live only in the bucket; the registry only in the checkout.
        assert not (tmp_path / "assets").exists()
        assert not any(key.startswith("schema/MovieTheater/") for key in keys)
        # A fresh graph on the same bucket reads the run back.
        again = Graph(tmp_path, BucketStore(client, "store"))
        assert sorted(part["@type"] for part in again.parts(merged).values()) == ["Movie", "ScreeningEvent"]

        assert prune(again, keep=1) == (1, 1)
        assert not again.exists(stray)
        assert again.exists(merged)


def test_mirroring_copies_new_objects_deletes_stale_ones_and_refuses_an_empty_source(tmp_path):
    import pytest

    from allabiografer.store import LocalStore
    from allabiografer.sync import mirror

    source, target = LocalStore(tmp_path / "a"), LocalStore(tmp_path / "b")
    run = b'{"actionStatus": "https://schema.org/CompletedActionStatus"}'
    with pytest.raises(SystemExit):
        mirror(source, target)
    source.put("schema/UpdateAction/run.jsonld", run)
    source.put("assets/new", b"new")
    target.put("assets/old", b"old")
    target.put("schema/City/Göteborg.jsonld", b"{}")

    assert mirror(source, target) == (2, 1)
    assert target.get("assets/new") == b"new"
    assert not target.exists("assets/old")
    # The registry is never mirrored, nor deleted.
    assert target.exists("schema/City/Göteborg.jsonld")


def test_pruning_keeps_the_sources_of_past_screenings(graph, parsed):
    def run(result, name, end):
        graph.save(
            "UpdateAction",
            name,
            {
                "startTime": end,
                "endTime": end,
                "actionStatus": "https://schema.org/CompletedActionStatus",
                "result": graph.ref(result),
            },
        )

    listed = {"a": ({"name": "Dune"}, [("Bio Rio", "2026-12-01T18:00:00+01:00")])}
    first_parse = parsed(graph, "x", ["Bio Rio"], listed)
    first = merge_datasets(graph, None, [first_parse], DAY)
    run(first, "first", "2026-12-01T00:00:00+00:00")
    later = merge_datasets(
        graph, first, [parsed(graph, "x", ["Bio Rio"], {}, day=date(2026, 12, 5))], date(2026, 12, 5)
    )
    run(later, "later", "2026-12-05T00:00:00+00:00")

    prune(graph, keep=1)

    (past,) = [part for part in graph.parts(later).values() if part["@type"] == "ScreeningEvent"]
    dataset, source = graph.find(later, past["isBasedOn"])
    assert dataset == first_parse
    assert source["startDate"] == past["startDate"]


def test_pruning_keeps_the_newest_render_of_the_kept_result(tmp_path):
    graph = Graph(tmp_path)
    dataset = graph.put_dataset({"name": "result"}, [])
    done = {"actionStatus": "https://schema.org/CompletedActionStatus"}
    graph.save("UpdateAction", "run", {"startTime": "1", "endTime": "2", "result": graph.ref(dataset), **done})
    website = {"@type": "WebSite", "url": "https://allabiografer.se"}
    for name, start in (("old", "3"), ("new", "4")):
        graph.save("CreateAction", name, {"startTime": start, "object": graph.ref(dataset), "result": website, **done})

    prune(graph, keep=1)

    assert graph.exists(graph.path("CreateAction", "new"))
    assert not graph.exists(graph.path("CreateAction", "old"))


def test_credentials_alone_never_select_production(tmp_path, monkeypatch):
    from allabiografer.pipeline import open_store
    from allabiografer.store import LocalStore

    monkeypatch.setenv("R2_BUCKET", "store")
    assert isinstance(open_store(tmp_path), LocalStore)


def test_pruning_keeps_older_runs_while_they_fit_and_never_a_run_in_progress(tmp_path):
    graph = Graph(tmp_path)
    done = {"actionStatus": "https://schema.org/CompletedActionStatus"}

    def run(name, start, status=done):
        data = graph.put_bytes(name.encode() * 1000, "text/plain", name=name, compress=False)
        dataset = graph.put_dataset({"name": name}, [{"@id": "#a", "@type": "Movie", "isBasedOn": graph.ref(data)}])
        graph.save("CreateAction", f"{name}-step", {"startTime": start, "result": graph.ref(dataset), **done})
        graph.save("UpdateAction", name, {"startTime": start, "endTime": start, "result": graph.ref(dataset), **status})
        return data

    before = set(graph.store.list(""))
    oldest = run("oldest", "1")
    one_run = sum(graph.store.size(key) for key in set(graph.store.list("")) - before)
    older, newest = run("older", "2"), run("newest", "3")
    going = run("going", "4", {"actionStatus": "https://schema.org/ActiveActionStatus"})

    # Room for two runs and a half: the newest two stay whole, the third goes whole.
    prune(graph, budget=int(2.5 * one_run))

    assert graph.exists(newest)
    assert graph.exists(older)
    assert not graph.exists(oldest)
    assert not graph.exists(graph.path("UpdateAction", "oldest"))
    assert graph.exists(going)
    assert graph.exists(graph.path("CreateAction", "going-step"))
