import gzip
import json
from itertools import combinations
from pathlib import Path

from allabiografer.movie_matching import groups

FIXTURE = Path(__file__).parent / "fixtures" / "movie_matching.json.gz"


def film(name, **fields):
    record = {"name": name}
    if director := fields.pop("director", None):
        record["director"] = [{"name": director}]
    if runtime := fields.pop("runtime", None):
        record["duration"] = f"PT{runtime}M"
    if year := fields.pop("year", None):
        record["datePublished"] = str(year)
    return record | fields


def together(movies, a, b):
    return any(a in group and b in group for group in groups(movies))


def test_one_title_is_one_film_unless_its_listings_disagree():
    movies = {
        "full": film("The Winter Garden", director="Ava Berg", runtime=91, year=2026),
        "sparse": film("The Winter Garden"),
        "formatted": film("The Winter Garden (Dolby Atmos)", runtime=93),
        "labelled": film("Premiär: The Winter Garden"),
    }
    assert groups(movies) == [sorted(movies)]


def test_a_remake_with_the_same_title_is_a_different_film():
    movies = {
        "silent": film("Metropolis", director="Fritz Lang", year=1927, runtime=153),
        "anime": film("Metropolis", director="Rintaro", year=2001, runtime=108),
        "sparse": film("Metropolis", runtime=107),
    }
    assert not together(movies, "silent", "anime")
    # Only one of the two films fits the sparse listing's runtime.
    assert together(movies, "anime", "sparse")


def test_a_title_year_and_long_edition_split_works():
    movies = {
        "animated": film("Sagan om ringen (1978)", runtime=134),
        "listing": film("Sagan om ringen", runtime=134),
        "theatrical": film("Fanny och Alexander", runtime=188),
        "complete": film("Fanny och Alexander – Complete version", runtime=312),
    }
    assert together(movies, "animated", "listing")
    assert not together(movies, "theatrical", "complete")


def test_a_shared_synopsis_joins_translated_titles():
    plot = (
        "Julen 1983. Efter ännu ett våldsamt gräl avslöjar sjuårige Andrevs mamma en hemlighet för honom: "
        "hans pappa är faktiskt inte hans pappa. I stället för att bli förkrossad blir Andrev exalterad "
        "över de möjligheter detta öppnar och ger sig ut för att leta efter sin riktiga far."
    )
    movies = {
        "swedish": film("Jävla karlar", description=plot, runtime=109),
        "english": film("Bloody Men", description=plot, runtime=108),
        "other": film("Bloody Mary", description="En helt annan berättelse om något annat " * 5, runtime=108),
    }
    assert together(movies, "swedish", "english")
    assert not together(movies, "english", "other")


def test_a_truncated_title_joins_the_one_film_it_names():
    movies = {
        "full": film("Ebenezer: A Christmas Carol", director="Ti West", runtime=123),
        "short": film("Ebenezer", director="Ti West", runtime=116),
        "original": film("Mamma Mia!", runtime=109),
        "sequel": film("Mamma Mia! Here We Go Again", runtime=120),
    }
    assert together(movies, "full", "short")
    assert not together(movies, "original", "sequel")


def test_reviewed_pairs_from_captured_listings():
    fixture = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    found = {frozenset(pair) for group in groups(fixture["movies"]) for pair in combinations(group, 2)}
    same = {frozenset(pair) for pair in fixture["same"]}
    different = {frozenset(pair) for pair in fixture["different"]}
    assert len(same & found) >= 0.95 * len(same)
    assert not different & found
