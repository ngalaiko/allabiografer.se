"""Static festival timelines with browser-based personal schedules."""

import hashlib
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import build
from build.markdown import page_link, write_festival, write_page
from store import DB_FILE, read_festivals
from store.version import Language

TZ = ZoneInfo("Europe/Stockholm")
_LANGUAGE_TAGS = {language.value.casefold(): language.tag for language in Language}


def _web_url(value: str) -> str:
    if urlparse(value).scheme not in {"http", "https"} or not urlparse(value).netloc:
        raise ValueError(f"Invalid festival URL: {value}")
    return value


def prepare(festival: dict) -> dict:
    """Validate programme data and lay out overlapping screenings in lanes."""
    festival = dict(festival)
    if not re.fullmatch(r"[a-z0-9-]+", festival["slug"]) or not isinstance(festival["year"], int):
        raise ValueError("Invalid festival path")
    first, last = (date.fromisoformat(festival[key]) for key in ("start", "end"))
    if not 0 <= (last - first).days <= 60:
        raise ValueError("Invalid festival dates")
    _web_url(festival["url"])
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    festival["days"] = [{"date": day.isoformat(), "label": day.strftime("%d/%m")} for day in days]
    festival["path"] = f"/festival/{festival['slug']}/{festival['year']}/"
    ids = set()
    films = defaultdict(list)
    screenings = []
    for original in festival["screenings"]:
        item = dict(original)
        identifier = str(item["id"])
        if identifier in ids:
            raise ValueError(f"Duplicate screening ID: {identifier}")
        ids.add(identifier)
        start = datetime.fromisoformat(item["start"])
        end = datetime.fromisoformat(item["end"]) if item.get("end") else None
        if start.tzinfo is None or (end and (end.tzinfo is None or end <= start)):
            raise ValueError(f"Invalid screening times: {identifier}")
        start = start.astimezone(TZ)
        if not first <= start.date() <= last:
            raise ValueError(f"Screening outside festival dates: {identifier}")
        _web_url(item["url"])
        minutes = start.hour * 60 + start.minute
        duration = (end - start).total_seconds() / 60 if end else None
        item.update(
            id=identifier,
            date=start.date().isoformat(),
            time=start.strftime("%H:%M"),
            end_time=end.astimezone(TZ).strftime("%H:%M") if end else "",
            minutes=minutes,
            duration=duration,
            left=round(5 + max(0, min(1, (minutes - 360) / 1080)) * 120, 1),
        )
        screenings.append(item)
        films[item["film_id"]].append(item)
    rows = []
    for film_id, items in films.items():
        metadata = {
            key: next((s[key] for s in items if s.get(key)), "")
            for key in (
                "film_url",
                "poster_url",
                "description",
                "intro",
                "runtime",
                "genres",
                "sections",
                "director",
                "country",
                "production_year",
                "language",
                "subtitles",
            )
        }
        for key in ("film_url", "poster_url"):
            if metadata[key]:
                _web_url(metadata[key])
        metadata["film_url"] = metadata["film_url"] or items[0]["url"]
        cinemas = []
        for venue in sorted({item["venue"] for item in items}):
            cells = []
            for day in festival["days"]:
                entries = sorted(
                    (s for s in items if s["date"] == day["date"] and s["venue"] == venue),
                    key=lambda s: s["start"],
                )
                lanes = []
                for item in entries:
                    lane = next((i for i, until in enumerate(lanes) if until <= item["left"]), len(lanes))
                    if lane == len(lanes):
                        lanes.append(0)
                    lanes[lane] = item["left"] + 70
                    item["lane"] = lane
                cells.append({"date": day["date"], "screenings": entries, "lanes": len(lanes)})
            cinemas.append(
                {"venue": venue, "cells": cells, "height": max(1, *(cell["lanes"] for cell in cells)) * 40 + 12}
            )
        rows.append(
            {
                "id": film_id,
                "title": items[0]["title"],
                **metadata,
                "cinemas": cinemas,
            }
        )
    festival["films"] = sorted(rows, key=lambda f: (min(s["start"] for s in films[f["id"]]), f["title"].casefold()))
    festival["screenings"] = sorted(screenings, key=lambda s: (s["start"], s["id"]))
    return festival


def _festival_nodes(sd, festival: dict, canonical: str) -> tuple[list[dict], list[dict]]:
    movies = {}
    for film in festival["films"]:
        movie = {
            "@type": "Movie",
            "@id": f"{canonical}#movie-{quote(str(film['id']), safe='')}",
            "name": film["title"],
        }
        if film["poster_url"]:
            movie["image"] = film["poster_url"]
        if description := film["description"] or film["intro"]:
            movie["description"] = description
        movies[film["id"]] = movie
    events = []
    for s in festival["screenings"]:
        event = build._screening_node(
            sd,
            movies[s["film_id"]],
            city=festival["city"],
            cinema=s["venue"],
            start=datetime.fromisoformat(s["start"]).astimezone(TZ).isoformat(),
            end=datetime.fromisoformat(s["end"]).astimezone(TZ).isoformat() if s.get("end") else "",
            ticket_url=s["url"],
        )
        for source, prop in (("language", "inLanguage"), ("subtitles", "subtitleLanguage")):
            names = dict.fromkeys(part.strip() for part in s.get(source, "").split(",") if part.strip())
            if names:
                event[prop] = [
                    _LANGUAGE_TAGS.get(name.casefold()) or {"@type": "Language", "name": name} for name in names
                ]
        events.append(event)
    return list(movies.values()), events


def build_festivals(env, sd, register, db_path: Path = DB_FILE) -> list[dict]:
    festivals = [
        prepare({**asdict(festival), "screenings": [asdict(s) for s in screenings]})
        for festival, screenings in read_festivals(path=db_path)
        if festival.city == "Stockholm"
    ]
    versions = {
        name: hashlib.sha256(Path(f"static/i/festival.{name}").read_bytes()).hexdigest()[:12] for name in ("css", "js")
    }
    for festival in festivals:
        out = sd.out_dir / festival["path"].strip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        canonical = register(sd, out)
        movies, events = _festival_nodes(sd, festival, canonical)
        build._write_schedule_feeds(out, movies, events, sd.generated_at)
        out.write_text(
            env.get_template("festival.html").render(
                title=f"{festival['name']} {festival['year']} – program och eget schema",
                description=(
                    f"Planera {festival['name']}: välj visningar, dela ditt schema och exportera till kalendern."
                ),
                og_image=build._abs(
                    build.write_card(
                        sd.out_dir,
                        title=festival["name"],
                        subtitle="Program och eget schema",
                        year=festival["year"],
                    )
                ),
                canonical=canonical,
                schedule_alternates=True,
                festival=festival,
                city_url=urlparse(build.city_programme_url(festival["city"])).path,
                versions=versions,
            )
        )
        end = sd.today + timedelta(days=build.SCHEDULE_DAYS)
        markdown = prepare(
            {
                **festival,
                "screenings": [s for s in festival["screenings"] if sd.today <= date.fromisoformat(s["date"]) < end],
            }
        )
        write_festival(out, markdown)
    out = sd.out_dir / "festival" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        env.get_template("festivals.html").render(
            title="Filmfestivaler – program och egna scheman",
            description="Filmfestivaler i Sverige. Planera ditt festivalschema.",
            og_image=build._abs(
                build.write_card(sd.out_dir, title="Filmfestivaler", subtitle="Program och egna scheman")
            ),
            canonical=register(sd, out),
            festivals=festivals,
            active="festival",
        )
    )
    write_page(
        out,
        "Filmfestivaler – program och egna scheman",
        ["\n".join(f"- {page_link(f['name'] + ' ' + str(f['year']), f['path'])}" for f in festivals)],
    )
    return festivals
