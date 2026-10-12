"""Persist uploaded NIfTI scans (and cloud caches) in S3 so EB redeploys don't wipe them.

When DATA_S3_BUCKET is set (AWS EB), uploads are written to both local disk
(for fast processing) and S3. On a fresh instance, list/download pull from S3.
"""
from __future__ import annotations

import os
import logging

log = logging.getLogger(__name__)

_S3_PREFIX = "scans/"
_CLOUD_PREFIX = "cloud_caches/"


def _bucket() -> str:
    return (os.environ.get("DATA_S3_BUCKET") or "").strip()


def s3_enabled() -> bool:
    return bool(_bucket())


def _client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("s3", region_name=region)


def _key(filename: str) -> str:
    name = os.path.basename(filename)
    return f"{_S3_PREFIX}{name}"


def _cloud_key(cache_filename: str) -> str:
    return f"{_CLOUD_PREFIX}{os.path.basename(cache_filename)}"


def list_remote_scans() -> list[str] | None:
    """Return NIfTI filenames in S3, or None if S3 is not configured."""
    if not s3_enabled():
        return None
    try:
        client = _client()
        bucket = _bucket()
        out: list[str] = []
        token = None
        while True:
            kwargs = {"Bucket": bucket, "Prefix": _S3_PREFIX}
            if token:
                kwargs["ContinuationToken"] = token
            resp = client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents") or []:
                key = obj["Key"]
                name = (
                    key[len(_S3_PREFIX) :]
                    if key.startswith(_S3_PREFIX)
                    else os.path.basename(key)
                )
                lower = name.lower()
                if lower.endswith(".nii") or lower.endswith(".nii.gz"):
                    out.append(name)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return sorted(set(out))
    except Exception:
        log.exception("list_remote_scans failed")
        return None


def put_scan(local_path: str, filename: str) -> bool:
    """Upload a local file to S3. Returns True on success / skip."""
    if not s3_enabled():
        return True
    name = os.path.basename(filename)
    try:
        _client().upload_file(local_path, _bucket(), _key(name))
        log.info("uploaded %s to s3://%s/%s", name, _bucket(), _key(name))
        return True
    except Exception:
        log.exception("put_scan failed for %s", name)
        return False


def put_cloud_cache(local_cache_path: str) -> bool:
    """Persist a threshold-cloud JSON cache beside the scan in S3."""
    if not s3_enabled() or not os.path.isfile(local_cache_path):
        return True
    name = os.path.basename(local_cache_path)
    try:
        _client().upload_file(local_cache_path, _bucket(), _cloud_key(name))
        log.info("uploaded cloud cache %s", name)
        return True
    except Exception:
        log.exception("put_cloud_cache failed for %s", name)
        return False


def ensure_cloud_cache(local_cache_path: str) -> bool:
    """Ensure a local cloud-cache JSON exists (download from S3 if needed)."""
    if os.path.isfile(local_cache_path):
        return True
    if not s3_enabled():
        return False
    name = os.path.basename(local_cache_path)
    try:
        _client().download_file(_bucket(), _cloud_key(name), local_cache_path)
        return os.path.isfile(local_cache_path)
    except Exception:
        log.debug("ensure_cloud_cache miss for %s", name, exc_info=True)
        try:
            if os.path.isfile(local_cache_path):
                os.remove(local_cache_path)
        except OSError:
            pass
        return False


def ensure_local(filename: str, data_dir: str) -> str | None:
    """Ensure scan exists on local disk (download from S3 if needed)."""
    name = os.path.basename(filename)
    local = os.path.join(data_dir, name)
    if os.path.isfile(local):
        return local
    if not s3_enabled():
        return None
    try:
        _client().download_file(_bucket(), _key(name), local)
        log.info("downloaded %s from S3 → %s", name, local)
        return local if os.path.isfile(local) else None
    except Exception:
        log.exception("ensure_local failed for %s", name)
        try:
            if os.path.isfile(local):
                os.remove(local)
        except OSError:
            pass
        return None


def delete_scan(filename: str, data_dir: str) -> None:
    name = os.path.basename(filename)
    local = os.path.join(data_dir, name)
    if os.path.isfile(local):
        try:
            os.remove(local)
        except OSError:
            pass
    if not s3_enabled():
        return
    client = _client()
    bucket = _bucket()
    try:
        client.delete_object(Bucket=bucket, Key=_key(name))
    except Exception:
        log.exception("delete_scan S3 failed for %s", name)
    # Best-effort: remove common cloud-cache sidecars in S3.
    for pct in ("99.9600", "99.5000", "99.0000"):
        cache_name = f"{name}.cloud_{pct}.json"
        try:
            client.delete_object(Bucket=bucket, Key=_cloud_key(cache_name))
        except Exception:
            pass
        local_cache = local + f".cloud_{pct}.json"
        if os.path.isfile(local_cache):
            try:
                os.remove(local_cache)
            except OSError:
                pass
