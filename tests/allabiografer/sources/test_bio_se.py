import json
from datetime import date

from allabiografer.sources.bio_se.parse import rows

MOVIE = {
    "id": 43279,
    "title": "Arne Goes to Space",
    "poster_url": "https://example.org/arne.jpg",
    "genre": "Drama,Komedi,Film",
    "language": "Svenska",
    "rating": "Från 7 år",
    "run_time": "102",
    "trailer_urls": ["https://youtu.be/IS2lhxTgteI"],
    "synopsis": "Arne åker till rymden.",
}
SESSION = {
    "show_date_time": "2026-11-26T18:30:00",
    "payment_link": "/bokning/cinemaId/16484/sessionId/1581",
    "screen_name": "Medborgarhuset",
    "format": "2D Digital",
    "language": "Svenska",
    "text": "Svenska",
}


def test_movie_carries_every_field_the_listing_states(tmp_path):
    cinema = {
        "id": 16484,
        "title": "Ale Medborgarhusets Bio",
        "slug": "x",
        "city": "Alafors",
        "street_address": "Ledetvägen 6",
    }
    (tmp_path / "cinemas.json").write_text(json.dumps({"cinemas": [cinema]}))
    (tmp_path / "programme-16484.json").write_text(json.dumps({"movies": [{"movie": MOVIE, "sessions": [SESSION]}]}))

    (row,) = rows(tmp_path, date(2026, 11, 26))

    assert row[8] == {
        "name": "Arne Goes to Space",
        "url": "https://bio.se/movie/43279",
        "description": "Arne åker till rymden.",
        "duration": "PT102M",
        "genre": ["Drama", "Komedi"],
        "contentRating": "Från 7 år",
        "image": "https://example.org/arne.jpg",
        "inLanguage": ["sv"],
        "trailer": [{"@type": "VideoObject", "url": "https://youtu.be/IS2lhxTgteI"}],
    }
