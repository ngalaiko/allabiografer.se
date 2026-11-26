"""Film records built from site metadata, without side effects."""

from allabiografer.model import Film, film_key
from allabiografer.rating import age_rating


def make(source: str, title: str, **fields) -> Film:
    """Build a Film keyed by source and title, with its age rating normalised."""
    title = title.strip()
    fields["age_rating"] = age_rating(fields.get("age_rating", ""))
    return Film(key=film_key(source, title), source=source, title=title, **fields)
