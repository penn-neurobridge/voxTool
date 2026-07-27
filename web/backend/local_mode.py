"""Desktop (offline) mode support.

The cloud build keeps every scan inside ``backend/data`` and mirrors it to S3.
The desktop build instead opens a scan *in place* from anywhere on disk, the way
the legacy PyQt tool did, so a CT never gets copied out of wherever the lab keeps
it. Nothing here touches the network.

Two pieces make that work without changing the ~20 existing scan endpoints:

* a registry mapping the short name the UI passes around (``scan.nii.gz``) to the
  absolute path it was opened from, consulted by ``_scan_filepath``;
* a cache directory under the per-user application data folder, so the derived
  threshold-cloud JSON never lands next to the (possibly read-only) source scan.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading

_APP_NAME = "VoxTool"
_REGISTRY_FILE = "open_scans.json"
_MAX_RECENT = 50

_lock = threading.Lock()
_registry: dict[str, str] | None = None


def is_local_mode() -> bool:
    """True when running inside the desktop app rather than the cloud deployment."""
    return os.environ.get("VOXTOOL_LOCAL", "").lower() in ("1", "true", "yes")


def _preferred_data_dirs() -> list[str]:
    """Candidate locations for app state, best first."""
    override = os.environ.get("VOXTOOL_DATA_DIR")
    home = os.path.expanduser("~")

    if override:
        candidates = [override]
    elif sys.platform == "darwin":
        candidates = [os.path.join(home, "Library", "Application Support", _APP_NAME)]
    elif os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        candidates = [os.path.join(root, _APP_NAME)]
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        candidates = [os.path.join(root, _APP_NAME)]

    # Managed lab machines sometimes lock the conventional folder; a working app
    # with a fallback cache beats a crash on startup.
    candidates.append(os.path.join(home, f".{_APP_NAME.lower()}"))
    candidates.append(os.path.join(tempfile.gettempdir(), f"{_APP_NAME.lower()}-data"))
    return candidates


_resolved_data_dir: str | None = None


def app_data_dir() -> str:
    """Per-user writable directory, following each platform's convention."""
    global _resolved_data_dir
    if _resolved_data_dir is not None:
        return _resolved_data_dir

    errors = []
    for base in _preferred_data_dirs():
        try:
            os.makedirs(base, exist_ok=True)
            probe = os.path.join(base, ".write-test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
        except OSError as exc:
            errors.append(f"{base}: {exc}")
            continue
        if errors:
            print(
                f"VoxTool: using fallback data directory {base} "
                f"(tried {'; '.join(errors)})",
                file=sys.stderr,
            )
        _resolved_data_dir = base
        return base

    raise RuntimeError(
        "VoxTool could not find a writable data directory. Tried:\n  "
        + "\n  ".join(errors)
        + "\nSet VOXTOOL_DATA_DIR to a folder you can write to."
    )


def cache_dir() -> str:
    d = os.path.join(app_data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def _registry_path() -> str:
    return os.path.join(app_data_dir(), _REGISTRY_FILE)


def _load() -> dict[str, str]:
    global _registry
    if _registry is not None:
        return _registry
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            data = json.load(f)
        _registry = {
            str(k): str(v) for k, v in (data or {}).items() if isinstance(v, str)
        }
    except (OSError, ValueError):
        _registry = {}
    return _registry


def _save() -> None:
    reg = _load()
    tmp = _registry_path() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2)
        os.replace(tmp, _registry_path())
    except OSError:
        pass


def _unique_name(basename: str, abs_path: str, reg: dict[str, str]) -> str:
    """Keep the plain filename unless a different path already claimed it."""
    existing = reg.get(basename)
    if existing is None or os.path.normcase(existing) == os.path.normcase(abs_path):
        return basename

    # Same filename from a different folder: disambiguate with a short path hash
    # rather than a counter, so reopening the same file is stable across restarts.
    stem, ext = _split_nifti_ext(basename)
    tag = hashlib.sha1(os.path.dirname(abs_path).encode("utf-8")).hexdigest()[:6]
    return f"{stem}~{tag}{ext}"


#: Characters that change the meaning of a URL path segment. The scan name is
#: used as one (``/api/scans/<name>/snap``), and while browsers percent-encode
#: spaces for us, they treat "#" as a fragment and "?" as a query — so a file
#: called "scan #2.nii.gz" would silently 404. Substituted at registration.
_URL_UNSAFE = set('#?%\\/"<>|^`{}[]') | {chr(c) for c in range(0x20)}


def _url_safe(name: str) -> str:
    cleaned = "".join("_" if c in _URL_UNSAFE else c for c in name).strip()
    return cleaned or "scan.nii.gz"


def _split_nifti_ext(name: str) -> tuple[str, str]:
    lower = name.lower()
    if lower.endswith(".nii.gz"):
        return name[: -len(".nii.gz")], name[-len(".nii.gz") :]
    stem, ext = os.path.splitext(name)
    return stem, ext


def register_scan(abs_path: str) -> str:
    """Record an on-disk scan and return the short name the UI should use."""
    abs_path = os.path.abspath(os.path.expanduser(abs_path))
    with _lock:
        reg = _load()
        name = _unique_name(_url_safe(os.path.basename(abs_path)), abs_path, reg)
        reg[name] = abs_path
        if len(reg) > _MAX_RECENT:
            for stale in [k for k, v in reg.items() if not os.path.isfile(v)][
                : len(reg) - _MAX_RECENT
            ]:
                reg.pop(stale, None)
        _save()
    return name


def resolve(name: str) -> str | None:
    """Absolute path for a registered scan name, if it still exists on disk."""
    if not name:
        return None
    with _lock:
        path = _load().get(name)
    if path and os.path.isfile(path):
        return path
    return None


def unregister(name: str) -> None:
    """Forget a scan. Never deletes the user's file — desktop opens in place."""
    with _lock:
        if _load().pop(name, None) is not None:
            _save()


def registered_scans() -> list[str]:
    """Registered names whose files are still present, newest-modified first."""
    with _lock:
        items = list(_load().items())
    live = [(n, p) for n, p in items if os.path.isfile(p)]

    def mtime(pair):
        try:
            return os.path.getmtime(pair[1])
        except OSError:
            return 0.0

    return [n for n, _ in sorted(live, key=mtime, reverse=True)]


def scan_paths() -> dict[str, str]:
    with _lock:
        return dict(_load())


def cache_path_for(abs_path: str, threshold_pct: float) -> str:
    """Cache location for a scan's threshold cloud, inside the app data folder.

    Keyed on path plus size and mtime so that editing or replacing a scan at the
    same path can never silently serve a stale cloud.
    """
    abs_path = os.path.abspath(abs_path)
    try:
        st = os.stat(abs_path)
        stamp = f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        stamp = "0:0"
    digest = hashlib.sha1(
        f"{os.path.normcase(abs_path)}|{stamp}".encode("utf-8")
    ).hexdigest()[:12]
    stem, _ = _split_nifti_ext(os.path.basename(abs_path))
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)[:40]
    return os.path.join(cache_dir(), f"{safe}-{digest}.cloud_{threshold_pct:.4f}.json")
