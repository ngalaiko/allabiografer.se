import io
from datetime import date

from PIL import Image

from allabiografer.graph import DATA
from allabiografer.merge import merge_datasets
from allabiografer.render import render

DAY = date(2026, 12, 1)
STATIC = DATA.parents[1] / "src" / "allabiografer" / "site" / "static" / "i"
ENGLISH = {"inLanguage": ["en"], "subtitleLanguage": ["sv"]}


def test_render_writes_pages_from_the_merged_dataset(graph, parsed, tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (1000, 1500), "teal").save(buffer, "PNG")
    poster = graph.put_bytes(buffer.getvalue(), "image/png", name="poster.png")
    films = {
        "a": (
            {"name": "Dune", "image": graph.ref(poster), "genre": ["Drama"], "duration": "PT150M"},
            [("Bio Rio", "2026-12-02T18:00:00+01:00", ENGLISH), ("Aspen", "2026-12-03T20:00:00+01:00", ENGLISH)],
        ),
        "b": ({"name": "Gammal film"}, [("Aspen", "2026-11-20T20:00:00+01:00")]),
    }
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio", "Aspen"], films)], DAY)
    out = tmp_path / "www"

    render(graph, merged, out, today=DAY)

    # The styles and scripts are published unchanged.
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
    # Resized posters are files in the site; the store keeps only the original.
    posters = sorted((out / "posters").iterdir())
    assert len(posters) == 4
    assert not any(poster.is_symlink() for poster in posters)
    # Poster, the films' pages and two dataset documents.
    assert len(list((tmp_path / "assets").iterdir())) == 5
    with Image.open(next(link for link in posters if "-" not in link.stem)) as image:
        assert (image.format, image.size) == ("WEBP", (250, 354))


def test_banners_and_placeholders_are_no_posters(graph):
    from allabiografer.posters import poster as _poster

    def stored(size):
        buffer = io.BytesIO()
        Image.new("RGB", size, "gray").save(buffer, "PNG")
        return graph.ref(graph.put_bytes(buffer.getvalue(), "image/png", name="image.png"))

    film = graph.path("Movie", "x")
    assert _poster(graph, film, stored((500, 750)), None, {}) is not None
    # A 16:9 still, a square cover and a 150x90 "Bild saknas" placeholder.
    for size in ((1920, 1080), (1080, 1080), (150, 90)):
        assert _poster(graph, film, stored(size), None, {}) is None


def test_renamed_cinemas_redirect_from_their_former_pages(graph, parsed, tmp_path):
    listed = {"a": ({"name": "Dune"}, [("Göteborg Hagabion", "2026-12-02T18:00:00+01:00")])}
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Göteborg Hagabion"], listed)], DAY)
    out = tmp_path / "www"

    render(graph, merged, out, today=DAY)

    assert (out / "stad" / "göteborg" / "hagabion" / "index.html").is_file()
    redirect = (out / "stad" / "göteborg" / "göteborg-hagabion" / "index.html").read_text()
    target = "/stad/g%C3%B6teborg/hagabion/"
    assert '<meta charset="utf-8">' in redirect
    assert f'<meta http-equiv="refresh" content="0; url={target}">' in redirect
    assert f'<link rel="canonical" href="https://allabiografer.se{target}">' in redirect
    assert '<meta name="robots" content="noindex, follow">' in redirect
    assert f'<a href="{target}">allabiografer.se/stad/göteborg/hagabion/</a>' in redirect
    assert not (out / "film-redirects.map").exists()
