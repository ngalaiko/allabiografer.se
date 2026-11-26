from allabiografer.movie_fields import PROPERTIES, genres, normalise


def test_source_labels_map_onto_one_vocabulary():
    assert genres(["Drama, Crime", "Sci Fi", "Animerad familjefilm", "Live på bio", "Jul"]) == [
        "Drama",
        "Kriminal",
        "Science fiction",
        "Animerat",
        "Familj",
    ]
    movie = normalise(
        {
            "name": "  Dune:  Part Three ",
            "alternateName": "Dune: Part Three",
            "duration": "PT2H30M",
            "datePublished": "2026-12-16",
            "contentRating": "11 år",
            "inLanguage": ["en", "xx"],
            "director": {"@type": "Person", "name": "Denis Villeneuve"},
            "actor": ["Zendaya", "Zendaya", ""],
            "trailer": "https://youtu.be/x",
            "distributor": {"@type": "Organization", "name": "UIP"},
            "description": "",
        }
    )
    assert movie == {
        "name": "Dune: Part Three",
        "duration": "PT150M",
        "datePublished": "2026-12-16",
        "contentRating": "Från 11 år",
        "inLanguage": ["en"],
        "director": [{"@type": "Person", "name": "Denis Villeneuve"}],
        "actor": [{"@type": "Person", "name": "Zendaya"}],
        "trailer": [{"@type": "VideoObject", "url": "https://youtu.be/x"}],
    }
    assert set(movie) <= set(PROPERTIES)


def test_unrated_and_implausible_values_drop():
    assert normalise({"name": "X", "contentRating": "Ej granskad", "duration": "PT0M", "datePublished": "2026"}) == {
        "name": "X",
        "datePublished": "2026",
    }
