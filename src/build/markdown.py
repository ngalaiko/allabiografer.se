"""Markdown pages rendered directly from the database-backed page data."""

import re
from pathlib import Path


def text(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>()#|>~])", r"\\\1", str(value))


def link(label: str, url: str) -> str:
    url = url.replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")
    return f"[{text(label)}]({url})"


def write_page(path: Path, title: str, lines: list[str]) -> None:
    path.with_suffix(".md").write_text(f"# {text(title)}\n\n" + "\n\n".join(lines) + "\n", encoding="utf-8")


def write_programme(path: Path, title: str, blocks: list[dict], days: list[dict], *, note: str = "") -> None:
    lines = [text(note)] if note else []
    for block in blocks:
        variant = f" ({block['variant']})" if block["variant"] else ""
        lines.append(f"## {link(block['film_title'], block['film_url'])}{text(variant)}")
        lines.extend(text(block[key]) for key in ("mi_text", "full_desc") if block[key])
        for cinema in block["cinemas"]:
            name = link(cinema["name"], cinema["url"]) if cinema["url"] else text(cinema["name"])
            lines.append(f"### {name}")
            location = " • ".join(filter(None, [cinema["address"], cinema["city_name"]]))
            if location:
                lines.append(text(location))
            for day, cell in zip(days, cinema["cells"], strict=True):
                if cell["times"]:
                    times = [
                        text(t["label"]) + " (passerad)" if t["past"] else link(t["label"], t["url"])
                        for t in cell["times"]
                    ]
                    lines.append(f"- {day['date']}: " + ", ".join(times))
    if not blocks:
        lines.append("Inga visningar de närmaste två veckorna.")
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
            for cell in cinema["cells"]:
                for screening in cell["screenings"]:
                    label = f"{screening['date']} {screening['time']}"
                    if screening["end_time"]:
                        label += f"–{screening['end_time']}"
                    details = [screening.get("language"), screening.get("subtitles")]
                    detail = " · ".join(filter(None, details))
                    lines.append(f"- {link(label, screening['url'])}" + (f" · {text(detail)}" if detail else ""))
    if not festival["films"]:
        lines.append("Inga visningar publicerade ännu.")
    write_page(path, f"{festival['name']} {festival['year']} – program och eget schema", lines)
