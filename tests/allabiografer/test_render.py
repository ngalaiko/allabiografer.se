import io
import shutil
from datetime import date

from PIL import Image

from allabiografer.graph import DATA, Graph
from allabiografer.merge import merge_datasets
from allabiografer.parsing import PREFIX
from allabiografer.render import render

DAY = date(2026, 12, 1)
STATIC = DATA.parents[1] / "static" / "i"


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
                "identifier": {"propertyID": PREFIX + adapter, "value": f"{movie_id}-{start}"},
                "name": fields["name"],
                "startDate": start,
                "workPresented": graph.ref(movie),
                "location": graph.ref(graph.path("MovieTheater", cinema)),
                "offers": {"@type": "Offer", "url": "https://example.org/tickets"},
                "inLanguage": ["en"],
                "subtitleLanguage": ["sv"],
            }
            parts.append(graph.put("ScreeningEvent", screening))
    return graph.put(
        "Dataset", {"temporalCoverage": DAY.isoformat(), "about": about, "hasPart": [graph.ref(p) for p in parts]}
    )


def test_render_writes_v1_pages_from_the_merged_dataset(tmp_path):
    for kind in ("MovieTheater", "City"):
        shutil.copytree(DATA / "schema" / kind, tmp_path / "schema" / kind)
    graph = Graph(tmp_path)
    buffer = io.BytesIO()
    Image.new("RGB", (1000, 1500), "teal").save(buffer, "PNG")
    poster = graph.put_bytes(buffer.getvalue(), "image/png", name="poster.png")
    films = {
        "a": (
            {"name": "Dune", "image": graph.ref(poster), "genre": ["Drama"], "duration": "PT150M"},
            [("Bio Rio", "2026-12-02T18:00:00+01:00"), ("Aspen", "2026-12-03T20:00:00+01:00")],
        ),
        "b": ({"name": "Gammal film"}, [("Aspen", "2026-11-20T20:00:00+01:00")]),
    }
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio", "Aspen"], films)], DAY)
    out = tmp_path / "www"

    render(graph, merged, out, today=DAY)

    # v1's styles and scripts are published unchanged.
    assert (out / "i" / "style.css").read_bytes() == (STATIC / "style.css").read_bytes()
    cinema = (out / "stad" / "stockholm" / "bio-rio" / "index.html").read_text()
    assert 'class="schedule-film"' in cinema
    assert ">18:00<" in cinema
    assert "Engelskt tal • Svensk text" in cinema
    assert (out / "film" / "dune" / "index.html").is_file()
    assert (out / "stad" / "stockholm" / "genre" / "drama" / "index.html").is_file()
    # Films without upcoming screenings are not published.
    assert not (out / "film" / "gammal-film").exists()
    # No iCalendar feeds; Schema.org JSON-LD only.
    assert not list(out.rglob("*.ics"))
    assert (out / "film" / "dune" / "index.jsonld").is_file()
    # Resized posters stay in the asset store; the site links to them.
    posters = sorted((out / "posters").iterdir())
    assert len(posters) == 4
    assert all(link.is_symlink() and link.resolve().parent == (tmp_path / "assets").resolve() for link in posters)
    with Image.open(next(link for link in posters if "-" not in link.stem)) as image:
        assert (image.format, image.size) == ("WEBP", (250, 354))
