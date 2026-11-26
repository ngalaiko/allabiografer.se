"""Paths and relative links for on-disk Schema.org documents."""

import json
from os.path import relpath
from pathlib import Path
from urllib.parse import quote

CONTEXT = "https://schema.org"
CATALOGUE = Path("schema/Dataset/catalogue.jsonld")


def entity_path(kind: str, id_: str) -> Path:
    return Path("schema") / kind / f"{id_}.jsonld"


def reference(path: Path, directory: Path) -> str:
    return quote(Path(relpath(path, directory)).as_posix())


def link(path: Path, directory: Path) -> dict[str, str]:
    return {"@id": reference(path, directory)}


def write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
        file.write("\n")


class Catalogue:
    def __init__(self, root: Path):
        self.path = root / CATALOGUE
        self._members: list[Path] = []

    def node(self, path: Path, **fields) -> None:
        self.record(path, {"@context": CONTEXT, "@id": "", "@type": path.parent.name, **fields})

    def record(self, path: Path, document: dict) -> None:
        write(path, document)
        self._members.append(path)

    def finish(self, *, based_on, **fields) -> Path:
        base = self.path.parent
        write(
            self.path,
            {
                "@context": CONTEXT,
                "@id": "",
                "@type": "Dataset",
                **fields,
                "isBasedOn": [link(path, base) for path in based_on],
                "mainEntity": {"@type": "ItemList", "itemListElement": [link(path, base) for path in self._members]},
            },
        )
        return self.path
