"""Content-addressed assets and Schema.org entities under one data directory."""

import base64
import hashlib
import json
import mimetypes
from compression import zstd
from os.path import relpath
from pathlib import Path
from urllib.parse import quote, unquote

from .store import REGISTRY, LocalStore, registry

CONTEXT = "https://schema.org"
# The repository's data directory; pass another to work elsewhere.
DATA = Path(__file__).resolve().parents[2] / "data" / "allabiografer"
NI_PREFIX = "ni:///sha-256;"
# Compression must save at least this share of the original size.
MIN_SAVING = 0.1


def media_type(name: str, header: str = "") -> str:
    """Media type without parameters, from a response header or the file name."""
    declared = header.split(";", 1)[0].strip().lower()
    return declared or mimetypes.guess_type(name)[0] or "application/octet-stream"


def fragment(kind: str, *values) -> str:
    """A stable fragment identifier for a part, from the values that identify it."""
    digest = hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f"{kind}-{digest[:16]}"


def ni(digest: bytes) -> str:
    return NI_PREFIX + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class Graph:
    """Entities live at schema/<type>/<id>.jsonld; bytes live at assets/<sha256>.

    Entities written with `put` are named by the hash of their content, so they are
    immutable and shared between runs. Links between entities are relative paths.

    A Dataset's parts (Movies, ScreeningEvents, nested Datasets) live in one compressed
    JSON-LD document, its `distribution`. Parts carry `#fragment` identifiers; their links
    resolve against the Dataset entity, as if the document were stored in its place.
    """

    def __init__(self, root: Path = DATA, store=None):
        self.root = root.resolve()
        self.assets = self.root / "assets"
        self.schema = self.root / "schema"
        # Generated objects live in `store`; the checked-in registry is always read from `root`.
        self.store = store or LocalStore(self.root)
        self._local = LocalStore(self.root)
        self._parts: dict[Path, dict[str, dict]] = {}

    def key(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def path_of(self, key: str) -> Path:
        return self.root / key

    def _of(self, path: Path):
        return self._local if registry(self.key(path)) else self.store

    def exists(self, path: Path) -> bool:
        return self._of(path).exists(self.key(path))

    def entities(self, kind: str) -> list[Path]:
        """Every stored entity of a type, fetched in one batch when the store is remote."""
        prefix = f"schema/{kind}/"
        source = self._local if kind in REGISTRY else self.store
        keys = sorted(key for key in source.list(prefix) if key.endswith(".jsonld"))
        source.prefetch(keys)
        return [self.path_of(key) for key in keys]

    def prefetch(self, paths: list[Path]) -> None:
        """Fetch many entities in one batch; later reads are local."""
        self.store.prefetch([self.key(path) for path in paths if not registry(self.key(path))])

    def prefetch_content(self, entities: list[dict]) -> None:
        """Fetch many MediaObjects' bytes in one batch."""
        keys = []
        for entity in entities:
            encoded = entity["contentUrl"].removeprefix(NI_PREFIX)
            keys.append(f"assets/{base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).hex()}")
        self.store.prefetch(keys)

    def path(self, kind: str, id_: str) -> Path:
        return self.schema / kind / f"{id_}.jsonld"

    def ref(self, target: Path) -> dict[str, str]:
        """Link to `target` from any entity in schema/<type>/."""
        return {"@id": quote(Path(relpath(target, self.schema / "_")).as_posix())}

    @staticmethod
    def resolve(origin: Path, reference: dict | str) -> Path:
        """The entity a link points to; a fragment names a part within it."""
        iri = reference["@id"] if isinstance(reference, dict) else reference
        path = iri.partition("#")[0]
        return (origin.parent / unquote(path)).resolve() if path else origin

    def part_ref(self, dataset: Path, fragment: str) -> dict[str, str]:
        """Link to a part of `dataset` from any entity in schema/<type>/."""
        return {"@id": f"{self.ref(dataset)['@id']}#{fragment}"}

    def find(self, origin: Path, reference: dict | str) -> tuple[Path, dict]:
        """The Dataset a part link points into, and the part."""
        iri = reference["@id"] if isinstance(reference, dict) else reference
        dataset = self.resolve(origin, iri)
        return dataset, self.parts(dataset)[iri.partition("#")[2]]

    def put_dataset(self, fields: dict, parts: list[dict]) -> Path:
        """Write a Dataset whose parts live in one compressed JSON-LD document."""
        document = {"@context": CONTEXT, "@type": "Dataset", **fields, "hasPart": parts}
        data = (json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n").encode()
        download = self.put_bytes(data, "application/ld+json", name="dataset.jsonld")
        return self.put("Dataset", {**fields, "distribution": self.ref(download)})

    def parts(self, dataset: Path) -> dict[str, dict]:
        """A Dataset's parts by fragment, those of nested Datasets included."""
        if dataset not in self._parts:
            entity = self.read(dataset)
            distribution = entity.get("distribution")
            if not isinstance(distribution, dict):
                raise ValueError(f"{dataset} keeps no parts; start with --fresh")
            document = json.loads(self.content(self.read(self.resolve(dataset, distribution))))
            found, pending = {}, list(document["hasPart"])
            while pending:
                part = pending.pop()
                found[part["@id"].removeprefix("#")] = part
                if part["@type"] == "Dataset":
                    pending += part.get("hasPart", [])
            self._parts[dataset] = found
        return self._parts[dataset]

    def read(self, path: Path) -> dict:
        return json.loads(self._of(path).get(self.key(path)))

    @staticmethod
    def _dump(document: dict) -> bytes:
        return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()

    def put(self, kind: str, fields: dict) -> Path:
        """Write an immutable entity named by the hash of its content."""
        document = {"@context": CONTEXT, "@type": kind, **fields}
        digest = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        path = self.path(kind, digest)
        if not self.exists(path):
            self.store.put(self.key(path), self._dump({"@context": CONTEXT, "@id": "", **document}))
        return path

    def save(self, kind: str, id_: str, fields: dict) -> Path:
        """Write a named, mutable entity, such as an action record."""
        path = self.path(kind, id_)
        self.store.put(self.key(path), self._dump({"@context": CONTEXT, "@id": "", "@type": kind, **fields}))
        return path

    def put_bytes(self, data: bytes, media: str, *, name: str, url: str = "", compress: bool = True) -> Path:
        """Store raw bytes as an asset and describe them with a MediaObject.

        Compressed assets declare the registered `+zstd` structured syntax suffix. Assets served
        as-is (`compress=False`) keep their bytes unchanged.
        """
        stored, encoding = data, media
        packed = zstd.compress(data) if compress else data
        if compress and len(packed) <= len(data) * (1 - MIN_SAVING):
            stored, encoding = packed, f"{media}+zstd"
        digest = hashlib.sha256(stored).digest()
        asset = f"assets/{digest.hex()}"
        if not self.store.exists(asset):
            self.store.put(asset, stored)
        fields = {
            "name": name,
            "contentUrl": ni(digest),
            "sha256": digest.hex(),
            "contentSize": str(len(stored)),
            "encodingFormat": encoding,
            **({"isBasedOn": url} if url else {}),
        }
        return self.put("ImageObject" if media.startswith("image/") else "DataDownload", fields)

    def content(self, entity: dict) -> bytes:
        """Original bytes of a stored MediaObject, verified against its hash."""
        url = entity["contentUrl"]
        if not url.startswith(NI_PREFIX):
            raise ValueError(f"Unsupported content URL: {url}")
        encoded = url.removeprefix(NI_PREFIX)
        digest = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = self.store.get(f"assets/{digest.hex()}")
        if hashlib.sha256(data).digest() != digest:
            raise ValueError(f"Corrupt asset: {digest.hex()}")
        return zstd.decompress(data) if entity["encodingFormat"].endswith("+zstd") else data
