import io
from datetime import date

from PIL import Image

from allabiografer.enrich import enrich_dataset, tmdb_movie, url
from allabiografer.merge import merge_datasets

DAY = date(2026, 12, 1)

DUNE = {
    "id": 1170608,
    "imdb_id": "tt31378509",
    "title": "Dune: Del tre",
    "original_title": "Dune: Part Three",
    "overview": "Paul Atreides möter konsekvenserna.",
    "runtime": 150,
    "release_date": "2026-12-16",
    "original_language": "en",
    "poster_path": "/en.jpg",
    "genres": [{"name": "Science Fiction"}, {"name": "Äventyr"}],
    "credits": {"crew": [{"job": "Director", "name": "Denis Villeneuve"}], "cast": [{"name": "Zendaya"}]},
    "images": {"posters": [{"iso_639_1": "en", "file_path": "/en.jpg"}, {"iso_639_1": "sv", "file_path": "/sv.jpg"}]},
    "release_dates": {"results": [{"iso_3166_1": "SE", "release_dates": [{"certification": "11"}]}]},
}


def fake(answers):
    asked = []

    def fetch(path, params):
        asked.append(url(path, params))
        return answers.get(path, {"results": []})

    return fetch, asked


def portrait(graph):
    buffer = io.BytesIO()
    Image.new("RGB", (500, 750), "gray").save(buffer, "PNG")
    return graph.ref(graph.put_bytes(buffer.getvalue(), "image/png", name="poster.png"))


def films(graph, dataset):
    found = {}
    for reference in graph.read(dataset)["hasPart"]:
        path = graph.resolve(dataset, reference)
        entity = graph.read(path)
        if entity["@type"] == "Movie":
            found[entity["name"]] = entity
    return found


def test_tmdb_details_become_a_normalised_movie():
    movie = tmdb_movie(DUNE)
    assert movie["image"] == "https://image.tmdb.org/t/p/original/sv.jpg"
    assert movie["genre"] == ["Science fiction", "Äventyr"]
    assert movie["contentRating"] == "Från 11 år"
    assert movie["sameAs"] == ["https://www.imdb.com/title/tt31378509", "https://www.themoviedb.org/movie/1170608"]
    assert movie["director"] == [{"@type": "Person", "name": "Denis Villeneuve"}]


def test_only_films_missing_critical_details_are_filled_and_stated_values_stay(graph, parsed):
    tmdb = ["https://www.themoviedb.org/movie/1170608"]
    complete = {"image": portrait(graph), "description": "Text.", "director": ["Ava Berg"]}
    listed = {
        "a": (
            {"name": "Dune: Part Three", "duration": "PT155M", "sameAs": tmdb},
            [("Bio Rio", "2026-12-16T18:00:00+01:00")],
        ),
        "b": ({"name": "Heat", **complete}, [("Bio Rio", "2026-12-17T18:00:00+01:00")]),
    }
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], listed)], DAY)
    fetch, asked = fake({"/movie/1170608": DUNE})

    enriched, count = enrich_dataset(graph, merged, fetch)

    assert count == 1
    assert all("1170608" in request for request in asked)
    dune = films(graph, enriched)["Dune: Part Three"]
    assert dune["image"] == "https://image.tmdb.org/t/p/original/sv.jpg"
    assert dune["director"] == [{"@type": "Person", "name": "Denis Villeneuve"}]
    # The cinema's own runtime is kept.
    assert dune["duration"] == "PT155M"
    assert films(graph, enriched)["Heat"] == films(graph, merged)["Heat"]
    screenings = [
        graph.read(graph.resolve(enriched, ref))
        for ref in graph.read(enriched)["hasPart"]
        if "ScreeningEvent" in ref["@id"]
    ]
    works = {
        graph.read(graph.resolve(graph.path("ScreeningEvent", "_"), s["workPresented"]))["name"] for s in screenings
    }
    assert works == {"Dune: Part Three", "Heat"}


def test_search_accepts_one_consistent_result_only(graph, parsed):
    listed = {"a": ({"name": "Metropolis", "datePublished": "1927"}, [("Bio Rio", "2026-12-16T18:00:00+01:00")])}
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], listed)], DAY)
    lang = {"id": 19, "title": "Metropolis", "original_title": "Metropolis", "release_date": "1927-01-10"}
    remake = {"id": 10, "title": "Metropolis", "original_title": "Metropolis", "release_date": "2001-05-26"}
    detail = DUNE | {"id": 19, "title": "Metropolis", "original_title": "Metropolis", "runtime": 153}
    answers = {"/search/movie": {"results": [lang, remake]}, "/movie/19": detail}

    enriched, count = enrich_dataset(graph, merged, fake(answers)[0])

    assert count == 1
    assert "https://www.themoviedb.org/movie/19" in films(graph, enriched)["Metropolis"]["sameAs"]


def test_a_banner_counts_as_no_poster(graph, parsed):
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), "gray").save(buffer, "PNG")
    still = graph.ref(graph.put_bytes(buffer.getvalue(), "image/png", name="still.png"))
    tmdb = ["https://www.themoviedb.org/movie/1170608"]
    complete = {"description": "Text.", "director": ["Denis Villeneuve"], "sameAs": tmdb, "image": still}
    listed = {"a": ({"name": "Dune: Part Three", **complete}, [("Bio Rio", "2026-12-16T18:00:00+01:00")])}
    merged = merge_datasets(graph, None, [parsed(graph, "x", ["Bio Rio"], listed)], DAY)

    enriched, count = enrich_dataset(graph, merged, fake({"/movie/1170608": DUNE})[0])

    assert count == 1
    assert films(graph, enriched)["Dune: Part Three"]["image"] == "https://image.tmdb.org/t/p/original/sv.jpg"
