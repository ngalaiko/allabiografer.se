"""Turn one adapter's fetch Dataset into ScreeningEvent and Movie entities."""

import tempfile
from datetime import date
from importlib import import_module
from pathlib import Path

from allabiografer.model import Dimension, Presentation, PresentationSystem, ProjectionMedium
from allabiografer.model.version import ContentVersion

from .graph import Graph
from .schedule import PREFIX

# Picture and projection formats. Sound, seating and programme labels are not video formats.
_SYSTEMS = (
    PresentationSystem.IMAX,
    PresentationSystem.DOLBY_CINEMA,
    PresentationSystem.FOUR_DX,
    PresentationSystem.SCREENX,
)
_MEDIA = (ProjectionMedium.MM_35, ProjectionMedium.MM_70)


def video_format(presentation: Presentation) -> list[str]:
    formats = []
    if presentation.dimension is not Dimension.UNKNOWN:
        formats.append(str(presentation.dimension))
    formats += [str(system) for system in _SYSTEMS if system in presentation.experiences]
    if presentation.medium in _MEDIA:
        formats.append(str(presentation.medium))
    return formats


def language_fields(version: ContentVersion) -> dict:
    """BCP 47 tags; an empty subtitle list means the source states there are none."""
    fields = {}
    if spoken := version.audio.languages:
        fields["inLanguage"] = sorted(language.tag for language in spoken)
    if (subtitles := version.subtitles.languages) is not None:
        fields["subtitleLanguage"] = sorted(language.tag for language in subtitles)
    return fields


def screening_fields(version: ContentVersion, presentation: Presentation) -> dict:
    fields = language_fields(version)
    if formats := video_format(presentation):
        fields["videoFormat"] = formats
    return fields


def parse_capture(graph: Graph, adapter: str, captured: Path) -> Path:
    dataset = graph.read(captured)
    downloads = {}
    for reference in dataset["distribution"]:
        path = graph.resolve(captured, reference)
        downloads[graph.read(path)["name"]] = path
    cinemas = {}
    for cinema in dataset["about"]:
        identifier = cinema["identifier"]
        if identifier["propertyID"] != PREFIX + adapter:
            raise ValueError(f"{captured}: {identifier['propertyID']} is not {adapter}")
        cinemas[identifier.get("value")] = graph.resolve(captured, cinema)
    today = date.fromisoformat(dataset["temporalCoverage"])
    rows = import_module(f".sources.{adapter}.parse", __package__).rows
    movies = {}
    screenings = []
    with tempfile.TemporaryDirectory() as scratch:
        inputs = Path(scratch)
        for name, path in downloads.items():
            (inputs / name).write_bytes(graph.content(graph.read(path)))
        for venue, show_id, start, ticket, version, presentation, movie_id, capture, movie in rows(inputs, today):
            # Adapters may yield programmes of venues outside the selection: shared feeds, old captures.
            cinema = cinemas.get(venue[0])
            if cinema is None:
                continue
            if movie_id not in movies:
                movie = dict(movie)
                if not movie.get("url"):
                    movie.pop("url", None)
                if isinstance(image := movie.get("image"), str) and image in downloads:
                    movie["image"] = graph.ref(downloads[image])
                movies[movie_id] = graph.put(
                    "Movie",
                    {
                        "identifier": {"@type": "PropertyValue", "propertyID": PREFIX + adapter, "value": movie_id},
                        **movie,
                        "isBasedOn": graph.ref(downloads[capture]),
                    },
                )
            screenings.append(
                graph.put(
                    "ScreeningEvent",
                    {
                        "identifier": {"@type": "PropertyValue", "propertyID": PREFIX + adapter, "value": show_id},
                        "name": movie["name"],
                        "startDate": start.isoformat(),
                        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                        "workPresented": graph.ref(movies[movie_id]),
                        "location": graph.ref(cinema),
                        "offers": {"@type": "Offer", "url": ticket},
                        **screening_fields(version, presentation),
                    },
                )
            )
    seen = set()
    unique = [path for path in screenings if not (path in seen or seen.add(path))]
    return graph.put(
        "Dataset",
        {
            "name": f"{adapter} screenings",
            "temporalCoverage": dataset["temporalCoverage"],
            "isBasedOn": graph.ref(captured),
            "about": dataset["about"],
            "hasPart": [graph.ref(path) for path in sorted(movies.values(), key=str)]
            + [graph.ref(path) for path in sorted(unique, key=str)],
        },
    )
