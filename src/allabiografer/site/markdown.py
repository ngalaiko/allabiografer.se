"""Markdown pages rendered directly from the database-backed page data."""

import re
from itertools import groupby
from operator import itemgetter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def text(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>()#|>~])", r"\\\1", str(value))


def link(label: str, url: str) -> str:
    url = url.replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")
    return f"[{text(label)}]({url})"


def page_link(label: str, route: str) -> str:
    return link(label, route + "index.md")


def write_page(path: Path, title: str, lines: list[str]) -> None:
    blocks = [f"# {text(title)}", *filter(None, lines)]
    path.with_suffix(".md").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_programme(
    path: Path,
    title: str,
    blocks: list[dict],
    days: list[dict],
    *,
    note: str = "",
    empty_context: list[dict] | None = None,
) -> None:
    lines = [text(note)] if note else []
    for film_url, group in groupby(blocks, key=itemgetter("film_url")):
        variants = list(group)
        film = variants[0]
        lines.append(f"## {page_link(film['film_title'], film_url)}")
        if film["full_desc"]:
            lines.append(text(film["full_desc"]))
        for block in variants:
            show_variant = len(variants) > 1 or bool(block["variant"])
            if show_variant:
                lines.append(f"### {text(block['variant'] or 'Övriga visningar')}")
            if block["mi_text"]:
                lines.append(text(block["mi_text"]))
            for cinema in block["cinemas"]:
                name = page_link(cinema["name"], cinema["url"]) if cinema["url"] else text(cinema["name"])
                lines.append(f"{'####' if show_variant else '###'} {name}")
                location = " • ".join(filter(None, [cinema["address"], cinema["city_name"]]))
                if location:
                    lines.append(text(location))
                showtimes = []
                for day, cell in zip(days, cinema["cells"], strict=True):
                    if cell["times"]:
                        times = [
                            text(t["label"]) + " (passerad)" if t["past"] else link(t["label"], t["url"])
                            for t in cell["times"]
                        ]
                        showtimes.append(f"- {day['date']}: " + ", ".join(times))
                lines.append("\n".join(showtimes))
    if not blocks:
        if not note:
            lines.append("Inga visningar de närmaste två veckorna.")
        lines.append(
            "\n".join(
                f"- {page_link(item['name'], item['url'])}" + (f" · {text(item['address'])}" if item["address"] else "")
                for item in empty_context or []
            )
        )
    write_page(path, title, lines)


def write_festival(path: Path, festival: dict) -> None:
    lines = [
        text(f"{festival['city']} · {festival['start']} – {festival['end']}"),
        link("Festivalens webbplats", festival["url"]),
    ]
    for film in festival["films"]:
        lines.append(f"## {link(film['title'], film['film_url'])}")
        metadata = [
            f"{film['runtime']} min" if film["runtime"] else "",
            film["production_year"],
            film["sections"],
            film["director"],
            film["country"],
        ]
        lines.append(text(" · ".join(str(value) for value in metadata if value)))
        if film["description"] or film["intro"]:
            lines.append(text(film["description"] or film["intro"]))
        for cinema in film["cinemas"]:
            lines.append(f"### {text(cinema['venue'])}")
            showtimes = []
            for cell in cinema["cells"]:
                for screening in cell["screenings"]:
                    label = f"{screening['date']} {screening['time']}"
                    if screening["end_time"]:
                        label += f"–{screening['end_time']}"
                    details = [screening.get("language"), screening.get("subtitles")]
                    detail = " · ".join(filter(None, details))
                    showtimes.append(f"- {link(label, screening['url'])}" + (f" · {text(detail)}" if detail else ""))
            lines.append("\n".join(showtimes))
    if not festival["films"]:
        lines.append("Inga visningar publicerade ännu.")
    write_page(path, f"{festival['name']} {festival['year']} – program och eget schema", lines)
