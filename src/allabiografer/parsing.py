"""Turn one adapter's fetch Dataset into Movie entities and, per registry DataFeed, a Dataset of its screenings."""

import tempfile
from datetime import date
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from allabiografer.model.version import formats

from .graph import fragment
from .movie_fields import normalise
from .schedule import PREFIX

if TYPE_CHECKING:
    from allabiografer.model.version import ContentVersion, Presentation

    from .graph import Graph


def video_format(presentation: Presentation) -> list[str]:
    """Schema.org has no audio format on a screening: sound formats join the video ones."""
    return [str(value) for value in formats(presentation)]


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
    paths = [graph.resolve(captured, reference) for reference in dataset["distribution"]]
    graph.prefetch(paths)
    entities = {path: graph.read(path) for path in paths}
    graph.prefetch_content(list(entities.values()))
    for path, entity in entities.items():
        downloads[entity["name"]] = path
    feeds = {}
    for reference in dataset["about"]:
        path = graph.resolve(captured, reference)
        feed = graph.read(path)
        identifier = feed["identifier"]
        if identifier["propertyID"] != PREFIX + adapter:
            raise ValueError(f"{captured}: {identifier['propertyID']} is not {adapter}")
        feeds[identifier.get("value")] = (path, feed, graph.resolve(path, feed["about"]))
    today = date.fromisoformat(dataset["temporalCoverage"])
    rows = import_module(f".sources.{adapter}.parse", __package__).rows
    movies: dict[str, dict] = {}
    screenings: dict[Path, dict[str, dict]] = {path: {} for path, _, _ in feeds.values()}
    with tempfile.TemporaryDirectory() as scratch:
        inputs = Path(scratch)
        for name, path in downloads.items():
            (inputs / name).write_bytes(graph.content(graph.read(path)))
        for venue, show_id, start, ticket, version, presentation, movie_id, capture, movie in rows(inputs, today):
            # Adapters may yield programmes of venues outside the selection: shared feeds, old captures.
            if venue[0] not in feeds:
                continue
            feed_path, feed, cinema = feeds[venue[0]]
            if movie_id not in movies:
                movie = normalise(movie)
                if isinstance(image := movie.get("image"), str) and image in downloads:
                    movie["image"] = graph.ref(downloads[image])
                movies[movie_id] = {
                    "@id": "#" + fragment("movie", movie_id),
                    "@type": "Movie",
                    "identifier": {"@type": "PropertyValue", "propertyID": PREFIX + adapter, "value": movie_id},
                    **movie,
                    "isBasedOn": graph.ref(downloads[capture]),
                }
            screening = {
                "@type": "ScreeningEvent",
                "identifier": {"@type": "PropertyValue", "propertyID": PREFIX + adapter, "value": show_id},
                "name": movie["name"],
                "startDate": start.isoformat(),
                "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                "workPresented": {"@id": movies[movie_id]["@id"]},
                "location": graph.ref(cinema),
                "offers": {"@type": "Offer", "url": ticket},
                **screening_fields(version, presentation),
                # Programmes published by someone other than the cinema name their organiser.
                **({"organizer": feed["publisher"]} if "publisher" in feed else {}),
            }
            key = fragment("screening", screening)
            screenings[feed_path][key] = {"@id": f"#{key}", **screening}
    # One snapshot per registry feed, empty ones included: an empty programme replaces the previous one.
    snapshots = [
        {
            "@id": "#" + fragment("feed", feed["name"], str(path)),
            "@type": "Dataset",
            "name": feed["name"],
            "isBasedOn": graph.ref(path),
            "about": graph.ref(cinema),
            "temporalCoverage": dataset["temporalCoverage"],
            "hasPart": [screenings[path][key] for key in sorted(screenings[path])],
        }
        for path, feed, cinema in sorted(feeds.values(), key=lambda item: str(item[0]))
    ]
    return graph.put_dataset(
        {
            "name": f"{adapter} screenings",
            "temporalCoverage": dataset["temporalCoverage"],
            "isBasedOn": graph.ref(captured),
            "about": dataset["about"],
        },
        [movies[key] for key in sorted(movies)] + snapshots,
    )
