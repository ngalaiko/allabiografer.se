import io
import json
import re
import shutil
from datetime import date

from PIL import Image

from allabiografer.graph import DATA, Graph
from allabiografer.merge import merge_datasets
from allabiografer.parsing import PREFIX
from allabiografer.render import render

DAY = date(2026, 12, 1)


def parsed(graph, adapter, cinemas, films):
    """A parse Dataset: `films` maps a movie ID to (fields, [(cinema, start)])."""
    about = [
        graph.ref(graph.path("MovieTheater", c)) | {"identifier": {"propertyID": PREFIX + adapter}} for c in cinemas
    ]
    parts = []
    for movie_id, (fields, shows) in films.items():
        identifier = {"propertyID": PREFIX + adapter, "value": movie_id}
        movie = graph.put("Movie", {"identifier": identifier, "isBasedOn": "x", **fields})
        parts.append(movie)
        for cinema, start in shows:
            screening = {
                "name": fields["name"],
                "startDate": start,
                "workPresented": graph.ref(movie),
                "location": graph.ref(graph.path("MovieTheater", cinema)),
                "offers": {"@type": "Offer", "url": "https://example.org/tickets"},
            }
            parts.append(graph.put("ScreeningEvent", screening))
    return graph.put(
        "Dataset", {"temporalCoverage": DAY.isoformat(), "about": about, "hasPart": [graph.ref(p) for p in parts]}
    )


def jsonld(page):
    found = re.search(r'<script type="application/ld\+json">(.*?)</script>', page.read_text(), re.DOTALL)
    return json.loads(found[1].replace("<\\/", "</"))


def test_render_writes_pages_from_the_merged_dataset(tmp_path):
    shutil.copytree(DATA / "schema" / "MovieTheater", tmp_path / "schema" / "MovieTheater")
    shutil.copytree(DATA / "schema" / "City", tmp_path / "schema" / "City")
    graph = Graph(tmp_path)
    buffer = io.BytesIO()
    Image.new("RGB", (1000, 1500), "teal").save(buffer, "PNG")
    poster = graph.put_bytes(buffer.getvalue(), "image/png", name="poster.png")
    films = {
        "a": (
            {"name": "Dune", "image": graph.ref(poster)},
            [("Bio Rio", "2026-12-02T18:00:00+01:00"), ("Aspen", "2026-12-03T20:00:00+01:00")],
        ),
        "b": ({"name": "Gammal film"}, [("Aspen", "2026-11-20T20:00:00+01:00")]),
    }
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio", "Aspen"], films)], DAY)
    out = tmp_path / "www"

    render(graph, merged, out, today=DAY)

    assert (out / "index.html").is_file()
    film = out / "film" / "dune" / "index.html"
    assert "18:00" in film.read_text()
    assert jsonld(film)["@id"] == "https://allabiografer.se/film/dune/"
    assert len(jsonld(film)["subjectOf"]) == 2
    assert (out / "stad" / "stockholm" / "bio-rio" / "index.html").is_file()
    # Past screenings and films without upcoming ones are not published.
    assert not (out / "film" / "gammal-film").exists()
    # The resized poster lives in the asset store; the site links to it.
    (link,) = (out / "assets").iterdir()
    assert link.is_symlink()
    assert link.resolve().parent == (tmp_path / "assets").resolve()
    with Image.open(link) as image:
        assert (image.format, image.width) == ("WEBP", 500)
    assert f"/assets/{link.name}" in film.read_text()
