from v2.movie_matching import groups


def test_reviewed_identity_can_join_different_titles_but_not_conflicting_years():
    first = {"name": "The Winter Garden", "datePublished": "2026", "url": "https://example.com/film/1/"}
    second = {"name": "Vinterträdgården", "datePublished": "2026", "sameAs": ["https://example.com/film/1"]}
    slots = {"a": set(), "b": set()}

    assert groups({"a": first, "b": second}, slots) == [["a", "b"]]
    assert groups({"a": first, "b": {**second, "datePublished": "2001"}}, slots) == [["a"], ["b"]]


def test_matching_title_and_director_need_compatible_runtimes():
    first = {"name": "The Winter Garden", "director": [{"@type": "Person", "name": "Ava Berg"}], "duration": "PT91M"}
    second = {"name": "The Winter Garden", "director": {"@type": "Person", "name": "Ava Berg"}, "duration": "PT93M"}
    slots = {"a": set(), "b": set()}

    assert groups({"a": first, "b": second}, slots) == [["a", "b"]]
    assert groups({"a": first, "b": {**second, "duration": "PT94M"}}, slots) == [["a"], ["b"]]
    assert groups({"a": first, "b": {"name": second["name"], "duration": "PT91M"}}, slots) == [["a"], ["b"]]
