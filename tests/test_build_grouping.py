from datetime import date, time

import build
from build import SiteData
from store import Movie, Screening
from store.version import (
    Accessibility,
    AccessibilityFeature,
    AudioKind,
    AudioVersion,
    AuditoriumAttribute,
    ContentVersion,
    Dimension,
    Language,
    Presentation,
    PresentationSystem,
    ProjectionAttribute,
    ProjectionMedium,
    SoundAttribute,
    SubtitleVersion,
)


def screening(index, *, start=None, audio=None, subtitles=None, presentation=None, accessibility=None):
    return Screening(
        tmdb_id=42,
        date=date(2030, 1, 1),
        time=start or time(18, index),
        ticket_url=f"https://example.com/{index}",
        cinema_name="Bio",
        city="Stockholm",
        version=ContentVersion(
            audio=audio or AudioVersion(),
            subtitles=SubtitleVersion(subtitles),
        ),
        presentation=presentation or Presentation(),
        accessibility=accessibility or Accessibility(),
    )


def blocks(monkeypatch, screenings):
    monkeypatch.setattr(build, "_poster_url", lambda *_: None)
    sd = SiteData(
        screenings=screenings,
        movies={42: Movie.from_dict({"tmdb_id": 42, "title_sv": "Filmen"})},
        city_slugs={"Stockholm": "stockholm"},
        cinema_slugs={("Stockholm", "Bio"): "bio"},
    )
    return build._prepare_programme_blocks(sd, screenings, [date(2030, 1, 1)], city="Stockholm")


def test_each_modifier_defines_a_variant_and_is_labelled(monkeypatch):
    screenings = [
        screening(0),
        screening(1, presentation=Presentation(sound=frozenset({SoundAttribute.DOLBY_ATMOS}))),
        screening(2, presentation=Presentation(auditorium=frozenset({AuditoriumAttribute.VIP}))),
        screening(3, presentation=Presentation(auditorium=frozenset({AuditoriumAttribute.XL}))),
        screening(4, presentation=Presentation(projection=frozenset({ProjectionAttribute.LASER}))),
        screening(5, presentation=Presentation(projection=frozenset({ProjectionAttribute.K4}))),
        screening(6, accessibility=Accessibility(frozenset({AccessibilityFeature.AUDIO_DESCRIPTION}))),
        screening(
            7,
            presentation=Presentation(
                projection=frozenset({ProjectionAttribute.LASER, ProjectionAttribute.K4}),
                sound=frozenset({SoundAttribute.DOLBY_ATMOS}),
                auditorium=frozenset({AuditoriumAttribute.VIP, AuditoriumAttribute.XL}),
            ),
            accessibility=Accessibility(frozenset({AccessibilityFeature.AUDIO_DESCRIPTION})),
        ),
    ]
    result = blocks(monkeypatch, screenings)

    assert len(result) == 8
    labels_by_url = {
        showtime["url"]: block["variant"] for block in result for showtime in block["cinemas"][0]["cells"][0]["times"]
    }
    assert labels_by_url == {
        "https://example.com/0": "",
        "https://example.com/1": "Dolby Atmos",
        "https://example.com/2": "VIP",
        "https://example.com/3": "XL",
        "https://example.com/4": "Laser",
        "https://example.com/5": "4K",
        "https://example.com/6": "Syntolkning",
        "https://example.com/7": "4K, Laser · Dolby Atmos · VIP, XL · Syntolkning",
    }


def test_screenings_with_the_same_modifier_group_together(monkeypatch):
    laser = Presentation(projection=frozenset({ProjectionAttribute.LASER}))
    result = blocks(monkeypatch, [screening(0, presentation=laser), screening(1, presentation=laser)])
    assert len(result) == 1
    assert result[0]["variant"] == "Laser"
    assert len(result[0]["cinemas"][0]["cells"][0]["times"]) == 2


def test_variant_sorting_ignores_showing_frequency_and_start_time(monkeypatch):
    screenings = [
        screening(0, start=time(23, 0)),
        screening(1, start=time(18, 0), presentation=Presentation(experiences=frozenset({PresentationSystem.IMAX}))),
        *(
            screening(
                i + 2, start=time(18, i), presentation=Presentation(sound=frozenset({SoundAttribute.DOLBY_ATMOS}))
            )
            for i in range(4)
        ),
        *(
            screening(
                i + 6, start=time(19, i), presentation=Presentation(projection=frozenset({ProjectionAttribute.LASER}))
            )
            for i in range(3)
        ),
        *(
            screening(
                i + 9,
                start=time(20, i),
                accessibility=Accessibility(frozenset({AccessibilityFeature.AUDIO_DESCRIPTION})),
            )
            for i in range(5)
        ),
    ]

    def labels(items):
        return [block["variant"] for block in blocks(monkeypatch, items)]

    expected = ["", "Dolby Atmos", "IMAX", "Laser", "Syntolkning"]
    assert labels(screenings) == expected
    assert labels(list(reversed(screenings))) == expected


def test_experience_medium_and_dimension_make_variant_blocks(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0),
            screening(
                1,
                presentation=Presentation(
                    experiences=frozenset({PresentationSystem.IMAX}), projection=frozenset({ProjectionAttribute.LASER})
                ),
            ),
            screening(
                2,
                presentation=Presentation(
                    medium=ProjectionMedium.MM_70, auditorium=frozenset({AuditoriumAttribute.XL})
                ),
            ),
            screening(3, presentation=Presentation(dimension=Dimension.THREE_D)),
        ],
    )
    assert {block["variant"] for block in result} == {"", "IMAX · Laser", "70 mm · XL", "3D"}
    assert len(result) == 4


def test_dubbed_and_original_versions_get_clear_labels(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0, audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
            screening(1, audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH}))),
        ],
    )
    assert {block["variant"] for block in result} == {"Svenskt tal", "Originalversion · Engelskt tal"}


def test_unknown_audio_labels_only_the_known_speech_language(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0, audio=AudioVersion(languages=frozenset({Language.SWEDISH}))),
            screening(1, audio=AudioVersion(languages=frozenset({Language.ENGLISH}))),
        ],
    )
    assert {block["variant"] for block in result} == {"Svenskt tal", "Engelskt tal"}


def test_digital_metadata_does_not_add_a_label_to_audio_variants(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0, audio=AudioVersion(languages=frozenset({Language.SWEDISH}))),
            screening(
                1,
                audio=AudioVersion(languages=frozenset({Language.ENGLISH})),
                presentation=Presentation(medium=ProjectionMedium.DIGITAL),
            ),
        ],
    )
    assert {block["variant"] for block in result} == {"Svenskt tal", "Engelskt tal"}


def test_original_and_dubbed_same_language_keep_unknown_choice_separate(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0, audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.SWEDISH}))),
            screening(1, audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
            screening(2, audio=AudioVersion(languages=frozenset({Language.SWEDISH}))),
        ],
    )
    assert {block["variant"] for block in result} == {
        "Originalversion",
        "Svenskt tal",
        "Svenskt tal (typ okänd)",
    }


def test_unknown_subtitles_join_one_unambiguous_variant(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0, audio=AudioVersion(AudioKind.ORIGINAL), subtitles=frozenset({Language.SWEDISH})),
            screening(1, audio=AudioVersion(AudioKind.ORIGINAL)),
        ],
    )
    assert len(result) == 1


def test_complementary_partial_content_facts_merge(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0, audio=AudioVersion(AudioKind.ORIGINAL)),
            screening(1, subtitles=frozenset({Language.SWEDISH})),
        ],
    )
    assert len(result) == 1


def test_partial_fact_does_not_bridge_conflicting_subtitle_variants(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0, audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
            screening(1, subtitles=frozenset({Language.SWEDISH})),
            screening(2, subtitles=frozenset({Language.ENGLISH})),
        ],
    )
    assert len(result) == 3


def test_unknown_audio_stays_separate_from_ambiguous_known_versions(monkeypatch):
    screenings = [
        screening(0, audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH}))),
        screening(1, audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH}))),
        screening(2),
    ]
    result = blocks(monkeypatch, screenings)
    assert len(result) == 3
    assert len({id(s) for s in screenings}) == 3


def test_ambiguous_unknown_grouping_is_permutation_invariant(monkeypatch):
    known_dub = screening(0, audio=AudioVersion(AudioKind.DUBBED, frozenset({Language.SWEDISH})))
    known_original = screening(1, audio=AudioVersion(AudioKind.ORIGINAL, frozenset({Language.ENGLISH})))
    unknown = screening(2)

    def assignment(items):
        return {
            show["url"]: block["variant"]
            for block in blocks(monkeypatch, items)
            for cell in block["cinemas"][0]["cells"]
            for show in cell["times"]
        }

    assert assignment([known_dub, known_original, unknown]) == assignment([unknown, known_original, known_dub])


def test_unknown_and_explicitly_empty_subtitles_remain_distinct(monkeypatch):
    unknown = screening(0)
    no_subtitles = screening(1, subtitles=frozenset())
    assert unknown.version.subtitles.languages is None
    assert no_subtitles.version.subtitles.languages == frozenset()


def test_unknown_projection_joins_digital_without_defaulting_to_it(monkeypatch):
    result = blocks(
        monkeypatch,
        [
            screening(0),
            screening(1, presentation=Presentation(medium=ProjectionMedium.DIGITAL)),
        ],
    )
    assert len(result) == 1
    assert result[0]["variant"] == ""


def test_unknown_dimension_joins_2d_but_stays_separate_from_3d(monkeypatch):
    unknown_and_2d = blocks(
        monkeypatch,
        [screening(0), screening(1, presentation=Presentation(dimension=Dimension.TWO_D))],
    )
    unknown_and_3d = blocks(
        monkeypatch,
        [screening(0), screening(1, presentation=Presentation(dimension=Dimension.THREE_D))],
    )
    assert len(unknown_and_2d) == 1
    assert {block["variant"] for block in unknown_and_3d} == {"", "3D"}


def test_unknown_dimension_stays_separate_from_3d_with_imax_and_digital(monkeypatch):
    shared = {
        "experiences": frozenset({PresentationSystem.IMAX}),
        "medium": ProjectionMedium.DIGITAL,
    }
    result = blocks(
        monkeypatch,
        [
            screening(0, presentation=Presentation(**shared)),
            screening(1, presentation=Presentation(**shared, dimension=Dimension.THREE_D)),
        ],
    )
    assert {block["variant"] for block in result} == {"IMAX", "IMAX · 3D"}


def test_standalone_special_presentations_are_labelled(monkeypatch):
    presentations = [
        (Presentation(experiences=frozenset({PresentationSystem.IMAX})), "IMAX"),
        (Presentation(medium=ProjectionMedium.MM_70), "70 mm"),
        (Presentation(dimension=Dimension.THREE_D), "3D"),
    ]
    for i, (presentation, expected) in enumerate(presentations):
        result = blocks(monkeypatch, [screening(i, presentation=presentation)])
        assert result[0]["variant"] == expected


def test_dense_times_get_non_overlapping_slots():
    positions = build._compute_time_positions(
        [
            (time(18, 0), "a"),
            (time(18, 5), "b"),
            (time(18, 15), "c"),
            (time(21, 0), "d"),
        ]
    )
    for index, left in enumerate(positions):
        for right in positions[index + 1 :]:
            overlap_x = left["left"] < right["left"] + 45 and right["left"] < left["left"] + 45
            overlap_y = left["top"] < right["top"] + 28 and right["top"] < left["top"] + 28
            assert not (overlap_x and overlap_y)
