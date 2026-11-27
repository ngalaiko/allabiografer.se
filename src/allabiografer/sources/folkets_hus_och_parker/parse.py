"""Replay the embedded cinema programmes without enrichment or network access."""

import json
import re

from allabiografer.movie_fields import film_fields
from allabiografer.sources.folkets_hus_och_parker.site import _PRIVATE_HIRE, _SITES, _film, _start

from .._shared import STOCKHOLM, facts, stable_key


def rows(inputs, today):
    for site in _SITES:
        path = inputs / f"{site.source}.html"
        if not path.is_file():
            continue
        html = path.read_text(encoding="utf-8")
        embedded = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not embedded:
            raise ValueError(f"Missing programme in {path}")
        programme = json.loads(embedded[1])["props"]["pageProps"]["programList"]
        features = {f["id"]: f for f in programme["features"]}
        seen = set()
        for entry in programme["schedule"]:
            feature = features.get(entry.get("featureId")) or {}
            info = feature.get("info") or {}
            title = info.get("title", "").strip()
            if not title or title in {_PRIVATE_HIRE, *site.excluded_titles}:
                continue
            film = _film(feature, site=site)
            fields = film_fields(
                film,
                # Other listings for this recording disagree on its length.
                runtime=None
                if film.url.rstrip("/").endswith("/program/national-theatre-the-misanthrope")
                else film.runtime,
            )
            for show in entry.get("dates", []):
                if not show.get("startDate") or not show.get("ticksterLink"):
                    continue
                start = _start(show["startDate"]).replace(tzinfo=STOCKHOLM)
                ticket = show["ticksterLink"]
                key = stable_key(site.source, start.isoformat(), ticket)
                if start.date() < today or key in seen:
                    continue
                seen.add(key)
                yield (
                    (site.source, site.cinema, site.address, site.city),
                    key,
                    start,
                    ticket,
                    *facts(language=info.get("audioLanguage") or "", subtitles=info.get("textLanguage") or ""),
                    f"{site.source}-{feature['id']}",
                    path.name,
                    fields,
                    path.name,
                )
