"""Roxy Kristianstad's public My Cloud Cinema programme."""

from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

from parse import _http, _version
from parse.parsers import _films, _tmdb_cache
from store import Film, Screening, Venue
from store.version import AudioKind, AudioVersion, ContentVersion, SubtitleVersion

_SOURCE = "roxy_bio"
_BASE = "https://boka.roxy.bio"
_VENUE = Venue(name="Roxy Bio", city="Kristianstad", address="Tivoligatan 3D")
_STOCKHOLM = ZoneInfo("Europe/Stockholm")
_AUDIO = {"Original språk": AudioKind.ORIGINAL, "Dubbad": AudioKind.DUBBED}


def parse() -> Iterator[Screening | Venue | Film]:
    with _http.session() as session:
        response = session.get(
            f"{_BASE}/webservices/show_times/getShowTimesDays",
            params={"cinema_id": 12, "date": datetime.now(_STOCKHOLM).date().isoformat(), "number_of_days": 35},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload["resultCode"] != 0:
            raise ValueError(f"Roxy programme returned resultCode {payload['resultCode']}")

        # The cinema's events feed includes locked bookings and its film quiz.
        rows = [
            row
            for row in payload["data"]
            if not row["show_locked"]
            and row["title"].strip()
            and not row["title"].strip().casefold().startswith("filmquiz")
        ]
        details = {}
        for movie_id in dict.fromkeys(row["movie_id"] for row in rows):
            response = session.get(
                f"{_BASE}/webservices/movies/getMovieDetails",
                params={"cinema_id": 12, "movie_id": movie_id},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if payload["resultCode"] != 0:
                raise ValueError(f"Roxy film {movie_id} returned resultCode {payload['resultCode']}")
            details[movie_id] = next(row for row in payload["data"] if row["movie_id"] == movie_id)

    yield _VENUE
    for row in rows:
        movie_id = row["movie_id"]
        detail = details[movie_id]
        start = datetime.fromisoformat(row["show_time"]).astimezone(_STOCKHOLM)
        audio = _version.languages(row.get("audio_lang") or "")
        kind = _AUDIO.get(row.get("movie_audio_style_name"), AudioKind.UNKNOWN)
        subtitle = row.get("subtitle_lang")
        year = detail.get("production_year") or None
        runtime = row.get("running_time") or None
        film = _films.make(
            _SOURCE,
            row["title"],
            url=f"{_BASE}/#/movie/{movie_id}",
            runtime=runtime,
            age_rating=row.get("rating_name"),
            original_languages=audio if kind is AudioKind.ORIGINAL else frozenset(),
        )
        yield film
        yield Screening(
            # Use the year to disambiguate TMDB candidates, not to group cinema programmes.
            tmdb_id=_tmdb_cache.lookup(film.title, year=year) if year else None,
            title=film.title,
            source=_SOURCE,
            film_key=film.key,
            date=start.date(),
            time=start.time(),
            city=_VENUE.city,
            cinema_name=_VENUE.name,
            screen=row["screen_name"],
            ticket_url=f"{_BASE}/#/book/{row['show_time_id']}",
            runtime=runtime,
            version=ContentVersion(
                audio=AudioVersion(kind, audio),
                subtitles=SubtitleVersion(_version.languages(subtitle) if subtitle else None),
            ),
            raw_attributes=("Slutsålt",) if row.get("sold_out") else (),
        )
