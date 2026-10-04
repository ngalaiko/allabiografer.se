"""nortic.se payload parsing."""

import json
from pathlib import Path

import pytest

from parse.parsers import nortic_se
from store import Film, Screening, Venue
from store.version import AudioKind, Dimension, Language

_FIXTURE = Path(__file__).parent / "fixtures" / "nortic_se" / "shows.json"


@pytest.fixture(autouse=True)
def _no_tmdb(monkeypatch):
    monkeypatch.setattr(nortic_se, "_tmdb", lambda title, **_: None)


@pytest.fixture
def items() -> list[Screening | Venue | Film]:
    return list(nortic_se._parse_payload(json.loads(_FIXTURE.read_text())))


def test_missing_arena_address_becomes_empty_string(items):
    venue = next(v for v in items if isinstance(v, Venue) and v.name == "Folketshus")
    assert venue.address == ""


def test_film_category_is_ingested(items):
    tellus = [s for s in items if isinstance(s, Screening) and s.cinema_name == "Biocafé Tellus"]
    assert len(tellus) == 2
    assert {s.title for s in tellus} == {"Tony"}


def test_non_film_categories_are_skipped(items):
    assert not any("Nyårskonsert" in getattr(i, "title", "") for i in items)
    assert not any(getattr(i, "name", "") == "Grand Hotell Spegelsalen" for i in items)


def test_screening_fields(items):
    s = next(s for s in items if isinstance(s, Screening) and s.title == "Biodlaren")
    assert s.city == "Askersund"
    assert (s.cinema_name, s.screen) == ("Sjöängen", "Stora salongen")
    assert s.date.isoformat() == "2026-09-29"
    assert s.time.strftime("%H:%M") == "16:30"
    assert s.ticket_url == "https://tickets.nortic.se/ticket/show/357605"
    assert s.film_key == "nortic_se:biodlaren"


def test_film_metadata(items):
    film = next(f for f in items if isinstance(f, Film) and f.title == "Tony")
    assert film.key == "nortic_se:tony"
    assert film.source == "nortic_se"
    assert film.overview.startswith("En 19-årig Anthony Bourdain reser till Provincetown")
    assert "<p>" not in film.overview
    assert film.url == "https://tickets.nortic.se/ticket/event/86718"
    # The API's images are 16:9 event banners, not posters.
    assert film.poster_url == ""


def test_short_description_is_the_overview_fallback(items):
    film = next(f for f in items if isinstance(f, Film) and f.title == "Biodlaren")
    assert film.overview == "Ett utforskande av kärleken, naturen och livets cykler."


def test_one_film_per_title_merged_across_organizers(items):
    films = [f for f in items if isinstance(f, Film) and f.title == "Biodlaren"]
    assert len(films) == 1
    # The overview comes from the first organizer's event; the second has none.
    assert films[0].overview == "Ett utforskande av kärleken, naturen och livets cykler."


def test_every_screening_carries_its_film_key(items):
    keys = {f.key for f in items if isinstance(f, Film)}
    screenings = [s for s in items if isinstance(s, Screening)]
    assert screenings
    assert all(s.film_key in keys for s in screenings)


def test_version_tags_move_from_title_to_screening():
    payload = json.loads(_FIXTURE.read_text())
    event = next(e for e in payload["events"] if e["title"] == "Tony")
    event["title"] = "Tony 3D (Eng. tal)"
    items = list(nortic_se._parse_payload(payload))
    s = next(s for s in items if isinstance(s, Screening) and s.cinema_name == "Biocafé Tellus")
    assert (s.title, s.presentation.dimension, s.version.audio.languages, s.film_key) == (
        "Tony",
        Dimension.THREE_D,
        frozenset({Language.ENGLISH}),
        "nortic_se:tony",
    )
    assert any(isinstance(f, Film) and f.title == "Tony" for f in items)


def test_languages_stated_in_the_description():
    payload = json.loads(_FIXTURE.read_text())
    event = next(e for e in payload["events"] if e["title"] == "Tony")
    event["description"] = (
        "<p>Drama.</p><p>Originalspråk: Engelskt-tal, Svensk text. Eventuellt kvarvarande biljetter</p>"
    )
    items = list(nortic_se._parse_payload(payload))
    s = next(s for s in items if isinstance(s, Screening) and s.cinema_name == "Biocafé Tellus")
    assert not s.version.audio.languages
    assert s.version.subtitles.languages == frozenset({Language.SWEDISH})
    film = next(f for f in items if isinstance(f, Film) and f.title == "Tony")
    assert film.original_languages == frozenset({Language.ENGLISH})


@pytest.fixture
def live() -> list[Screening | Venue | Film]:
    return list(nortic_se._parse_payload(json.loads((_FIXTURE.parent / "live.json").read_text())))


def _films(items) -> dict[str, Film]:
    return {f.title: f for f in items if isinstance(f, Film)}


def _screenings(items, title: str) -> list[Screening]:
    return [s for s in items if isinstance(s, Screening) and s.title == title]


def test_event_wrappers_are_stripped_from_titles(live):
    titles = set(_films(live))
    assert {
        "Kevlarsjäl",
        "Rebuilding",
        "Super Mario Galaxy",
        "Top Hat - The Musical",
        "Fjord",
        "Mördarens son",
        "Sven Klangs Kvintett",
        "Vi Lever Än",
    } <= titles
    [rebuilding, *_] = _screenings(live, "Rebuilding")
    assert "Bio Kontrast" in rebuilding.raw_attributes
    [mario] = _screenings(live, "Super Mario Galaxy")
    assert {"Bio Kontrast", "För Funkisfamiljer"} <= set(mario.raw_attributes)


def test_english_subtitles_title_suffix_sets_subtitles(live):
    fjords = _screenings(live, "Fjord")
    tellus = next(s for s in fjords if s.cinema_name == "Biocafé Tellus")
    assert tellus.version.subtitles.languages == frozenset({Language.ENGLISH})
    assert tellus.film_key == "nortic_se:fjord"
    assert "with English subtitles" in tellus.raw_attributes


def test_runtime_comes_from_the_description_not_the_slot_length(live):
    films = _films(live)
    assert films["Fjord"].runtime == 146
    assert films["Rebuilding"].runtime == 96
    assert films["Soundtrack to a Coup d\u00b4Etat"].runtime == 150
    assert films["Mördarens son"].runtime == 82
    # playTimeInMinutes is the booked slot: 100 for every Askersund family film.
    assert films["Monsterfabriken"].runtime is None


def test_labelled_metadata_in_the_description(live):
    films = _films(live)
    assert films["Kevlarsjäl"].age_rating == "Från 15 år"
    assert films["Arkipelag"].age_rating == "Från 15 år"
    assert films["Monsterfabriken"].age_rating == "Barntillåten"
    assert films["Mördarens son"].age_rating == "Från 11 år"
    assert films["Fjord"].genres == ["Drama"]
    assert films["Super Mario Galaxy"].title_original == "The Super Mario Galaxy Movie"


def test_dubbed_speech_sets_screening_audio_not_original_language(live):
    assert _films(live)["Super Mario Galaxy"].original_languages == frozenset()
    [mario] = _screenings(live, "Super Mario Galaxy")
    assert mario.version.audio.kind is AudioKind.DUBBED
    assert mario.version.audio.languages == frozenset({Language.SWEDISH})
    assert _films(live)["Rebuilding"].original_languages == frozenset({Language.ENGLISH})


def test_halls_split_into_screens(live):
    [monster] = _screenings(live, "Monsterfabriken")
    assert (monster.cinema_name, monster.screen) == ("Sjöängen", "Stora salongen")
    [kevlar] = _screenings(live, "Kevlarsjäl")
    assert (kevlar.cinema_name, kevlar.screen) == ("Bio Göta Lejon", "Götasalen")


def test_one_cinema_name_per_organizer_and_city(live):
    names = {(v.city, v.name) for v in live if isinstance(v, Venue)}
    assert {n for c, n in names if c == "Ulricehamn"} == {"Folkets Hus Ulricehamn"}
    assert {n for c, n in names if c == "Midsommarkransen"} == {"Biocafé Tellus"}
    assert len({n for c, n in names if c == "Ellös"}) == 1
    screened = {(s.city, s.cinema_name) for s in live if isinstance(s, Screening)}
    assert screened <= names


def test_opera_broadcasts_are_included_and_stage_operas_skipped(live):
    titles = set(_films(live))
    assert {"Macbeth", "Così fan tutte", "Manon"} <= titles
    assert "Violetta tar bussen" not in titles


def test_stated_speech_sets_screening_audio(live):
    [rebuilding, *_] = _screenings(live, "Rebuilding")
    assert rebuilding.version.audio.languages == frozenset({Language.ENGLISH})
    assert rebuilding.version.audio.kind is AudioKind.UNKNOWN
    assert rebuilding.version.subtitles.languages == frozenset({Language.SWEDISH})


def test_genres_under_the_bio_label(live):
    assert _films(live)["Monsterfabriken"].genres == ["Animerad familjefilm"]
    payload = json.loads((_FIXTURE.parent / "live.json").read_text())
    event = next(e for e in payload["events"] if e["title"] == "Monsterfabriken")
    event["description"] = "<p>Bio: Drama, komedi, romantik Åldersgräns: Ej angivet</p>"
    assert _films(nortic_se._parse_payload(payload))["Monsterfabriken"].genres == ["Drama", "Komedi", "Romantik"]
    event["description"] = "<p>Bio: Ej angivet Åldersgräns: Ej angivet</p>"
    assert _films(nortic_se._parse_payload(payload))["Monsterfabriken"].genres == []


def _event(
    title: str,
    *,
    category: str = "Bio",
    organizer: int = 1,
    show_id: int = 1,
    description: str = "",
    start: str = "2026-12-05 18:00",
) -> dict:
    return {
        "id": show_id,
        "title": title,
        "category": category,
        "organizerId": organizer,
        "description": description,
        "link": f"https://tickets.nortic.se/ticket/event/{show_id}",
        "shows": [
            {
                "startDate": start,
                "link": f"https://tickets.nortic.se/ticket/show/{show_id}",
                "arenaName": "Bio Laxen",
                "arenaCity": "Mörrum",
            }
        ],
    }


def test_opera_composer_suffix_is_stripped():
    payload = {
        "events": [
            _event("Live på bio: Simson och Delila", category="Opera", organizer=2, show_id=1),
            _event("Simson & Delila/ Camille Saint-Saenss", category="Opera", organizer=2, show_id=2),
            _event("Manon/ Massenet", category="Opera", organizer=2, show_id=3),
            _event("Otello/Verdi", category="Opera", organizer=2, show_id=4),
            _event("Face/Off", show_id=5),
        ]
    }
    items = list(nortic_se._parse_payload(payload))
    assert set(_films(items)) == {"Simson och Delila", "Manon", "Otello", "Face/Off"}
    assert {s.film_key for s in items if isinstance(s, Screening)} == {
        "nortic_se:simson och delila",
        "nortic_se:manon",
        "nortic_se:otello",
        "nortic_se:face off",
    }


def test_season_passes_and_festival_packages_are_skipped():
    payload = {
        "events": [
            _event("Wernamo Filmstudio hösten 2026", show_id=1),
            _event("Minifilmfestival Höst 26", show_id=2),
            _event("Höstsonaten", show_id=3),
        ]
    }
    assert set(_films(nortic_se._parse_payload(payload))) == {"Höstsonaten"}


def test_broadcast_lookups_are_restricted_to_the_screening_year(monkeypatch):
    calls: dict[str, int | None] = {}
    monkeypatch.setattr(nortic_se, "_tmdb", lambda title, year=None, **_: calls.setdefault(title, year) and None)
    payload = {
        "events": [
            _event("Live på bio: Simson och Delila", category="Opera", organizer=2, show_id=1),
            _event("Opera på bio - Tosca", show_id=2),
            _event("Höstsonaten", show_id=3),
        ]
    }
    list(nortic_se._parse_payload(payload))
    assert calls == {"Simson och Delila": 2026, "Tosca": 2026, "Höstsonaten": None}


def test_english_description_labels_state_the_version():
    event = _event(
        "Doc Lounge - Mördarens son",
        description="<p>Runtime: 82 minutes Language: Swedish Subtitles: English Age rating: 11+</p>",
    )
    s = next(i for i in nortic_se._parse_payload({"events": [event]}) if isinstance(i, Screening))
    assert s.version.audio.languages == {Language.SWEDISH}
    assert s.version.subtitles.languages == {Language.ENGLISH}


def test_start_dates_with_seconds_are_read():
    items = list(nortic_se._parse_payload({"events": [_event("Höstsonaten", start="2026-12-05 18:00:00")]}))
    s = next(i for i in items if isinstance(i, Screening))
    assert (s.date.isoformat(), s.time.strftime("%H:%M")) == ("2026-12-05", "18:00")


def test_unreadable_start_dates_yield_no_venue():
    items = list(nortic_se._parse_payload({"events": [_event("Höstsonaten", start="snart")]}))
    assert not any(isinstance(i, (Venue, Screening)) for i in items)
