from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredAsset:
    storage_key: str
    file_name: str
    file_size_bytes: int
    sha256_hash: str


class AssetStorage(Protocol):
    """Replaceable storage boundary for uploaded project evidence."""
    def save(self, file_name: str, source: BinaryIO, project_id: str | None = None, max_bytes: int | None = None) -> StoredAsset: ...
    def open(self, storage_key: str) -> BinaryIO: ...
    def delete(self, storage_key: str) -> None: ...


class FileTooLargeError(ValueError):
    pass


class LocalAssetStorage:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv("ASSET_STORAGE_DIR", "./storage")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, storage_key: str) -> Path:
        path = (self.root / PurePosixPath(storage_key)).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    def save(self, file_name: str, source: BinaryIO, project_id: str | None = None, max_bytes: int | None = None) -> StoredAsset:
        safe_name = Path(file_name.replace("\\", "/")).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("A safe base file name is required")
        prefix = PurePosixPath(project_id or "company").name
        key = f"{prefix}/{uuid.uuid4().hex}_{safe_name}"
        destination = self.path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with destination.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    if max_bytes is not None and size + len(chunk) > max_bytes:
                        raise FileTooLargeError("The file exceeds the configured upload limit")
                    digest.update(chunk)
                    size += len(chunk)
                    target.write(chunk)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return StoredAsset(key, safe_name, size, digest.hexdigest())

    def save_bytes(self, file_name: str, content: bytes, project_id: str | None = None) -> StoredAsset:
        return self.save(file_name, BytesIO(content), project_id)

    def open(self, storage_key: str) -> BinaryIO:
        return self.path_for(storage_key).open("rb")

    def delete(self, storage_key: str) -> None:
        path = self.path_for(storage_key)
        path.unlink(missing_ok=True)
        parent = path.parent
        if parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                pass


def storage_key_exists(storage_key: str | None) -> bool:
    if not storage_key:
        return False
    try:
        return LocalAssetStorage().path_for(storage_key).is_file()
    except (OSError, ValueError):
        return False
