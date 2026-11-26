"""Film posters: a stored portrait image, whatever form a source gives it in."""

import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .graph import Graph, media_type

# Height over width: one-sheets are about 1.5; a little margin keeps cropped ones.
POSTER_RATIO = 1.2
MIN_POSTER_WIDTH = 200


def portrait(graph: Graph, entity: dict) -> bool:
    """Posters are portrait and big enough to show; stills, banners and placeholders are not."""
    try:
        with Image.open(io.BytesIO(graph.content(entity))) as found:
            width, height = found.size
    except UnidentifiedImageError, OSError, ValueError:
        return False
    return height >= width * POSTER_RATIO and width >= MIN_POSTER_WIDTH


def poster(graph: Graph, film_path: Path, image, session, downloaded: dict[str, Path]) -> dict | None:
    """The film's stored poster: a captured image, or a URL downloaded into the store once."""
    if isinstance(image, dict):
        entity = graph.read(graph.resolve(film_path, image))
        return entity if portrait(graph, entity) else None
    if not isinstance(image, str) or not image.startswith(("http://", "https://")):
        return None
    if image not in downloaded:
        try:
            response = session.get(image, timeout=30)
            response.raise_for_status()
        except Exception:
            return None
        media = media_type(image, response.headers.get("Content-Type", ""))
        if not media.startswith("image/"):
            return None
        downloaded[image] = graph.put_bytes(response.content, media, name=Path(image).name, url=image)
    entity = graph.read(downloaded[image])
    return entity if portrait(graph, entity) else None


def stored_downloads(graph: Graph) -> dict[str, Path]:
    """Images already downloaded, by source URL; their bytes are fetched in one batch."""
    found, entities = {}, []
    for path in graph.entities("ImageObject"):
        entity = graph.read(path)
        entities.append(entity)
        url = entity.get("isBasedOn")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            found[url] = path
    graph.prefetch_content(entities)
    return found
