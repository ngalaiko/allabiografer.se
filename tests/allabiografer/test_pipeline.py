import json
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from allabiografer import pipeline
from allabiografer.graph import Graph
from allabiografer.model import AudioFormat, Presentation, VideoFormat
from allabiografer.model.version import AudioVersion, ContentVersion, Language, SubtitleVersion
from allabiografer.parsing import screening_fields
from allabiografer.schedule import feeds


def test_assets_are_compressed_when_worthwhile_and_addressed_by_ni(tmp_path):
    graph = Graph(tmp_path)
    page = graph.read(graph.put_bytes(b"<p>bio</p>" * 200, "text/html", name="page.html", url="https://example.org"))
    image = graph.read(graph.put_bytes(bytes(range(256)), "image/jpeg", name="poster.jpg"))

    assert page["@type"] == "DataDownload"
    assert page["encodingFormat"] == "text/html+zstd"
    assert page["contentUrl"].startswith("ni:///sha-256;")
    assert (tmp_path / "assets" / page["sha256"]).stat().st_size == int(page["contentSize"])
    assert graph.content(page) == b"<p>bio</p>" * 200
    assert image["@type"] == "ImageObject"
    assert image["encodingFormat"] == "image/jpeg"
    assert graph.content(image) == bytes(range(256))


def test_entities_are_named_by_content(tmp_path):
    graph = Graph(tmp_path)
    first = graph.put("Thing", {"name": "x"})
    assert graph.put("Thing", {"name": "x"}) == first
    assert graph.put("Thing", {"name": "y"}) != first


def test_screening_fields_use_bcp47_tags_and_video_formats_only():
    version = ContentVersion(AudioVersion(languages=frozenset({Language.ENGLISH})), SubtitleVersion(frozenset()))
    presentation = Presentation(
        video=frozenset({VideoFormat.MM_70, VideoFormat.IMAX, VideoFormat.THREE_D}),
        audio=frozenset({AudioFormat.DOLBY_ATMOS}),
    )

    assert screening_fields(version, presentation) == {
        "inLanguage": ["en"],
        "subtitleLanguage": [],
        "videoFormat": ["3D", "IMAX", "Dolby Atmos", "70 mm"],
    }
    assert screening_fields(ContentVersion(), Presentation()) == {}


def test_screening_formats_are_read_from_labels_and_fill_unstated_aspects():
    from allabiografer.normalize import screening_facts

    found = screening_facts(format="2D 3D IMAX Laser Atmos 35mm 70 mm D-Box iSense Infinity Vision 4K XL")
    assert found["presentation"] == Presentation(
        video=frozenset(VideoFormat)
        - {VideoFormat.TWO_D, VideoFormat.MM_35, VideoFormat.DOLBY_CINEMA, VideoFormat.FOUR_DX, VideoFormat.SCREENX},
        audio=frozenset({AudioFormat.DOLBY_ATMOS}),
    )
    found = screening_facts(format="IMAX", source_texts=("ScreenX 3D Atmos",))
    assert found["presentation"] == Presentation(
        video=frozenset({VideoFormat.IMAX, VideoFormat.THREE_D}), audio=frozenset({AudioFormat.DOLBY_ATMOS})
    )


def test_run_records_actions_and_links_screenings_to_the_registry(graph, monkeypatch):
    feed = feeds(graph.root)["Ale Medborgarhusets Bio"]
    cinemas = {"cinemas": [{"id": 16484}]}
    programme = {"movies": []}

    def fetch_pages(session, inputs, today, *, selectors=None):
        assert selectors == {"16484"}
        (inputs / "programme-16484.json").write_text(json.dumps(programme))
        (inputs / "cinemas.json").write_text(json.dumps(cinemas))

    def rows(inputs, today):
        assert json.loads((inputs / "cinemas.json").read_text()) == cinemas
        version = ContentVersion(AudioVersion(languages=frozenset({Language.SWEDISH})))
        start = datetime(2026, 12, 1, 18, tzinfo=UTC)
        yield (
            ("16484",),
            "1",
            start,
            "https://bio.se",
            version,
            Presentation(),
            "m",
            "cinemas.json",
            {"name": "Film"},
            "programme-16484.json",
        )
        yield (
            ("99",),
            "2",
            start,
            "https://bio.se",
            version,
            Presentation(),
            "m",
            "cinemas.json",
            {"name": "Film"},
            "cinemas.json",
        )

    modules = {
        "fetch": SimpleNamespace(fetch_pages=fetch_pages),
        "parse": SimpleNamespace(rows=rows),
        "bio_se": SimpleNamespace(SITE="bio.se"),
    }
    monkeypatch.setattr(pipeline, "import_module", lambda name, package: modules[name.rsplit(".", 1)[1]])
    monkeypatch.setattr("allabiografer.parsing.import_module", lambda name, package: modules[name.rsplit(".", 1)[1]])
    monkeypatch.setattr(pipeline._http, "session", lambda: nullcontext(SimpleNamespace(headers={})))
    monkeypatch.setattr(pipeline, "datetime", SimpleNamespace(now=lambda tz: datetime(2026, 11, 26, tzinfo=tz)))

    monkeypatch.setenv("TMDB_ACCESS_TOKEN", "token")
    tmdb_response = SimpleNamespace(status_code=200, content=b"{}", raise_for_status=lambda: None)
    tmdb_session = SimpleNamespace(get=lambda address, headers=None, timeout=None: tmdb_response)
    monkeypatch.setattr(pipeline.tmdb, "recording", lambda graph, session: pipeline.tmdb.Answers(graph, tmdb_session))

    result, failures = pipeline.run(graph, [feed], previous=None)

    assert failures == {}
    actions = [
        graph.read(path) for kind in ("DownloadAction", "CreateAction") for path in graph.schema.glob(f"{kind}/*")
    ]
    assert sorted(action["name"] for action in actions) == [
        "Build programme",
        "Download bio.se",
        "Look up films on TMDB",
        "Read bio.se",
    ]
    assert pipeline.latest(graph) == result
    assert {action["actionStatus"] for action in actions} == {"https://schema.org/CompletedActionStatus"}
    for action_path in graph.schema.glob("*Action/*"):
        module = graph.read(graph.resolve(action_path, graph.read(action_path)["instrument"]))
        assert graph.read(graph.resolve(action_path, module["isPartOf"]))["@type"] == "SoftwareSourceCode"
    merged = graph.read(result)
    assert merged["temporalCoverage"] == date(2026, 11, 26).isoformat()
    screenings = [part for part in graph.parts(result).values() if part["@type"] == "ScreeningEvent"]
    assert len(screenings) == 1
    assert screenings[0]["inLanguage"] == ["sv"]
    assert graph.resolve(result, screenings[0]["location"]) == graph.path("MovieTheater", feed.cinema).resolve()

    # The result alone leads to each part's sources: parsed parts, then the captured files.
    def captured(origin, reference):
        dataset, part = graph.find(origin, reference)
        links = part["isBasedOn"] if isinstance(part["isBasedOn"], list) else [part["isBasedOn"]]
        return [graph.read(graph.resolve(dataset, link))["name"] for link in links]

    assert captured(result, screenings[0]["isBasedOn"]) == ["programme-16484.json"]
    (film,) = [part for part in graph.parts(result).values() if part["@type"] == "Movie"]
    records = [link for link in film["isBasedOn"] if "#" in link["@id"]]
    assert [name for link in records for name in captured(result, link)] == ["cinemas.json"]
    # The TMDB responses looked up for it.
    responses = [graph.read(graph.resolve(result, link)) for link in film["isBasedOn"] if "#" not in link["@id"]]
    assert responses
    assert all(response["isBasedOn"].startswith("https://api.themoviedb.org/3/") for response in responses)
    # The run's result is what its last step produced, and that step names every input.
    (built,) = [
        action
        for action in actions
        if action.get("result") and graph.resolve(graph.path("CreateAction", "_"), action["result"]) == result
    ]
    assert built["name"] == "Build programme"
    inputs = {graph.read(graph.resolve(graph.path("CreateAction", "_"), link))["name"] for link in built["object"]}
    assert inputs == {"bio.se listings", "TMDB answers"}


def test_source_snapshot_is_deterministic_and_restorable(tmp_path):
    import io
    import tarfile

    from allabiografer.code import ROOT, archive, source_code

    assert archive() == archive()
    graph = Graph(tmp_path)
    code = graph.read(source_code(graph))
    assert code["version"].removesuffix("-dirty").isalnum()
    snapshot = graph.read(graph.resolve(graph.path("SoftwareSourceCode", "_"), code["encoding"]))
    with tarfile.open(fileobj=io.BytesIO(graph.content(snapshot))) as tar:
        pipeline_file = tar.extractfile("src/allabiografer/pipeline.py").read()
        names = tar.getnames()
    assert pipeline_file == (ROOT / "src" / "allabiografer" / "pipeline.py").read_bytes()
    assert "uv.lock" in names
    assert "data/allabiografer/schema/MovieTheater/Bio Rio.jsonld" in names
    assert not any(name.startswith(("src/parse", "src/store", "tests")) for name in names)


def test_single_cinema_adapters_reject_other_selections():
    from allabiografer.sources._shared import single

    single(None)
    single({None})
    with pytest.raises(ValueError, match="Single-cinema"):
        single({"other"})


def test_failed_adapter_is_recorded_and_others_still_merge(graph, monkeypatch):

    def fetch(graph, adapter, group, day):
        raise ValueError("source changed")

    monkeypatch.setattr(pipeline, "fetch", fetch)
    with pytest.raises(RuntimeError, match="Every adapter failed"):
        pipeline.run(graph, [feeds(graph.root)["Ale Medborgarhusets Bio"]], previous=None)


def test_every_adapter_names_its_website():
    from allabiografer.parsing import site
    from allabiografer.schedule import feeds

    adapters = {feed.adapter for feed in feeds().values()}
    assert all(re.fullmatch(r"[a-z0-9.-]+\.[a-z]+", site(adapter)) for adapter in adapters)
