"""Where entities and assets live: a local directory, or an S3-compatible bucket such as R2.

Objects are addressed by keys relative to the data directory: `schema/<Type>/<id>.jsonld`
and `assets/<sha256>`. The registry (`schema/{City,MovieTheater,...}`) is always read from
the checkout; it is code-reviewed data, not generated.
"""

import concurrent.futures
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

REGISTRY = frozenset({"AdministrativeArea", "City", "Country", "DataFeed", "MovieTheater"})


class LocalStore:
    """Objects as files under a directory."""

    def __init__(self, root: Path):
        self.root = root

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def put(self, key: str, data: bytes) -> None:
        import tempfile

        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        # mkstemp creates private files; stored data is meant to be read by anyone.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)

    def exists(self, key: str) -> bool:
        return (self.root / key).is_file()

    def prefetch(self, keys: list[str]) -> None:
        pass

    def flush(self) -> None:
        pass

    def size(self, key: str) -> int:
        return (self.root / key).stat().st_size

    def list(self, prefix: str) -> Iterator[str]:
        base = self.root / prefix
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and not path.name.startswith(".tmp-"):
                    yield path.relative_to(self.root).as_posix()

    def delete(self, keys: list[str]) -> None:
        for key in keys:
            (self.root / key).unlink(missing_ok=True)
        for directory in sorted({(self.root / key).parent for key in keys}, reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()


class BucketStore:
    """Objects in an S3-compatible bucket, with a local read-through cache.

    Generated objects are named by their content or by a run's UUID and never change once
    complete, so cached copies never go stale; only action records are rewritten, and those
    are never cached. The bucket is listed once, so existence checks cost no requests.
    Writes are uploaded in the background; `flush` waits for them, and action records
    (which link to what a step wrote) are written only after a flush.
    """

    def __init__(self, client, bucket: str, cache: Path | None = None, workers: int = 32):
        self.client = client
        self.bucket = bucket
        self.cache = cache
        self._pool = concurrent.futures.ThreadPoolExecutor(workers)
        self._pending: list[concurrent.futures.Future] = []
        # Every key with its size, from one listing; writes and deletes keep it current.
        self._keys: dict[str, int] | None = None

    @classmethod
    def from_environment(cls, cache: Path | None = None) -> BucketStore:
        """R2 from R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET.

        R2_JURISDICTION (such as `eu`) selects a jurisdiction's endpoint; its buckets are only
        reachable there.
        """
        import boto3
        from botocore.config import Config

        jurisdiction = f".{name}" if (name := os.environ.get("R2_JURISDICTION", "").strip()) else ""
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}{jurisdiction}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
            config=Config(retries={"max_attempts": 10, "mode": "adaptive"}, max_pool_connections=64),
        )
        return cls(client, os.environ["R2_BUCKET"], cache)

    @staticmethod
    def _mutable(key: str) -> bool:
        return key.startswith("schema/") and key.split("/")[1].endswith("Action")

    @property
    def keys(self) -> dict[str, int]:
        if self._keys is None:
            found = {}
            for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket):
                found.update((item["Key"], item["Size"]) for item in page.get("Contents", []))
            self._keys = found
        return self._keys

    def _cached(self, key: str) -> Path | None:
        return self.cache / key if self.cache and not self._mutable(key) else None

    def get(self, key: str) -> bytes:
        cached = self._cached(key)
        if cached and cached.is_file():
            return cached.read_bytes()
        data = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        if cached:
            LocalStore(self.cache).put(key, data)
        return data

    def prefetch(self, keys: list[str]) -> None:
        """Cache many immutable objects at once; later gets read them locally."""
        if not self.cache:
            return
        missing = [key for key in keys if not self._mutable(key) and not (self.cache / key).is_file()]
        list(self._pool.map(self.get, missing))

    def put(self, key: str, data: bytes) -> None:
        self.keys[key] = len(data)
        if self._cached(key):
            LocalStore(self.cache).put(key, data)
        if self._mutable(key):
            # A record links to what its step wrote: those objects land first.
            self.flush()
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
            return
        self._pending.append(self._pool.submit(self.client.put_object, Bucket=self.bucket, Key=key, Body=data))

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        for future in pending:
            future.result()

    def exists(self, key: str) -> bool:
        return key in self.keys

    def size(self, key: str) -> int:
        return self.keys[key]

    def list(self, prefix: str) -> Iterator[str]:
        return iter(sorted(key for key in self.keys if key.startswith(prefix)))

    def delete(self, keys: list[str]) -> None:
        self.flush()
        for start in range(0, len(keys), 1000):
            batch = keys[start : start + 1000]
            self.client.delete_objects(
                Bucket=self.bucket, Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True}
            )
        for key in keys:
            self.keys.pop(key, None)
        for key in keys:
            if self.cache:
                (self.cache / key).unlink(missing_ok=True)


def registry(key: str) -> bool:
    """Whether a key is part of the checked-in registry."""
    parts = key.split("/")
    return len(parts) == 3 and parts[0] == "schema" and parts[1] in REGISTRY
