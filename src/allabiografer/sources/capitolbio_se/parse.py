"""Parse Capitol's saved calendar and film pages."""

import json
import re
from datetime import datetime, timedelta

from allabiografer.movie_fields import film_fields, imdb_links
from allabiografer.sources.capitolbio_se.site import _DAYS, _details, _page, _showtimes

from .._shared import STOCKHOLM, film_id


def rows(inputs, today):
    details = {}
    seen = set()
    for offset in range(_DAYS):
        day = today + timedelta(days=offset)
        for film, show in _showtimes((inputs / f"programme-{day}.html").read_text(encoding="utf-8"), day):
            if show.ticket_url in seen:
                continue
            seen.add(show.ticket_url)
            slug = film_id(film.url)
            capture = f"movie-{slug}.html"
            if slug not in details:
                html = (inputs / capture).read_text(encoding="utf-8")
                film = _details(html, film)
                credits = {"director": film.directors}
                extra = {}
                title = film.title
                for script in _page(html).select('script[type="application/ld+json"]'):
                    try:
                        data = json.loads(script.get_text())
                    except json.JSONDecodeError:
                        continue
                    for item in data.get("@graph", [data]):
                        if item.get("@type") == "Movie":
                            if title.endswith(",") and (name := item.get("name")):
                                title = re.sub(r"\s*\([^()]*(?:tal|text)\)$", "", name, flags=re.IGNORECASE)
                            for role in ("actor", "director"):
                                people = item.get(role) or []
                                if names := [
                                    p["name"]
                                    for p in (people if isinstance(people, list) else [people])
                                    if p.get("name")
                                ]:
                                    credits[role] = names
                            extra = {
                                "genre": item.get("genre") or [],
                                "languages": [item.get("inLanguage") or ""],
                                # Capitol publishes landscape stills, no posters.
                                "image": item.get("image") or "",
                            }
                details[slug] = film_fields(film, credits=credits, same_as=imdb_links(html), **extra)
                details[slug]["name"] = title
            yield (
                (None, "Capitol", "Sankt Eriksgatan 82"),
                film_id(show.ticket_url),
                datetime.combine(day, show.time, STOCKHOLM),
                show.ticket_url,
                show.version,
                show.presentation,
                slug,
                capture,
                details[slug],
                f"programme-{day}.html",
            )
