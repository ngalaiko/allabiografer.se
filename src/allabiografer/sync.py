"""Copy the generated store between R2 and the data directory.

`pull` makes the data directory a copy of the bucket; `push` makes the bucket a copy of
the data directory. Both delete objects missing from the source, and both refuse a source
without a completed run, so an empty side can never wipe the other. The registry is never
copied: it is read from the checkout either way.
"""

import argparse
import concurrent.futures
from pathlib import Path

from .graph import DATA
from .store import BucketStore, LocalStore, registry

COMPLETED = b'"https://schema.org/CompletedActionStatus"'


def keys(store) -> set[str]:
    return {key for prefix in ("schema/", "assets/") for key in store.list(prefix) if not registry(key)}


def _has_run(store, found: set[str]) -> bool:
    return any(key.startswith("schema/UpdateAction/") and COMPLETED in store.get(key) for key in found)


def mirror(source, target) -> tuple[int, int]:
    """Make `target` hold exactly `source`'s generated objects; return (copied, deleted)."""
    wanted, present = keys(source), keys(target)
    if not _has_run(source, wanted):
        raise SystemExit("The source has no completed run; refusing to mirror it")
    # Content-named objects never change; action records do, so they are always copied.
    copy = sorted(key for key in wanted if key not in present or "Action/" in key)
    with concurrent.futures.ThreadPoolExecutor(32) as pool:
        list(pool.map(lambda key: target.put(key, source.get(key)), copy))
    stale = sorted(present - wanted)
    target.delete(stale)
    return len(copy), len(stale)


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("direction", choices=("pull", "push"))
    cli.add_argument("--data", type=Path, default=DATA)
    args = cli.parse_args()
    local, bucket = LocalStore(args.data.resolve()), BucketStore.from_environment()
    source, target = (bucket, local) if args.direction == "pull" else (local, bucket)
    copied, deleted = mirror(source, target)
    print(f"{args.direction}: copied {copied}, deleted {deleted}")
