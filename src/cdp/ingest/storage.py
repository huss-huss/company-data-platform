"""Object storage for the raw layer.

The interface deliberately mirrors the subset of ``google.cloud.storage`` the pipeline needs
(``client.bucket(name).blob(key)``, ``upload_from_string``, ``download_as_bytes``,
``list_blobs(prefix=...)``, ``metadata`` and the ``if_generation_match=0`` create-only
precondition). Swapping :class:`LocalFilesystemClient` for a real GCS client is therefore a
constructor change, not a refactor.

Raw bytes are stored untouched; metadata lives in a sidecar tree (``_meta/``) so the payload
files stay byte-identical to what the provider returned.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol


class PreconditionFailedError(Exception):
    """Raised when ``if_generation_match=0`` is used and the object already exists."""


class Blob(Protocol):
    name: str
    metadata: dict[str, str] | None
    content_type: str | None

    def exists(self) -> bool: ...
    def reload(self) -> None: ...
    def upload_from_string(
        self,
        data: bytes | str,
        content_type: str | None = None,
        if_generation_match: int | None = None,
    ) -> None: ...
    def download_as_bytes(self) -> bytes: ...


class Bucket(Protocol):
    name: str

    def blob(self, blob_name: str) -> Blob: ...
    def list_blobs(self, prefix: str | None = None) -> Iterator[Blob]: ...


class StorageClient(Protocol):
    def bucket(self, bucket_name: str) -> Bucket: ...


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class LocalBlob:
    def __init__(self, bucket: LocalBucket, name: str) -> None:
        if name.startswith("/") or ".." in Path(name).parts or name.startswith("_meta/"):
            raise ValueError(f"invalid blob name: {name!r}")
        self.bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None
        self.content_type: str | None = None

    @property
    def _path(self) -> Path:
        return self.bucket.root / self.name

    @property
    def _meta_path(self) -> Path:
        return self.bucket.root / "_meta" / f"{self.name}.json"

    @property
    def public_url(self) -> str:
        return f"file://{self._path}"

    @property
    def uri(self) -> str:
        return f"gs://{self.bucket.name}/{self.name}"

    def exists(self) -> bool:
        return self._path.exists()

    def reload(self) -> None:
        if not self.exists():
            raise FileNotFoundError(self.uri)
        if self._meta_path.exists():
            sidecar = json.loads(self._meta_path.read_text())
            self.metadata = sidecar.get("metadata")
            self.content_type = sidecar.get("content_type")

    def upload_from_string(
        self,
        data: bytes | str,
        content_type: str | None = None,
        if_generation_match: int | None = None,
    ) -> None:
        if if_generation_match == 0 and self.exists():
            raise PreconditionFailedError(self.uri)
        payload = data.encode() if isinstance(data, str) else data
        self.content_type = content_type
        # Metadata first: a crash between the two writes leaves an orphan sidecar (harmless)
        # rather than a payload without provenance.
        _atomic_write(
            self._meta_path,
            json.dumps({"metadata": self.metadata, "content_type": content_type}).encode(),
        )
        _atomic_write(self._path, payload)

    def download_as_bytes(self) -> bytes:
        return self._path.read_bytes()


class LocalBucket:
    def __init__(self, root: Path, name: str) -> None:
        self.name = name
        self.root = root / name

    def blob(self, blob_name: str) -> LocalBlob:
        return LocalBlob(self, blob_name)

    def list_blobs(self, prefix: str | None = None) -> Iterator[LocalBlob]:
        if not self.root.exists():
            return
        for path in sorted(self.root.rglob("*")):
            rel = path.relative_to(self.root).as_posix()
            if not path.is_file() or rel.startswith("_meta/") or path.name.startswith(".tmp-"):
                continue
            if prefix and not rel.startswith(prefix):
                continue
            blob = LocalBlob(self, rel)
            blob.reload()
            yield blob


class LocalFilesystemClient:
    """GCS-shaped client backed by a local directory (``<root>/<bucket>/<blob>``)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def bucket(self, bucket_name: str) -> LocalBucket:
        return LocalBucket(self.root, bucket_name)
