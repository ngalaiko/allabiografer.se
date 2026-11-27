"""Draw what a run did as a Mermaid diagram, rendered with Pele (https://pele.run).

- no arguments: the newest run, every step with its status and what it read and wrote;
- `--step <name or id>`: one step of that run, its inputs, its result and, for a read, the
  screenings per feed;
- `--film <slug>`: where a Programme film comes from, down to the URLs fetched.

It writes the diagram as SVG, rendered by Pele, and opens it with `--open`; `--mermaid`
prints the Mermaid source instead. Runs from the local store; `nix run .#pull` copies
production there.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .graph import DATA, Graph

# Mermaid on stdin, SVG on stdout; the flake sets PELE to Pele's dist/pele.js.
RENDERER = Path(__file__).with_name("pele.mjs")
STATUS = {
    "https://schema.org/CompletedActionStatus": "done",
    "https://schema.org/FailedActionStatus": "failed",
    "https://schema.org/ActiveActionStatus": "running",
}
STYLES = """  classDef failed fill:#f4c7c3,stroke:#a51d2d
  classDef running fill:#fde9a9,stroke:#9c6d00
  classDef data fill:#e6e4d9,stroke:#6f6e69"""


def _label(*lines: str) -> str:
    text = "<br/>".join(line for line in lines if line)
    return '"' + text.replace('"', "#quot;") + '"'


def _list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def _seconds(action: dict) -> str:
    if "endTime" not in action:
        return ""
    elapsed = datetime.fromisoformat(action["endTime"]) - datetime.fromisoformat(action["startTime"])
    return f"{elapsed.total_seconds():.0f} s"


class Diagram:
    def __init__(self, graph: Graph):
        self.graph = graph
        self.lines = ["flowchart LR"]
        self.ids: dict[str, str] = {}

    def node(self, key: str, shape: str, label: str, style: str = "") -> str:
        if key not in self.ids:
            self.ids[key] = f"n{len(self.ids)}"
            opening, closing = {"step": ("(", ")"), "data": ("[(", ")]"), "file": ("[/", "/]"), "box": ("[", "]")}[
                shape
            ]
            self.lines.append(f"  {self.ids[key]}{opening}{label}{closing}{':::' + style if style else ''}")
        return self.ids[key]

    def edge(self, a: str, b: str, text: str = "") -> None:
        self.lines.append(f"  {a} -->{'|' + _label(text) + '|' if text else ''} {b}")

    def action(self, path: Path) -> str:
        action = self.graph.read(path)
        status = STATUS.get(action.get("actionStatus", ""), "")
        error = (action.get("error") or {}).get("description", "").splitlines()[:1]
        style = status if status in ("failed", "running") else ""
        return self.node(str(path), "step", _label(action["name"], f"{status} {_seconds(action)}", *error), style)

    def dataset(self, path: Path) -> str:
        entity = self.graph.read(path)
        distribution = entity.get("distribution")
        if isinstance(distribution, list):
            summary = f"{len(distribution)} files"
        else:
            kinds = Counter(part["@type"] for part in self.graph.parts(path).values())
            summary = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
        return self.node(str(path), "data", _label(entity.get("name", path.stem[:12]), summary), "data")

    def thing(self, origin: Path, reference) -> str | None:
        """A node for a linked entity; None for the registry, which every run reads."""
        if "@id" not in reference:
            return self.node(
                json.dumps(reference, sort_keys=True),
                "box",
                _label(reference.get("name", ""), reference.get("size", "")),
            )
        path = self.graph.resolve(origin, reference)
        if path.parent.name == "Dataset":
            return self.dataset(path)
        return None

    def source(self) -> str:
        return "\n".join([*self.lines, STYLES]) + "\n"


def runs(graph: Graph) -> list[tuple[str, Path]]:
    return sorted((graph.read(path)["startTime"], path) for path in graph.entities("UpdateAction"))


def steps(graph: Graph, run: Path) -> list[tuple[Path, dict]]:
    """The actions recorded during a run, in order."""
    record = graph.read(run)
    end = record.get("endTime", "9999")
    found = []
    for kind in ("DownloadAction", "CreateAction"):
        for path in graph.entities(kind):
            action = graph.read(path)
            if record["startTime"] <= action["startTime"] <= end:
                found.append((path, action))
    return sorted(found, key=lambda item: item[1]["startTime"])


def overview(graph: Graph, run: Path) -> Diagram:
    diagram = Diagram(graph)
    for path, action in steps(graph, run):
        step = diagram.action(path)
        for reference in _list(action.get("object")):
            if (source := diagram.thing(path, reference)) is not None:
                diagram.edge(source, step)
        if "result" in action and (result := diagram.thing(path, action["result"])) is not None:
            diagram.edge(step, result)
    return diagram


def step(graph: Graph, run: Path, wanted: str) -> Diagram:
    found = [
        (path, action)
        for path, action in steps(graph, run)
        if wanted in (path.stem, action["name"]) or wanted in action["name"]
    ]
    if len(found) != 1:
        names = ", ".join(action["name"] for _, action in found) or "none"
        raise SystemExit(f"{len(found)} steps match {wanted!r}: {names}")
    path, action = found[0]
    diagram = Diagram(graph)
    node = diagram.action(path)
    for reference in _list(action.get("object")):
        if (source := diagram.thing(path, reference)) is not None:
            diagram.edge(source, node)
    if "result" not in action or "@id" not in action["result"]:
        return diagram
    result = graph.resolve(path, action["result"])
    target = diagram.thing(path, action["result"])
    diagram.edge(node, target)
    entity = graph.read(result)
    if isinstance(entity.get("distribution"), list):
        # Downloaded files, by kind: programme pages, film pages, API responses.
        kinds = Counter(graph.read(graph.resolve(result, ref))["name"].split("-")[0] for ref in entity["distribution"])
        for kind, count in sorted(kinds.items()):
            diagram.edge(target, diagram.node(f"{result}:{kind}", "file", _label(f"{kind}…", f"{count} files")))
        return diagram
    # A read: screenings per feed snapshot.
    for part in graph.parts(result).values():
        if part["@type"] == "Dataset" and "isBasedOn" in part:
            feed = graph.resolve(result, part["isBasedOn"])
            # The registry ID keeps the town that tells namesakes apart: "Saga (Mora)".
            name = feed.stem
            shows = len(part.get("hasPart", []))
            feed_node = diagram.node(str(feed), "box", _label(name, f"{shows} screenings"), "" if shows else "failed")
            diagram.edge(target, feed_node)
    return diagram


def film(graph: Graph, programme: Path, slug: str) -> Diagram:
    parts = graph.parts(programme)
    movie = next(
        (
            part
            for part in parts.values()
            if part["@type"] == "Movie" and any(item.get("value") == slug for item in part["identifier"])
        ),
        None,
    )
    if movie is None:
        raise SystemExit(f"No film {slug!r} in the Programme")
    diagram = Diagram(graph)
    top = diagram.node(movie["@id"], "box", _label(movie["name"], slug))
    diagram.edge(diagram.dataset(programme), top)
    for link in movie["isBasedOn"]:
        if "#" in link["@id"]:
            dataset, record = graph.find(programme, link)
            name = graph.read(dataset)["name"]
            parsed = diagram.node(link["@id"], "box", _label(record["name"], name))
            diagram.edge(top, parsed, "read as")
            file = graph.resolve(dataset, record["isBasedOn"])
        else:
            parsed, file = top, graph.resolve(programme, link)
        if not graph.exists(file):
            continue
        entity = graph.read(file)
        downloaded = diagram.node(str(file), "file", _label(entity["name"], entity.get("isBasedOn", "")))
        diagram.edge(parsed, downloaded, "from" if parsed != top else "looked up")
    return diagram


def svg(source: str) -> str:
    """The diagram as SVG, rendered by Pele."""
    if not os.environ.get("PELE"):
        raise SystemExit("PELE is unset: run through `nix run .#trace`")
    done = subprocess.run(["node", str(RENDERER)], input=source, capture_output=True, text=True, check=False)
    if done.returncode:
        raise SystemExit(f"Pele could not render the diagram:\n{done.stderr.strip()}")
    return done.stdout


def show(path: Path) -> None:
    subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--run", help="Run ID (an UpdateAction file name); default: the newest")
    choice = cli.add_mutually_exclusive_group()
    choice.add_argument("--step", help="A step of the run, by name or ID, e.g. 'Read bio.se'")
    choice.add_argument("--film", help="A Programme film's slug")
    cli.add_argument("--data", type=Path, default=DATA, help="Local store")
    cli.add_argument("--output", type=Path, default=DATA / "trace.svg", help="SVG to write")
    cli.add_argument("--open", action="store_true", help="Open the SVG")
    cli.add_argument("--mermaid", action="store_true", help="Print the Mermaid source instead")
    args = cli.parse_args()
    graph = Graph(args.data.resolve())
    found = runs(graph)
    if not found:
        raise SystemExit("No runs in the local store; run one or `nix run .#pull`")
    run = graph.path("UpdateAction", args.run) if args.run else found[-1][1]
    record = graph.read(run)
    if args.film:
        if "result" not in record:
            raise SystemExit("The run built no Programme")
        diagram = film(graph, graph.resolve(run, record["result"]), args.film)
    elif args.step:
        diagram = step(graph, run, args.step)
    else:
        diagram = overview(graph, run)
    source = diagram.source()
    if args.mermaid:
        print(source, end="")
        return
    args.output.write_text(svg(source), encoding="utf-8")
    print(args.output.resolve())
    if args.open:
        show(args.output)
