"""The code a run executes, as a SoftwareSourceCode entity with a byte-exact snapshot."""

import io
import platform
import subprocess
import tarfile
from functools import cache
from pathlib import Path

from .graph import Graph

REPOSITORY = "https://github.com/ngalaiko/allabiografer.se"
ROOT = Path(__file__).resolve().parents[2]
# The package and the manifests that resolve its dependencies.
SOURCES = ("src/allabiografer",)
MANIFESTS = ("pyproject.toml", "uv.lock")


def files(root: Path = ROOT) -> list[Path]:
    """Source files, relative to `root`, excluding tests, caches, and data."""
    found = [root / name for name in MANIFESTS]
    for directory in SOURCES:
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


@cache
def _snapshot(graph_root: Path, root: Path) -> Path:
    graph = Graph(graph_root)
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
    return _snapshot(graph.root, root)
