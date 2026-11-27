"""The code a run executes and the registry it reads, as a SoftwareSourceCode entity with a byte-exact snapshot."""

import io
import platform
import subprocess
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from .store import REGISTRY as STORE_REGISTRY

if TYPE_CHECKING:
    from .graph import Graph

REPOSITORY = "https://github.com/ngalaiko/allabiografer.se"
ROOT = Path(__file__).resolve().parents[2]
# The package and the manifests that resolve its dependencies.
SOURCES = ("src/allabiografer",)
MANIFESTS = ("pyproject.toml", "uv.lock")
# The registry: what feeds select and what results link to.
REGISTRY = tuple(f"data/allabiografer/schema/{kind}" for kind in sorted(STORE_REGISTRY))


def files(root: Path = ROOT) -> list[Path]:
    """Source and registry files, relative to `root`, excluding tests and caches."""
    found = [root / name for name in MANIFESTS]
    for directory in SOURCES + REGISTRY:
        # Templates, styles and scripts shape the output as much as the Python does.
        for path in (item for item in (root / directory).rglob("*") if item.is_file()):
            relative = path.relative_to(root)
            if "__pycache__" in relative.parts or path.suffix == ".pyc":
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            found.append(path)
    return sorted(path.relative_to(root) for path in found)


def archive(root: Path = ROOT) -> bytes:
    """A deterministic tar of the source files: same code, same bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for relative in files(root):
            data = (root / relative).read_bytes()
            info = tarfile.TarInfo(relative.as_posix())
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def commit(root: Path = ROOT) -> str | None:
    """The checked-out commit, marked `-dirty` when the source files differ from it."""

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)

    head = git("rev-parse", "HEAD")
    if head.returncode:
        return None
    paths = [path.as_posix() for path in files(root)]
    changed = git("status", "--porcelain", "--untracked-files=all", "--", *paths)
    return head.stdout.strip() + ("-dirty" if changed.returncode or changed.stdout.strip() else "")


_snapshots: dict[tuple[str, Path], Path] = {}


def _snapshot(graph: Graph, root: Path) -> Path:
    snapshot = graph.put_bytes(archive(root), "application/x-tar", name="allabiografer-source.tar")
    version = commit(root)
    return graph.put(
        "SoftwareSourceCode",
        {
            "name": "allabiografer.se",
            "codeRepository": REPOSITORY,
            **({"version": version} if version else {}),
            "programmingLanguage": "Python",
            "runtimePlatform": f"Python {platform.python_version()}",
            "encoding": graph.ref(snapshot),
        },
    )


def source_code(graph: Graph, root: Path = ROOT) -> Path:
    """The SoftwareSourceCode entity for the code at `root`, stored once per process."""
    # Object ids are reused once freed; the store's location names it for the whole process.
    store = graph.store
    key = (str(getattr(store, "root", None) or f"{store.bucket}:{id(store.client)}"), root)
    if key not in _snapshots:
        _snapshots[key] = _snapshot(graph, root)
    return _snapshots[key]
