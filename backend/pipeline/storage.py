"""Audio storage abstraction.

Phase 1 ships LocalFilesystemStorage only. STORAGE_BACKEND env var selects the
implementation so S3/MinIO is a drop-in later without touching any caller —
routers/calls.py and pipeline/orchestrator.py only ever talk to the AudioStorage interface.
"""
import hashlib
import os
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from backend.app.config import get_settings


class AudioStorage(ABC):
    @abstractmethod
    def save(self, call_id: str, filename: str, fileobj) -> str:
        """Persist fileobj permanently, return the storage_path to record on the Call row."""

    @abstractmethod
    def get_path(self, storage_path: str) -> Path:
        """Return a local filesystem path readable by the pipeline worker."""

    @abstractmethod
    def stream(self, storage_path: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        """Yield bytes in [start, end) for range-request audio playback."""

    @abstractmethod
    def size(self, storage_path: str) -> int:
        ...

    @abstractmethod
    def delete(self, storage_path: str) -> None:
        """Only ever called for .temp/ working files — never for a Call's permanent
        recording (see docs/project/REUSE.md and the audit fixes in the approved plan)."""


def sha256_of(fileobj) -> str:
    fileobj.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        digest.update(chunk)
    fileobj.seek(0)
    return digest.hexdigest()


class LocalFilesystemStorage(AudioStorage):
    def __init__(self, base_path: str | None = None):
        settings = get_settings()
        self.base_path = Path(base_path or settings.storage_local_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, call_id: str, filename: str, fileobj) -> str:
        ext = Path(filename).suffix
        rel_path = f"{call_id}{ext}"
        dest = self.base_path / rel_path
        with open(dest, "wb") as out:
            shutil.copyfileobj(fileobj, out)
        return rel_path

    def get_path(self, storage_path: str) -> Path:
        return self.base_path / storage_path

    def stream(self, storage_path: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        path = self.get_path(storage_path)
        chunk_size = 64 * 1024
        with open(path, "rb") as f:
            f.seek(start)
            remaining = None if end is None else end - start
            while True:
                read_size = chunk_size if remaining is None else min(chunk_size, remaining)
                if read_size <= 0:
                    break
                data = f.read(read_size)
                if not data:
                    break
                if remaining is not None:
                    remaining -= len(data)
                yield data

    def size(self, storage_path: str) -> int:
        return os.path.getsize(self.get_path(storage_path))

    def delete(self, storage_path: str) -> None:
        path = self.get_path(storage_path)
        if path.exists():
            path.unlink()


_storage_instance: AudioStorage | None = None


def get_storage() -> AudioStorage:
    global _storage_instance
    if _storage_instance is None:
        settings = get_settings()
        if settings.storage_backend == "local":
            _storage_instance = LocalFilesystemStorage()
        else:
            raise ValueError(f"Unsupported STORAGE_BACKEND: {settings.storage_backend}")
    return _storage_instance
