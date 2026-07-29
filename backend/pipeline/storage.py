"""Audio storage abstraction.

STORAGE_BACKEND env var selects the implementation ("local" or "s3") so callers never
know which one is in play — routers/calls.py and pipeline/orchestrator.py only ever
talk to the AudioStorage interface.
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


class S3CompatibleStorage(AudioStorage):
    """Production storage option. Works against real AWS S3 or any S3-compatible
    endpoint (MinIO, etc.) via `storage_s3_endpoint_url`.

    `get_path()` still has to return a *local* filesystem path: every existing
    src/audio/* class (unmodified, per the approved plan) opens its input via
    librosa/soundfile/ffmpeg subprocess calls, not a byte stream — there's no
    S3-native way to hand them a file. So this downloads to a local cache once (under
    the call's own .temp/ working directory, which the orchestrator already cleans up
    at the end of a run — no extra cleanup path needed) and reuses it if already
    present, rather than re-downloading on every access.
    """

    def __init__(self) -> None:
        import boto3

        settings = get_settings()
        if not settings.storage_s3_bucket:
            raise ValueError("STORAGE_S3_BUCKET must be set when STORAGE_BACKEND=s3")

        self.bucket = settings.storage_s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_s3_endpoint_url or None,
            region_name=settings.storage_s3_region,
        )
        self._download_cache_dir = Path(settings.pipeline_temp_dir) / "_s3_cache"
        self._download_cache_dir.mkdir(parents=True, exist_ok=True)

    def save(self, call_id: str, filename: str, fileobj) -> str:
        ext = Path(filename).suffix
        key = f"{call_id}{ext}"
        fileobj.seek(0)
        self._client.upload_fileobj(fileobj, self.bucket, key)
        return key

    def get_path(self, storage_path: str) -> Path:
        local_path = self._download_cache_dir / storage_path
        if not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(self.bucket, storage_path, str(local_path))
        return local_path

    def stream(self, storage_path: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        # Proxied directly from S3 via an HTTP Range request — no need to pull the
        # whole object locally just to serve audio playback.
        range_header = f"bytes={start}-{'' if end is None else end - 1}"
        response = self._client.get_object(Bucket=self.bucket, Key=storage_path, Range=range_header)
        yield from response["Body"].iter_chunks(chunk_size=64 * 1024)

    def size(self, storage_path: str) -> int:
        response = self._client.head_object(Bucket=self.bucket, Key=storage_path)
        return response["ContentLength"]

    def delete(self, storage_path: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=storage_path)
        local_path = self._download_cache_dir / storage_path
        if local_path.exists():
            local_path.unlink()


_storage_instance: AudioStorage | None = None


def get_storage() -> AudioStorage:
    global _storage_instance
    if _storage_instance is None:
        settings = get_settings()
        if settings.storage_backend == "local":
            _storage_instance = LocalFilesystemStorage()
        elif settings.storage_backend == "s3":
            _storage_instance = S3CompatibleStorage()
        else:
            raise ValueError(f"Unsupported STORAGE_BACKEND: {settings.storage_backend!r} (expected 'local' or 's3')")
    return _storage_instance
