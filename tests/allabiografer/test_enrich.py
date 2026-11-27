import io
import json
from datetime import date
from types import SimpleNamespace

import pytest
from PIL import Image

from allabiografer.enrich import Answers, enrich_parts, tmdb_movie, url
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


class Session:
    """TMDB answering by path, or by (path, language) when given."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def get(self, address, headers=None, timeout=None):
        self.asked.append(address)
        path = address.removeprefix("https://api.themoviedb.org/3").split("?")[0]
        language = next((p[9:] for p in address.split("?")[-1].split("&") if p.startswith("language=")), None)
        found = self.answers.get((path, language), self.answers.get(path, {"results": []}))
        return SimpleNamespace(status_code=200, content=json.dumps(found).encode(), raise_for_status=lambda: None)


def enrich(graph, parsed_dataset, answers, monkeypatch):
    """The merge of `parsed_dataset` with a TMDB capture of `answers`, and the session asked."""
    monkeypatch.setenv("TMDB_ACCESS_TOKEN", "token")
    session = Session(answers)
    found = Answers(graph, session)
    from allabiografer.merge import combine

    combined = combine(graph, None, [parsed_dataset], DAY)
    enrich_parts(graph, combined.films + combined.screenings, DAY, found)
    capture = graph.put(
        "Dataset", {"name": "TMDB answers", "distribution": [graph.ref(path) for path in dict.fromkeys(found.used)]}
    )
    return merge_datasets(graph, None, [parsed_dataset], DAY, capture), session


def portrait(graph):
    buffer = io.BytesIO()
    Image.new("RGB", (500, 750), "gray").save(buffer, "PNG")
    return graph.ref(graph.put_bytes(buffer.getvalue(), "image/png", name="poster.png"))


def films(graph, dataset):
    found = {}
    for entity in graph.parts(dataset).values():
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


def test_only_films_missing_critical_details_are_filled_and_stated_values_stay(graph, parsed, monkeypatch):
    tmdb = ["https://www.themoviedb.org/movie/1170608"]
    complete = {"image": portrait(graph), "description": "Text.", "director": ["Ava Berg"]}
    listed = {
        "a": (
            {"name": "Dune: Part Three", "duration": "PT155M", "sameAs": tmdb},
            [("Bio Rio", "2026-12-16T18:00:00+01:00")],
        ),
        "b": ({"name": "Heat", **complete}, [("Bio Rio", "2026-12-17T18:00:00+01:00")]),
    }
    source = parsed(graph, "x", ["Bio Rio"], listed)
    merged = merge_datasets(graph, None, [source], DAY)

    enriched, session = enrich(graph, source, {"/movie/1170608": DUNE}, monkeypatch)

    assert all("1170608" in request for request in session.asked)
    dune = films(graph, enriched)["Dune: Part Three"]
    assert dune["image"] == "https://image.tmdb.org/t/p/original/sv.jpg"
    assert dune["director"] == [{"@type": "Person", "name": "Denis Villeneuve"}]
    # The cinema's own runtime is kept.
    assert dune["duration"] == "PT155M"
    # The response that filled it is among its sources.
    (response,) = [link for link in dune["isBasedOn"] if "#" not in link["@id"]]
    assert graph.read(graph.resolve(enriched, response))["isBasedOn"].startswith(url("/movie/1170608", {})[:-1])
    assert films(graph, enriched)["Heat"] == films(graph, merged)["Heat"]
    # Films carry their TMDB sources; the result builds on parse Datasets only, so the next run merges onto it.
    assert graph.read(enriched)["isBasedOn"] == [graph.ref(source)]
    assert films(graph, merge_datasets(graph, enriched, [], DAY))["Dune: Part Three"]["name"] == "Dune: Part Three"
    parts = graph.parts(enriched)
    works = {parts[s["workPresented"]["@id"][1:]]["name"] for s in parts.values() if s["@type"] == "ScreeningEvent"}
    assert works == {"Dune: Part Three", "Heat"}


def test_without_tmdb_films_keep_the_answers_that_filled_them(graph, parsed, monkeypatch):
    tmdb = ["https://www.themoviedb.org/movie/1170608"]
    listed = {"a": ({"name": "Dune: Part Three", "sameAs": tmdb}, [("Bio Rio", "2026-12-16T18:00:00+01:00")])}
    source = parsed(graph, "x", ["Bio Rio"], listed)
    enriched, _ = enrich(graph, source, {"/movie/1170608": DUNE}, monkeypatch)

    # The next run cannot reach TMDB: it builds without answers.
    later = merge_datasets(graph, enriched, [source], DAY)

    assert films(graph, later)["Dune: Part Three"]["director"] == [{"@type": "Person", "name": "Denis Villeneuve"}]


def test_search_accepts_one_consistent_result_only(graph, parsed, monkeypatch):
    listed = {"a": ({"name": "Metropolis", "datePublished": "1927"}, [("Bio Rio", "2026-12-16T18:00:00+01:00")])}
    lang = {"id": 19, "title": "Metropolis", "original_title": "Metropolis", "release_date": "1927-01-10"}
    remake = {"id": 10, "title": "Metropolis", "original_title": "Metropolis", "release_date": "2001-05-26"}
    detail = DUNE | {"id": 19, "title": "Metropolis", "original_title": "Metropolis", "runtime": 153}
    answers = {
        "/search/movie": {"results": [lang, remake]},
        "/movie/19": detail | {"release_date": "1927-01-10"},
        "/movie/10": detail | {"id": 10, "release_date": "2001-05-26", "runtime": 107},
    }

    enriched, _ = enrich(graph, parsed(graph, "x", ["Bio Rio"], listed), answers, monkeypatch)

    assert "https://www.themoviedb.org/movie/19" in films(graph, enriched)["Metropolis"]["sameAs"]


def test_a_banner_counts_as_no_poster(graph, parsed, monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), "gray").save(buffer, "PNG")
    still = graph.ref(graph.put_bytes(buffer.getvalue(), "image/png", name="still.png"))
    tmdb = ["https://www.themoviedb.org/movie/1170608"]
    complete = {"description": "Text.", "director": ["Denis Villeneuve"], "sameAs": tmdb, "image": still}
    listed = {"a": ({"name": "Dune: Part Three", **complete}, [("Bio Rio", "2026-12-16T18:00:00+01:00")])}

    enriched, _ = enrich(graph, parsed(graph, "x", ["Bio Rio"], listed), {"/movie/1170608": DUNE}, monkeypatch)

    assert films(graph, enriched)["Dune: Part Three"]["image"] == "https://image.tmdb.org/t/p/original/sv.jpg"


def identify(graph, parsed, movie, results, details, languages=None):
    """The TMDB id enrichment links `movie` to, given search results and detail responses."""
    listed = {"a": (movie, [("Bio Rio", "2026-12-16T18:00:00+01:00")])}
    released = {found["id"]: found["release_date"] for found in results}
    crew = {tmdb_id: [{"job": "Director", "name": d[3]}] if d[3] else [] for tmdb_id, d in details.items()}
    answers = {"/search/movie": {"results": results}} | {
        f"/movie/{tmdb_id}": DUNE
        | {"id": tmdb_id, "title": title, "original_title": original, "runtime": runtime, "overview": ""}
        | {"release_date": released[tmdb_id], "credits": {"crew": crew[tmdb_id], "cast": []}}
        | {"original_language": (languages or {}).get(tmdb_id, "en")}
        for tmdb_id, (title, original, runtime, _) in details.items()
    }
    enriched, _ = enrich(graph, parsed(graph, "x", ["Bio Rio"], listed), answers, pytest.MonkeyPatch())
    links = next(iter(films(graph, enriched).values())).get("sameAs", [])
    found = [link.rsplit("/", 1)[1] for link in links if "themoviedb" in link]
    return int(found[0]) if found else None


def result(tmdb_id, title, year, original=None):
    return {"id": tmdb_id, "title": title, "original_title": original or title, "release_date": f"{year}-01-01"}


def test_a_unique_title_matches_unless_contradicted(graph, parsed):
    # The Death of Robin Hood: a title, nothing else.
    robin = [result(1284465, "The Death of Robin Hood", 2026), result(10786, "Robin and Marian", 1976)]
    details = {1284465: ("The Death of Robin Hood", "The Death of Robin Hood", 123, "Michael Sarnoski")}
    assert identify(graph, parsed, {"name": "The Death of Robin Hood"}, robin, details) == 1284465
    # The listing states another director.
    assert (
        identify(graph, parsed, {"name": "The Death of Robin Hood", "director": ["Ava Berg"]}, robin, details) is None
    )


def test_namesakes_split_on_what_the_listing_states(graph, parsed):
    ida = [result(209274, "Ida", 2013), result(744382, "Ida", 2018), result(1118367, "Ida", 2023)]
    details = {209274: ("Ida", "Ida", 82, None), 744382: ("Ida", "Ida", 10, None), 1118367: ("Ida", "Ida", 83, None)}
    # 80 minutes fits two features; nothing tells them apart.
    assert identify(graph, parsed, {"name": "Ida", "duration": "PT80M"}, ida, details) is None
    # Bio.se states the original language: Polish, which only Pawlikowski's Ida is in.
    spoken = {"name": "Ida", "duration": "PT80M", "inLanguage": ["pl"]}
    languages = {209274: "pl", 744382: "fr", 1118367: "fr"}
    assert identify(graph, parsed, spoken, ida, details, languages) == 209274
    assert (
        identify(graph, parsed, {"name": "Ida", "duration": "PT80M", "datePublished": "2013"}, ida, details) == 209274
    )
    rose = [result(1176962, "Rose", 2026), result(16323, "The Rose", 1979)]
    details = {1176962: ("Rose", "Rose", 94, None), 16323: ("The Rose", "The Rose", 125, None)}
    assert identify(graph, parsed, {"name": "Rose", "duration": "PT94M"}, rose, details) == 1176962


def test_titles_match_across_spellings_and_languages(graph, parsed):
    capra = [result(1585, "Livet är underbart", 1946, "It's a Wonderful Life")]
    details = {1585: ("Livet är underbart", "It's a Wonderful Life", 131, "Frank Capra")}
    # Listings type a typographic apostrophe.
    movie = {"name": "It\u2019s a Wonderful Life", "director": ["Frank Capra"]}
    assert identify(graph, parsed, movie, capra, details) == 1585


def test_a_title_alone_is_not_enough_when_namesakes_remain(graph, parsed):
    # Bio.se's Black Jack is Colin Nutley's 1990 film; TMDB has several namesakes and none share a fact.
    jacks = [result(69567, "Black Jack", 1979), result(339471, "Black Jack", 1950)]
    details = {69567: ("Black Jack", "Black Jack", 105, "Ken Loach"), 339471: ("Black Jack", "Black Jack", 90, None)}
    assert identify(graph, parsed, {"name": "Black Jack", "duration": "PT111M"}, jacks, details) is None
    # A stage recording of the same name, without runtime or plot to agree with the listing.
    boots = [result(16367, "Kinky Boots", 2005), result(1798125, "Kinky Boots", 2020)]
    details = {
        16367: ("Kinky Boots", "Kinky Boots", 107, "Julian Jarrold"),
        1798125: ("Kinky Boots", "Kinky Boots", 0, None),
    }
    assert identify(graph, parsed, {"name": "Kinky Boots", "duration": "PT135M"}, boots, details) is None


def test_a_shared_director_outweighs_runtime_and_undated_duplicates(graph, parsed):
    # Fågel Blå lists It's a Wonderful Life at 131 minutes; TMDB says 111.
    capra = [result(1585, "It's a Wonderful Life", 1946), {"id": 1258547, "title": "It's a Wonderful Life"}]
    details = {1585: ("It's a Wonderful Life", "It's a Wonderful Life", 111, "Frank Capra")}
    capra[1]["release_date"] = ""
    details[1258547] = ("It's a Wonderful Life", "It's a Wonderful Life", 0, None)
    movie = {"name": "It's a Wonderful Life", "director": ["Frank Capra"], "duration": "PT131M"}
    assert identify(graph, parsed, movie, capra, details) == 1585


def test_a_title_found_in_any_language_counts(graph, parsed, monkeypatch):
    listed = {
        "a": ({"name": "The Neverending Story", "datePublished": "1984"}, [("Bio Rio", "2026-12-16T18:00:00+01:00")])
    }
    found = {"id": 34584, "original_title": "Die unendliche Geschichte", "release_date": "1984-03-16"}
    answers = {
        # Swedish results title it in Swedish, English ones in English.
        ("/search/movie", "sv-SE"): {"results": [found | {"title": "Den oändliga historien"}]},
        ("/search/movie", "en-US"): {"results": [found | {"title": "The NeverEnding Story"}]},
        ("/movie/34584", "sv-SE"): DUNE | found | {"title": "Den oändliga historien", "runtime": 94},
    }

    enriched, _ = enrich(graph, parsed(graph, "x", ["Bio Rio"], listed), answers, monkeypatch)

    assert "https://www.themoviedb.org/movie/34584" in films(graph, enriched)["The Neverending Story"]["sameAs"]
