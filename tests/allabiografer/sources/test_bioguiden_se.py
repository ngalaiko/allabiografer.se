import io
import shutil
from datetime import date
from pathlib import Path

from PIL import Image

from allabiografer.sources._shared import stable_key
from allabiografer.sources.bioguiden_se.parse import rows
from allabiografer.sources.bioguiden_se.site import gallery, poster

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bioguiden_se"
SANKT_JORGEN = "https://www.bioguiden.se/biografer.aspx?cityid=227&theatreid=c12ff623-32f1-41a8-9288-c215cc1de994"
PRADA = "8b4577f1-fdaf-4702-a12c-9d10c71a070d"


def test_the_poster_is_the_first_gallery_image_without_its_canvas():
    html = (FIXTURES / "film.html").read_text()
    assert gallery(html)[0] == "https://www.bioguiden.se/image.aspx?id=44b3cf4a-69d1-42b0-a50f-aebfcc796a88"

    with Image.open(io.BytesIO(poster((FIXTURES / "poster.jpg").read_bytes()))) as found:
        assert found.size == (280, 400)
    # Other gallery images are stills.
    assert poster((FIXTURES / "still.jpg").read_bytes()) is None


def test_movies_use_the_captured_poster_not_the_listing_thumbnail(tmp_path):
    shutil.copy(FIXTURES / "programme.html", tmp_path / f"programme-{stable_key(SANKT_JORGEN)}.html")
    (tmp_path / f"poster-{PRADA}.jpg").write_bytes(poster((FIXTURES / "poster.jpg").read_bytes()))

    movies = {row[8]["name"]: row[8] for row in rows(tmp_path, date(2026, 11, 26))}

    assert movies["Djävulen bär Prada 2"]["image"] == f"poster-{PRADA}.jpg"
    # The listing's 150x90 thumbnails are banners, not posters.
    assert all("image" not in movie for name, movie in movies.items() if name != "Djävulen bär Prada 2")


def test_movies_carry_the_film_pages_facts(tmp_path):
    from allabiografer.sources.bioguiden_se.site import facts

    found = facts((FIXTURES / "film.html").read_text())

    assert found == {"directors": ["Steven Spielberg"], "title_original": "E.T. the Extra-Terrestrial"}


def test_a_programme_with_nothing_selected_is_identified_by_its_address(tmp_path):
    overkalix = "https://www.bioguiden.se/biografer.aspx?cityid=91&theatreid=df7b68d4-44d9-4d99-b508-e4bf79b1444b"
    shutil.copy(FIXTURES / "unselected.html", tmp_path / f"programme-{stable_key(overkalix)}.html")

    found = list(rows(tmp_path, date(2026, 11, 26)))

    assert found
    assert {row[0][1] for row in found} == {"Överkalix Bio"}


def test_a_programme_selecting_the_previously_visited_cinema_is_identified_by_its_address(tmp_path):
    # One session fetches every programme; the dropdown can keep the previous cinema (Älvdalen).
    overkalix = "https://www.bioguiden.se/biografer.aspx?cityid=91&theatreid=df7b68d4-44d9-4d99-b508-e4bf79b1444b"
    shutil.copy(FIXTURES / "stale-selection.html", tmp_path / f"programme-{stable_key(overkalix)}.html")

    found = list(rows(tmp_path, date(2026, 11, 26)))

    assert {row[0][1] for row in found} == {"Överkalix Bio"}
