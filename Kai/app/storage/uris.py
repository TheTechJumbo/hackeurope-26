"""URI-based file access helpers.

Supports per-file routing via URI schemes and a configurable base URI for
relative references.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class FileStorageSettings(BaseSettings):
    storage_base_uri: str = "storage/artifacts"
    storage_http_write_enabled: bool = False
    storage_http_write_method: str = "PUT"
    storage_http_timeout: float = 30.0
    model_config = {"env_file": ".env", "extra": "ignore"}


def _has_scheme(value: str) -> bool:
    return bool(urlparse(value).scheme)


def _normalize_uri(uri: str) -> str:
    if uri.startswith("local://"):
        return "file://" + uri[len("local://") :]
    if uri.startswith("local:"):
        return "file://" + uri[len("local:") :]
    return uri


def _join_uri(base: str, ref: str) -> str:
    if not base.endswith("/"):
        base = base + "/"
    return base + ref.lstrip("/")


def resolve_uri(ref: str) -> str:
    """Resolve a reference into a full URI.

    - If ref already has a scheme, it is returned (normalized).
    - Otherwise, it is resolved relative to STORAGE_BASE_URI.
    """
    if not ref:
        raise ValueError("ref must be a non-empty string")

    if _has_scheme(ref):
        return _normalize_uri(ref)

    settings = FileStorageSettings()
    base = settings.storage_base_uri.strip()
    if not base:
        raise ValueError("STORAGE_BASE_URI cannot be empty")

    if _has_scheme(base):
        return _join_uri(_normalize_uri(base), ref)

    base_path = Path(base).expanduser()
    if not base_path.is_absolute():
        base_path = (Path.cwd() / base_path).resolve()
    return (base_path / ref).resolve().as_uri()


def _local_path_from_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in ("", "file"):
        raise ValueError(f"Not a local file URI: {uri}")
    path = parsed.path if parsed.scheme == "file" else uri
    return Path(unquote(path))


def _guess_content_type(uri: str, path: Path | None = None) -> str | None:
    if path is None:
        parsed = urlparse(uri)
        candidate = parsed.path or uri
        path = Path(candidate)
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type


def read_bytes(ref_or_uri: str) -> bytes:
    uri = resolve_uri(ref_or_uri)
    parsed = urlparse(uri)

    if parsed.scheme in ("", "file"):
        path = _local_path_from_uri(uri)
        return path.read_bytes()

    if parsed.scheme in ("http", "https"):
        settings = FileStorageSettings()
        with httpx.Client(timeout=settings.storage_http_timeout, follow_redirects=True) as client:
            resp = client.get(uri)
            resp.raise_for_status()
            return resp.content

    if parsed.scheme == "s3":
        return _read_s3(uri)

    raise ValueError(f"Unsupported URI scheme: {parsed.scheme}")


def write_bytes(ref_or_uri: str, data: bytes, content_type: str | None = None) -> str:
    uri = resolve_uri(ref_or_uri)
    parsed = urlparse(uri)

    if parsed.scheme in ("", "file"):
        path = _local_path_from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return uri

    if parsed.scheme in ("http", "https"):
        settings = FileStorageSettings()
        if not settings.storage_http_write_enabled:
            raise RuntimeError("HTTP writes are disabled. Set STORAGE_HTTP_WRITE_ENABLED=true to enable.")
        method = settings.storage_http_write_method.upper().strip() or "PUT"
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        with httpx.Client(timeout=settings.storage_http_timeout, follow_redirects=True) as client:
            resp = client.request(method, uri, content=data, headers=headers)
            resp.raise_for_status()
        return uri

    if parsed.scheme == "s3":
        return _write_s3(uri, data, content_type)

    raise ValueError(f"Unsupported URI scheme: {parsed.scheme}")


def read_text(ref_or_uri: str, encoding: str = "utf-8") -> str:
    return read_bytes(ref_or_uri).decode(encoding)


def write_text(ref_or_uri: str, text: str, encoding: str = "utf-8") -> str:
    return write_bytes(ref_or_uri, text.encode(encoding), content_type="text/plain")


def get_metadata(ref_or_uri: str) -> dict[str, Any]:
    uri = resolve_uri(ref_or_uri)
    parsed = urlparse(uri)

    if parsed.scheme in ("", "file"):
        path = _local_path_from_uri(uri)
        size_bytes = path.stat().st_size if path.exists() else 0
        return {
            "uri": uri,
            "size_bytes": size_bytes,
            "content_type": _guess_content_type(uri, path),
        }

    if parsed.scheme in ("http", "https"):
        settings = FileStorageSettings()
        size_bytes = 0
        content_type = None
        try:
            with httpx.Client(timeout=settings.storage_http_timeout, follow_redirects=True) as client:
                resp = client.head(uri)
                if resp.status_code < 400:
                    content_type = resp.headers.get("Content-Type")
                    size = resp.headers.get("Content-Length")
                    if size:
                        try:
                            size_bytes = int(size)
                        except ValueError:
                            size_bytes = 0
        except Exception as exc:
            logger.debug("HEAD metadata lookup failed for %s: %s", uri, exc)
        return {
            "uri": uri,
            "size_bytes": size_bytes,
            "content_type": content_type,
        }

    if parsed.scheme == "s3":
        return _head_s3(uri)

    raise ValueError(f"Unsupported URI scheme: {parsed.scheme}")


def _get_s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for s3:// URIs. Install it to enable S3 support.") from exc
    return boto3.client("s3")


def _split_s3(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"Invalid s3 URI: {uri}")
    return bucket, key


def _read_s3(uri: str) -> bytes:
    client = _get_s3_client()
    bucket, key = _split_s3(uri)
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


def _write_s3(uri: str, data: bytes, content_type: str | None = None) -> str:
    client = _get_s3_client()
    bucket, key = _split_s3(uri)
    extra: dict[str, Any] = {}
    if content_type:
        extra["ContentType"] = content_type
    client.put_object(Bucket=bucket, Key=key, Body=data, **extra)
    return uri


def _head_s3(uri: str) -> dict[str, Any]:
    client = _get_s3_client()
    bucket, key = _split_s3(uri)
    resp = client.head_object(Bucket=bucket, Key=key)
    return {
        "uri": uri,
        "size_bytes": resp.get("ContentLength", 0),
        "content_type": resp.get("ContentType"),
    }
