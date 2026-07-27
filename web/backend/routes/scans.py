import heapq
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback

import numpy as np
from flask import Blueprint, send_file, send_from_directory, jsonify, current_app, request

import local_mode
from ct_cache import get_volume, volume_is_cached, warm_volume
from legacy_interpolator import interpolate_between_endpoints, lead_radius_mm
from scan_store import (
    delete_scan as s3_delete_scan,
    ensure_cloud_cache,
    ensure_local,
    list_remote_scans,
    put_cloud_cache,
    put_scan,
    s3_enabled,
)

scans_bp = Blueprint("scans", __name__)

NIFTI_EXTS = (".nii", ".nii.gz")


def _is_nifti(name: str) -> bool:
    return name.lower().endswith(NIFTI_EXTS)


def _scan_filepath(filename: str) -> str | None:
    """Resolve the name the UI uses to a readable path on disk.

    Desktop scans are registered by absolute path and read where they live, so
    they are checked first; anything else falls back to the managed data
    directory (pulling from S3 when the cloud deployment is configured).
    """
    name = filename or ""
    registered = local_mode.resolve(name)
    if registered:
        return registered
    data_dir = current_app.config["DATA_DIR"]
    return ensure_local(os.path.basename(name), data_dir)


def _volume_warm_enabled() -> bool:
    return os.environ.get("ENABLE_VOLUME_WARM", "").lower() in ("1", "true", "yes")


class _VoxelAccess:
    """Fast in-RAM voxel reads when warmed; otherwise mmap z-slabs."""

    def __init__(self, filepath: str):
        if volume_is_cached(filepath):
            vol = get_volume(filepath)
            self._data = vol.data
            self.affine = vol.affine
            self.shape = vol.data.shape
            self._slab = None
        else:
            dataobj, affine, shape = _open_scan_dataobj(filepath)
            self._data = None
            self.affine = affine
            self.shape = shape
            self._slab = _SlabCache(dataobj)

    def value(self, i: int, j: int, k: int) -> float:
        if self._data is not None:
            return float(self._data[i, j, k])
        return self._slab.value(i, j, k)


def _dilate_mask_26(mask: np.ndarray) -> np.ndarray:
    """Binary 26-neighbor dilation (connect tiny breaks in bright voxels)."""
    p = np.pad(mask, 1, mode="constant", constant_values=False)
    acc = np.zeros_like(mask, dtype=bool)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for dk in (-1, 0, 1):
                if di == 0 and dj == 0 and dk == 0:
                    continue
                s0 = slice(1 + di, 1 + di + mask.shape[0])
                s1 = slice(1 + dj, 1 + dj + mask.shape[1])
                s2 = slice(1 + dk, 1 + dk + mask.shape[2])
                acc |= p[s0, s1, s2]
    return mask | acc


def _nearest_true_voxel(mask: np.ndarray, i: int, j: int, k: int, max_radius: int | None = None):
    """Find the closest mask voxel to (i,j,k). Returns (idx_tuple, dist_voxels) or (None, inf)."""
    sx, sy, sz = mask.shape
    if 0 <= i < sx and 0 <= j < sy and 0 <= k < sz and mask[i, j, k]:
        return (i, j, k), 0.0
    pts = np.argwhere(mask)
    if pts.shape[0] == 0:
        return None, float("inf")
    d2 = np.sum((pts - np.array([i, j, k], dtype=np.int32)) ** 2, axis=1)
    idx = int(np.argmin(d2))
    dist = float(np.sqrt(d2[idx]))
    if max_radius is not None and dist > max_radius:
        return None, dist
    t = tuple(int(x) for x in pts[idx])
    return t, dist


def _step_cost_mm(affine: np.ndarray, di: int, dj: int, dk: int) -> float:
    d_phys = affine[0:3, 0:3] @ np.array([di, dj, dk], dtype=np.float64)
    return float(np.linalg.norm(d_phys))


def _voxel_to_mm(affine: np.ndarray, gi: int, gj: int, gk: int) -> np.ndarray:
    return (affine @ np.array([gi, gj, gk, 1.0], dtype=np.float64))[:3]


def _astar_on_mask(
    mask: np.ndarray,
    start_l: tuple,
    goal_l: tuple,
    affine: np.ndarray,
    offset: tuple,
    max_expansions: int = 350_000,
):
    """A* on 26-connected grid; coordinates are local ROI indices.

    offset: (i0, j0, k0) global = local + offset
    """
    sx, sy, sz = mask.shape
    if not (0 <= start_l[0] < sx and 0 <= start_l[1] < sy and 0 <= start_l[2] < sz):
        return None
    if not (0 <= goal_l[0] < sx and 0 <= goal_l[1] < sy and 0 <= goal_l[2] < sz):
        return None

    def loc_g(lidx):
        return (
            lidx[0] + offset[0],
            lidx[1] + offset[1],
            lidx[2] + offset[2],
        )

    gmm = _voxel_to_mm(affine, *loc_g(goal_l))

    def h_fun(lidx):
        p = _voxel_to_mm(affine, *loc_g(lidx))
        return float(np.linalg.norm(p - gmm))

    start_l, _ = _nearest_true_voxel(mask, *start_l)
    goal_l, _ = _nearest_true_voxel(mask, *goal_l)
    if start_l is None or goal_l is None:
        return None

    # neighbors
    neigh = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for dk in (-1, 0, 1):
                if di == 0 and dj == 0 and dk == 0:
                    continue
                neigh.append((di, dj, dk))

    came = {}
    gscore = {start_l: 0.0}
    heap = [(h_fun(start_l), 0.0, start_l)]
    expansions = 0

    while heap:
        _, g, cur = heapq.heappop(heap)
        expansions += 1
        if expansions > max_expansions:
            return None
        if g > gscore[cur]:
            continue
        if cur == goal_l:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return path

        ci, cj, ck = cur
        for di, dj, dk in neigh:
            ni, nj, nk = ci + di, cj + dj, ck + dk
            if not (0 <= ni < sx and 0 <= nj < sy and 0 <= nk < sz):
                continue
            if not mask[ni, nj, nk]:
                continue
            step = _step_cost_mm(affine, di, dj, dk)
            ng = g + step
            nb = (ni, nj, nk)
            if ng < gscore.get(nb, float("inf")):
                came[nb] = cur
                gscore[nb] = ng
                heapq.heappush(heap, (ng + h_fun(nb), ng, nb))
    return None


def _path_to_mm(vol, offset: tuple, path_l: list) -> np.ndarray:
    """Local ROI voxel path → Nx3 mm (use global integer voxel indices)."""
    i0, j0, k0 = offset
    out = []
    for li, lj, lk in path_l:
        gi, gj, gk = i0 + li, j0 + lj, k0 + lk
        out.append(vol.voxel_to_mm([gi, gj, gk])[:3])
    return np.asarray(out, dtype=np.float64)


def _resample_polyline_mm(path_mm: np.ndarray, t_values: list) -> list:
    if path_mm.shape[0] < 2:
        return []
    seg = np.linalg.norm(np.diff(path_mm, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total < 1e-6:
        return []
    out = []
    for t in t_values:
        d = float(t) * total
        idx = int(np.searchsorted(cum, d, side="right") - 1)
        idx = max(0, min(idx, path_mm.shape[0] - 2))
        seg_len = float(seg[idx])
        if seg_len < 1e-9:
            p = path_mm[idx]
        else:
            u = (d - float(cum[idx])) / seg_len
            p = path_mm[idx] * (1.0 - u) + path_mm[idx + 1] * u
        out.append(p.tolist())
    return out


@scans_bp.route("/<filename>", methods=["GET"])
def get_scan(filename):
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404
    # Desktop scans live outside the managed data directory, so stream by path.
    if os.path.dirname(os.path.abspath(filepath)) != os.path.abspath(data_dir):
        return send_file(
            filepath,
            mimetype="application/octet-stream",
            conditional=True,
            download_name=os.path.basename(filepath),
        )
    return send_from_directory(
        data_dir, os.path.basename(filepath), mimetype="application/octet-stream"
    )


@scans_bp.route("/", methods=["GET"])
def list_scans():
    data_dir = current_app.config["DATA_DIR"]
    local = {f for f in os.listdir(data_dir) if _is_nifti(f)}

    if local_mode.is_local_mode():
        # Recently opened files first — they are what the user actually works on.
        recent = local_mode.registered_scans()
        return jsonify(recent + sorted(local - set(recent)))

    remote = list_remote_scans()
    if remote is not None:
        files = sorted(local | set(remote))
    else:
        files = sorted(local)
    return jsonify(files)


@scans_bp.route("/open_local", methods=["POST"])
def open_local_scan():
    """Open a scan in place from an absolute path (desktop only).

    Mirrors the legacy PyQt "Load Scan" flow: the CT is read where it already
    lives instead of being copied into the app, so there is no size ceiling and
    no second copy of patient data.

    Body: { path: "/abs/path/to/scan.nii.gz" }
    """
    if not local_mode.is_local_mode():
        return jsonify({"success": False, "error": "not available in cloud mode"}), 403

    body = request.get_json(silent=True) or {}
    raw = (body.get("path") or "").strip()
    if not raw:
        return jsonify({"success": False, "error": "path is required"}), 400

    path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.isfile(path):
        return jsonify({"success": False, "error": f"No such file: {path}"}), 404
    if not _is_nifti(path):
        return jsonify(
            {"success": False, "error": "file must end with .nii or .nii.gz"}
        ), 400
    if not os.access(path, os.R_OK):
        return jsonify({"success": False, "error": f"File is not readable: {path}"}), 403

    name = local_mode.register_scan(path)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    cloud_ready = os.path.isfile(_cloud_cache_path(path, 99.96))

    return jsonify(
        {
            "success": True,
            "filename": name,
            "path": path,
            "size_mb": round(size_mb, 1),
            "cloud_ready": cloud_ready,
        }
    )


@scans_bp.route("/upload", methods=["POST"])
def upload_scan():
    """Upload a NIfTI volume into the server data directory (and S3 when configured)."""
    data_dir = current_app.config["DATA_DIR"]
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"success": False, "error": "file is required"}), 400

    name = os.path.basename(upload.filename)
    lower = name.lower()
    if not (lower.endswith(".nii") or lower.endswith(".nii.gz")):
        return jsonify(
            {"success": False, "error": "filename must end with .nii or .nii.gz"}
        ), 400

    dest = os.path.join(data_dir, name)
    upload.save(dest)
    size_mb = os.path.getsize(dest) / (1024 * 1024)

    # Persist so EB redeploys do not wipe the scan.
    s3_ok = put_scan(dest, name)
    if s3_enabled() and not s3_ok:
        return jsonify(
            {
                "success": False,
                "error": "Saved on instance but failed to persist to S3 — try again.",
            }
        ), 500

    cloud_ready = _install_bundled_cloud_cache(dest, 99.96)
    if not cloud_ready:
        _warm_cloud_cache_async(dest, 99.96)

    # Volume preload happens when the cloud tab calls /warm_volume (avoids OOM during upload).

    return jsonify(
        {
            "success": True,
            "filename": name,
            "size_mb": round(size_mb, 1),
            "cloud_ready": cloud_ready,
            "cloud_warming": not cloud_ready,
            "persisted": s3_enabled(),
        }
    )


@scans_bp.route("/<filename>", methods=["DELETE"])
def delete_scan(filename):
    """Remove an uploaded NIfTI (local + S3) and side-car cloud cache files."""
    data_dir = current_app.config["DATA_DIR"]
    name = os.path.basename(filename or "")
    if not _is_nifti(name):
        return jsonify({"success": False, "error": "invalid filename"}), 400

    # A scan opened in place belongs to the user, not to us: close it and drop the
    # derived cache, but never touch the original file on their disk.
    if local_mode.is_local_mode():
        path = local_mode.resolve(name)
        if path:
            for pct in (99.96, 99.5, 99.0):
                base = local_mode.cache_path_for(path, pct)
                for side in (base, base + ".log", base + ".building"):
                    if os.path.isfile(side):
                        try:
                            os.remove(side)
                        except OSError:
                            pass
            local_mode.unregister(name)
            return jsonify({"success": True, "filename": name, "closed": True})

    path = _scan_filepath(name)
    remote = list_remote_scans() or []
    if not path and name not in remote:
        return jsonify({"success": False, "error": f"Scan '{name}' not found"}), 404

    # Clear associated cache / log sidecars so they don't linger.
    if path:
        for suffix in (
            ".cloud_99.9600.json",
            ".cloud_99.9600.json.log",
            ".cloud_99.5.json",
            ".cloud_99.5.json.log",
        ):
            side = path + suffix
            if os.path.isfile(side):
                try:
                    os.remove(side)
                except OSError:
                    pass

    s3_delete_scan(name, data_dir)
    return jsonify({"success": True, "filename": name})


@scans_bp.route("/<filename>/range", methods=["GET"])
def intensity_range(filename):
    """Return p1/p99 percentile intensity range for the Auto windowing preset."""
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404
    vol = get_volume(filepath)
    p1, p99 = np.percentile(vol.data, [1, 99])
    return jsonify({"p1": float(p1), "p99": float(p99)})


def _scan_vol(filepath: str, threshold_pct: float = 99.96):
    """Light handle when cloud cache exists (Render); full volume otherwise (local)."""
    _install_bundled_cloud_cache(filepath, threshold_pct)
    if os.path.isfile(_cloud_cache_path(filepath, threshold_pct)):
        return LightScanVol(filepath, threshold_pct)
    return get_volume(filepath)


@scans_bp.route("/<filename>/snap", methods=["POST"])
def snap(filename):
    """Snap a clicked mm coordinate to the centroid of nearby super-threshold voxels.

    Body: { point_mm: [r, a, s], radius_mm?: 4, threshold_pct?: 99.96, iterations?: 2 }
    Returns: { center_mm: [r, a, s], voxel_count: N, success: bool }
    """
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(force=True)
    point_mm = body.get("point_mm")
    if not point_mm or len(point_mm) != 3:
        return jsonify({"error": "point_mm [r,a,s] is required"}), 400

    radius_mm = float(body.get("radius_mm", 3.0))
    threshold_pct = float(body.get("threshold_pct", 99.96))
    iterations = int(body.get("iterations", 2))

    vol = _scan_vol(filepath, threshold_pct)
    points = vol.points_above_threshold(threshold_pct)
    if points.shape[0] == 0:
        return jsonify({"success": False, "voxel_count": 0, "center_mm": point_mm})

    # Convert click mm to voxel space, and convert radius_mm to voxel-space radius
    # using the average voxel scale from the affine.
    click_vox = vol.mm_to_voxel(point_mm)
    voxel_scale = float(np.mean(np.abs(np.diag(vol.affine[:3, :3]))))
    radius_vox = radius_mm / max(voxel_scale, 1e-6)

    current = np.array(click_vox, dtype=np.float32)
    nearby_count = 0
    for _ in range(max(1, iterations)):
        diffs = points - current
        dists2 = np.sum(diffs * diffs, axis=1)
        mask = dists2 <= (radius_vox * radius_vox)
        nearby = points[mask]
        if nearby.shape[0] == 0:
            break
        current = nearby.mean(axis=0)
        nearby_count = int(nearby.shape[0])

    if nearby_count == 0:
        return jsonify({"success": False, "voxel_count": 0, "center_mm": point_mm})

    center_mm = vol.voxel_to_mm(current).tolist()
    shape = vol.data.shape
    cv = np.round(current).astype(int)
    cv = np.clip(cv, [0, 0, 0], np.array(shape) - 1)
    center_voxel = [int(cv[0]), int(cv[1]), int(cv[2])]
    return jsonify(
        {
            "success": True,
            "voxel_count": nearby_count,
            "center_mm": [round(float(c), 2) for c in center_mm],
            "center_voxel": center_voxel,
        }
    )


def _voxel_spacing_mm(affine: np.ndarray) -> list:
    R = affine[:3, :3]
    return [
        float(np.linalg.norm(R[:, 0])),
        float(np.linalg.norm(R[:, 1])),
        float(np.linalg.norm(R[:, 2])),
    ]


def _percentile_thr_from_dataobj(dataobj, nz: int, pct: float, seed: int = 0) -> float:
    """Percentile from z-slab samples — never loads the full volume into RAM."""
    target = 2_000_000
    nz = int(nz)
    slices_to_sample = min(nz, 80)
    rng = np.random.default_rng(seed)
    ks = (
        rng.choice(nz, size=slices_to_sample, replace=False)
        if nz > slices_to_sample
        else np.arange(nz)
    )
    chunks: list[np.ndarray] = []
    per_slice = max(1, target // len(ks))
    for k in ks:
        slab = np.asarray(dataobj[:, :, int(k)], dtype=np.float32).ravel()
        step = max(1, slab.size // per_slice)
        chunks.append(slab[::step])
    return float(np.percentile(np.concatenate(chunks), pct))


def _indices_above_thr_from_dataobj(
    dataobj, nz: int, thr: float, excluded: set | None
) -> tuple[np.ndarray, int]:
    """Collect super-threshold voxel indices one z-slab at a time (low peak RAM)."""
    chunks: list[np.ndarray] = []
    total = 0
    for k in range(int(nz)):
        slab = np.asarray(dataobj[:, :, k], dtype=np.float32)
        ij = np.argwhere(slab >= thr)
        if ij.size == 0:
            continue
        pts = np.empty((len(ij), 3), dtype=np.int32)
        pts[:, 0] = ij[:, 0]
        pts[:, 1] = ij[:, 1]
        pts[:, 2] = k
        if excluded:
            mask = [
                (int(p[0]), int(p[1]), int(p[2])) not in excluded for p in pts
            ]
            pts = pts[np.asarray(mask, dtype=bool)]
        if len(pts):
            chunks.append(pts)
            total += len(pts)
    if not chunks:
        return np.empty((0, 3), dtype=np.int32), 0
    return np.vstack(chunks), total


def _excluded_set(excluded):
    ex = set()
    for triplet in excluded or []:
        if isinstance(triplet, (list, tuple)) and len(triplet) == 3:
            ex.add((int(triplet[0]), int(triplet[1]), int(triplet[2])))
    return ex


def _cloud_cache_path(filepath: str, threshold_pct: float) -> str:
    # Desktop keeps derived data in the app folder: the scan's own directory may
    # be read-only or on a share the lab does not want written to.
    if local_mode.is_local_mode():
        return local_mode.cache_path_for(filepath, threshold_pct)
    return f"{filepath}.cloud_{threshold_pct:.4f}.json"


def _bundled_cloud_cache_path(filename: str, threshold_pct: float) -> str:
    bundled_dir = current_app.config.get("BUNDLED_CLOUD_DIR")
    if not bundled_dir:
        return ""
    return os.path.join(bundled_dir, f"{filename}.cloud_{threshold_pct:.4f}.json")


def _install_bundled_cloud_cache(filepath: str, threshold_pct: float = 99.96) -> bool:
    """Use local / S3 / bundled cloud JSON if available (instant cloud load)."""
    cache_path = _cloud_cache_path(filepath, threshold_pct)
    if os.path.isfile(cache_path):
        return True
    if ensure_cloud_cache(cache_path):
        return True

    bundled = _bundled_cloud_cache_path(os.path.basename(filepath), threshold_pct)
    if not bundled or not os.path.isfile(bundled):
        return False

    shutil.copy2(bundled, cache_path)
    lock_path = cache_path + ".building"
    try:
        os.remove(lock_path)
    except OSError:
        pass
    put_cloud_cache(cache_path)
    return True


_DATAOBJ_CACHE: dict[str, tuple] = {}


def _open_scan_dataobj(filepath: str):
    import nibabel as nib

    abs_path = os.path.abspath(filepath)
    cached = _DATAOBJ_CACHE.get(abs_path)
    if cached is not None:
        return cached

    img = nib.load(filepath)
    dataobj = img.dataobj
    if dataobj.ndim == 4 and dataobj.shape[3] == 1:
        dataobj = dataobj[:, :, :, 0]
    affine = img.affine.astype(np.float64)
    shape = tuple(int(x) for x in dataobj.shape[:3])
    result = (dataobj, affine, shape)
    _DATAOBJ_CACHE[abs_path] = result
    return result


class _ShapeProxy:
    """Mimics vol.data.shape for legacy_interpolator without loading the volume."""

    def __init__(self, shape: tuple[int, int, int]):
        self.shape = shape


class LightScanVol:
    """Low-RAM volume handle: header + cached threshold points (Render-safe)."""

    def __init__(self, filepath: str, threshold_pct: float = 99.96):
        self.filepath = os.path.abspath(filepath)
        _, self.affine, shape = _open_scan_dataobj(filepath)
        self.inv_affine = np.linalg.inv(self.affine)
        self.data = _ShapeProxy(shape)
        self._threshold_pct = threshold_pct
        self._threshold_points: np.ndarray | None = None

    def points_above_threshold(self, threshold_pct: float) -> np.ndarray:
        if self._threshold_points is not None:
            return self._threshold_points
        _install_bundled_cloud_cache(self.filepath, threshold_pct)
        cache_path = _cloud_cache_path(self.filepath, threshold_pct)
        with open(cache_path, encoding="utf-8") as f:
            pts = json.load(f).get("points") or []
        self._threshold_points = np.asarray(pts, dtype=np.float32)
        return self._threshold_points

    def mm_to_voxel(self, mm):
        mm_h = np.array([mm[0], mm[1], mm[2], 1.0], dtype=np.float64)
        return (self.inv_affine @ mm_h)[:3]

    def voxel_to_mm(self, vox):
        vox_h = np.array([vox[0], vox[1], vox[2], 1.0], dtype=np.float64)
        return (self.affine @ vox_h)[:3]


class _SlabCache:
    """Load each z-slab once during BFS (fast on gzip without full-volume RAM)."""

    def __init__(self, dataobj):
        self.dataobj = dataobj
        self._slabs: dict[int, np.ndarray] = {}

    def value(self, i: int, j: int, k: int) -> float:
        slab = self._slabs.get(k)
        if slab is None:
            slab = np.asarray(self.dataobj[:, :, k], dtype=np.float32)
            self._slabs[k] = slab
        return float(slab[i, j])


def _warm_volume_async(filepath: str) -> None:
    """Preload float32 CT in this worker (matches local snap/pick; ~30s once on Render)."""
    if volume_is_cached(filepath):
        return
    app = current_app._get_current_object()

    def _run():
        try:
            with app.app_context():
                if not volume_is_cached(filepath):
                    warm_volume(filepath)
        except Exception:
            app.logger.exception("background volume warm failed")

    threading.Thread(target=_run, daemon=True).start()


def _cached_cloud_threshold(filepath: str, threshold_pct: float) -> float | None:
    _install_bundled_cloud_cache(filepath, threshold_pct)
    cache_path = _cloud_cache_path(filepath, threshold_pct)
    if not os.path.isfile(cache_path):
        return None
    with open(cache_path, encoding="utf-8") as f:
        thr = json.load(f).get("intensity_threshold")
    return float(thr) if thr is not None else None


def _threshold_for_pick(filepath: str, threshold_pct: float, body: dict | None = None) -> float:
    if body and body.get("intensity_threshold") is not None:
        return float(body["intensity_threshold"])
    thr = _cached_cloud_threshold(filepath, threshold_pct)
    if thr is not None:
        return thr
    dataobj, _, shape = _open_scan_dataobj(filepath)
    return _percentile_thr_from_dataobj(dataobj, shape[2], threshold_pct)


def _build_threshold_cloud_payload(
    filepath: str,
    threshold_pct: float,
    max_points: int = 400_000,
    seed: int = 0,
    excluded: list | None = None,
) -> dict:
    # Prefer in-RAM volume when warmed — much faster than per-slab NIfTI reads.
    if volume_is_cached(filepath):
        vol = get_volume(filepath)
        data = vol.data
        affine = vol.affine.astype(np.float64)
        shape = [int(x) for x in data.shape[:3]]
        flat = data.ravel()
        rng = np.random.default_rng(seed)
        if flat.size > 2_000_000:
            sample = flat[rng.choice(flat.size, size=2_000_000, replace=False)]
            thr = float(np.percentile(sample, threshold_pct))
        else:
            thr = float(np.percentile(flat, threshold_pct))
        mask = data >= thr
        if excluded:
            ex = _excluded_set(excluded)
            for i, j, k in ex:
                if 0 <= i < shape[0] and 0 <= j < shape[1] and 0 <= k < shape[2]:
                    mask[i, j, k] = False
        idx = np.column_stack(np.where(mask)).astype(np.int32)
        total = int(idx.shape[0])
        if total == 0:
            return {
                "success": True,
                "points": [],
                "intensity_threshold": thr,
                "threshold_pct": threshold_pct,
                "total_voxels": 0,
                "returned": 0,
                "shape": shape,
                "voxel_spacing_mm": _voxel_spacing_mm(affine),
            }
        if total > max_points:
            pick = rng.choice(total, size=max_points, replace=False)
            idx = idx[pick]
        return {
            "success": True,
            "points": idx.tolist(),
            "intensity_threshold": thr,
            "threshold_pct": threshold_pct,
            "total_voxels": total,
            "returned": int(idx.shape[0]),
            "shape": shape,
            "voxel_spacing_mm": _voxel_spacing_mm(affine),
        }

    import nibabel as nib

    img = nib.load(filepath)
    dataobj = img.dataobj
    if dataobj.ndim == 4 and dataobj.shape[3] == 1:
        dataobj = dataobj[:, :, :, 0]
    affine = img.affine.astype(np.float64)
    shape = [int(x) for x in dataobj.shape[:3]]
    nz = shape[2]

    thr = _percentile_thr_from_dataobj(dataobj, nz, threshold_pct, seed=seed)
    ex = _excluded_set(excluded)
    idx, total = _indices_above_thr_from_dataobj(dataobj, nz, thr, ex if ex else None)

    if total == 0:
        return {
            "success": True,
            "points": [],
            "intensity_threshold": thr,
            "threshold_pct": threshold_pct,
            "total_voxels": 0,
            "returned": 0,
            "shape": shape,
            "voxel_spacing_mm": _voxel_spacing_mm(affine),
        }

    if total > max_points:
        rng = np.random.default_rng(seed)
        pick = rng.choice(total, size=max_points, replace=False)
        idx = idx[pick]

    points = idx.astype(np.int32).tolist()
    return {
        "success": True,
        "points": points,
        "intensity_threshold": thr,
        "threshold_pct": threshold_pct,
        "total_voxels": total,
        "returned": len(points),
        "shape": shape,
        "voxel_spacing_mm": _voxel_spacing_mm(affine),
    }


def _write_threshold_cloud_cache(filepath: str, threshold_pct: float) -> dict:
    payload = _build_threshold_cloud_payload(filepath, threshold_pct)
    cache_path = _cloud_cache_path(filepath, threshold_pct)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    put_cloud_cache(cache_path)
    return payload


def _build_cloud_cache_to(filepath: str, threshold_pct: float, cache_path: str) -> None:
    """Build one threshold-cloud cache. Safe to run off the request thread."""
    lock_path = cache_path + ".building"
    try:
        with open(lock_path, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        payload = _build_threshold_cloud_payload(filepath, threshold_pct)
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, cache_path)
    except Exception:
        log_path = cache_path + ".log"
        try:
            with open(log_path, "a", encoding="utf-8") as log:
                traceback.print_exc(file=log)
        except OSError:
            pass
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass


def _warm_cloud_cache_async(filepath: str, threshold_pct: float = 99.96) -> None:
    """Kick off a cloud-cache build in the background."""
    cache_path = _cloud_cache_path(filepath, threshold_pct)
    lock_path = cache_path + ".building"
    if os.path.isfile(cache_path) or os.path.isfile(lock_path):
        return

    # A thread is enough on the desktop: there is no gunicorn worker recycling to
    # kill it, and a frozen build has no interpreter to re-invoke as a subprocess.
    if local_mode.is_local_mode():
        threading.Thread(
            target=_build_cloud_cache_to,
            args=(filepath, threshold_pct, cache_path),
            daemon=True,
        ).start()
        return

    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "warm_cloud.py")
    script = os.path.abspath(script)

    log_path = cache_path + ".log"
    with open(log_path, "ab") as log:
        subprocess.Popen(
            [sys.executable, script, filepath, str(threshold_pct)],
            cwd=os.path.dirname(script),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )


@scans_bp.route("/<filename>/warm_cloud", methods=["POST"])
def warm_cloud(filename):
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(silent=True) or {}
    threshold_pct = float(body.get("threshold_pct", 99.96))
    if _install_bundled_cloud_cache(filepath, threshold_pct):
        if _volume_warm_enabled():
            _warm_volume_async(filepath)
        return jsonify({"warming": False, "ready": True, "threshold_pct": threshold_pct})

    cache_path = _cloud_cache_path(filepath, threshold_pct)
    if os.path.isfile(cache_path):
        if _volume_warm_enabled():
            _warm_volume_async(filepath)
        return jsonify({"warming": False, "ready": True, "threshold_pct": threshold_pct})

    _warm_cloud_cache_async(filepath, threshold_pct)
    if _volume_warm_enabled():
        _warm_volume_async(filepath)
    return jsonify({"warming": True, "ready": False, "threshold_pct": threshold_pct})


@scans_bp.route("/<filename>/cloud_ready", methods=["GET"])
def cloud_ready(filename):
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"ready": False, "error": f"Scan '{filename}' not found"}), 404

    threshold_pct = float(request.args.get("threshold_pct", 99.96))
    _install_bundled_cloud_cache(filepath, threshold_pct)
    cache_path = _cloud_cache_path(filepath, threshold_pct)
    lock_path = cache_path + ".building"
    ready = os.path.isfile(cache_path)
    building = os.path.isfile(lock_path)
    if building and not ready:
        age = time.time() - os.path.getmtime(lock_path)
        if age > 900:
            try:
                os.remove(lock_path)
            except OSError:
                pass
            building = False
    return jsonify({"ready": ready, "building": building, "threshold_pct": threshold_pct})


@scans_bp.route("/<filename>/threshold_cloud", methods=["POST"])
def threshold_cloud(filename):
    """Sparse super-threshold voxels as integer [i,j,k] indices (numpy / nibabel order).

    Body: {
      threshold_pct: float,
      max_points?: int (default 400000),
      seed?: int (default 0),
      excluded_voxels?: [[i,j,k], ...]
    }
    """
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(force=True) or {}
    threshold_pct = float(body.get("threshold_pct", 99.5))
    max_points = int(body.get("max_points", 400_000))
    seed = int(body.get("seed", 0))
    excluded = body.get("excluded_voxels") or []

    if not (0 < threshold_pct <= 100):
        return jsonify({"error": "threshold_pct must be in (0, 100]"}), 400

    _install_bundled_cloud_cache(filepath, threshold_pct)

    cache_path = _cloud_cache_path(filepath, threshold_pct)
    if not excluded and os.path.isfile(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            payload = json.load(f)
        points = payload.get("points") or []
        total = int(payload.get("total_voxels") or len(points))
        if total > max_points and len(points) > max_points:
            rng = np.random.default_rng(seed)
            pick = rng.choice(len(points), size=max_points, replace=False)
            points = [points[i] for i in pick]
        payload["points"] = points
        payload["returned"] = len(points)
        return jsonify(payload)

    # Never block HTTP for minutes building a new threshold — CloudFront dies at ~60s.
    # Kick async build (+ volume warm) and tell the client to poll cloud_ready.
    if not excluded:
        if _volume_warm_enabled():
            _warm_volume_async(filepath)
        _warm_cloud_cache_async(filepath, threshold_pct)
        return (
            jsonify(
                {
                    "success": False,
                    "building": True,
                    "ready": False,
                    "threshold_pct": threshold_pct,
                    "message": "Cloud cache is building — poll cloud_ready then retry.",
                }
            ),
            202,
        )

    payload = _build_threshold_cloud_payload(
        filepath, threshold_pct, max_points=max_points, seed=seed, excluded=excluded
    )
    return jsonify(payload)


@scans_bp.route("/<filename>/warm_volume", methods=["POST"])
def warm_volume_route(filename):
    """Preload float32 CT into worker RAM when ENABLE_VOLUME_WARM is set (AWS EB)."""
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    if not _volume_warm_enabled():
        return jsonify({"ready": True, "warming": False, "skipped": True})

    if volume_is_cached(filepath):
        return jsonify({"ready": True, "warming": False, "skipped": False})

    _warm_volume_async(filepath)
    return jsonify({"ready": False, "warming": True, "skipped": False})


@scans_bp.route("/<filename>/volume_ready", methods=["GET"])
def volume_ready_route(filename):
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"ready": False, "error": f"Scan '{filename}' not found"}), 404

    return jsonify({"ready": volume_is_cached(filepath)})


@scans_bp.route("/<filename>/bright_component", methods=["POST"])
def bright_component(filename):
    """Legacy-style contact pick: sphere on the threshold *point cloud*.

    Body: {
      seed_voxel: [i,j,k],
      threshold_pct: float,
      excluded_voxels?: [[i,j,k], ...],
      max_voxels?: int (default 12000, safety cap),
      max_ball_mm?: float (default 3) — lead radius in mm (config.yml D/G=3, S=5),
      selection_iterations?: int (default 2) — config.yml selection_iterations
    }

    Mirrors desktop select_points_near + center_selection: take only
    super-threshold cloud points inside a Euclidean ball and recenter a few
    times. That gives compact, consistent contact-sized blobs — denser than a
    single voxel, but much smaller than selecting every bright *volume* voxel
    inside the same radius (which looked too big on AWS).
    """
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(force=True) or {}
    seed = body.get("seed_voxel")
    if not seed or len(seed) != 3:
        return jsonify({"success": False, "error": "seed_voxel [i,j,k] required"}), 400

    threshold_pct = float(body.get("threshold_pct", 99.96))
    max_voxels = int(body.get("max_voxels", 12_000))
    excluded = body.get("excluded_voxels") or []
    # Legacy depth/grid default is 3 mm (config.yml), not 6.
    max_ball_mm = float(body.get("max_ball_mm", 3.0))
    selection_iterations = int(body.get("selection_iterations", 2))

    if not (0 < threshold_pct <= 100):
        return jsonify({"success": False, "error": "threshold_pct must be in (0, 100]"}), 400

    _, affine, shape = _open_scan_dataobj(filepath)
    si, sj, sk = int(seed[0]), int(seed[1]), int(seed[2])
    if not (0 <= si < shape[0] and 0 <= sj < shape[1] and 0 <= sk < shape[2]):
        return jsonify({"success": False, "error": "seed_voxel out of bounds"}), 400

    thr = _threshold_for_pick(filepath, threshold_pct, body)
    ex_set = _excluded_set(excluded)
    M = affine[:3, :3]
    radius_mm = max_ball_mm if max_ball_mm > 0 else 3.0
    r_sq = radius_mm * radius_mm

    # Prefer the threshold point cloud (legacy CT point cloud). Fall back to a
    # local volume search only when the cloud isn't available yet.
    _install_bundled_cloud_cache(filepath, threshold_pct)
    cache_path = _cloud_cache_path(filepath, threshold_pct)
    cand = None
    source = "volume"
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                pts = json.load(f).get("points") or []
            if pts:
                cand = np.asarray(pts, dtype=np.float64)
                source = "cloud"
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            cand = None

    if cand is None or cand.size == 0:
        vox = _VoxelAccess(filepath)
        axis_mm = np.sqrt((M * M).sum(axis=0))
        axis_mm = np.where(axis_mm > 1e-6, axis_mm, 1.0)
        box_rad = np.ceil((2.0 * radius_mm) / axis_mm).astype(int) + 1
        i0, i1 = max(0, si - int(box_rad[0])), min(shape[0], si + int(box_rad[0]) + 1)
        j0, j1 = max(0, sj - int(box_rad[1])), min(shape[1], sj + int(box_rad[1]) + 1)
        k0, k1 = max(0, sk - int(box_rad[2])), min(shape[2], sk + int(box_rad[2]) + 1)
        if getattr(vox, "_data", None) is not None:
            sub = np.asarray(vox._data[i0:i1, j0:j1, k0:k1], dtype=np.float32)
            ii, jj, kk = np.where(sub >= thr)
            cand = np.column_stack((ii + i0, jj + j0, kk + k0)).astype(np.float64)
        else:
            candidates = []
            for i in range(i0, i1):
                for j in range(j0, j1):
                    for k in range(k0, k1):
                        if (i, j, k) in ex_set:
                            continue
                        if vox.value(i, j, k) >= thr:
                            candidates.append((i, j, k))
            cand = np.asarray(candidates, dtype=np.float64)

    if cand is None or cand.size == 0:
        return jsonify({"success": False, "error": "empty_component"}), 400

    if ex_set and source == "cloud":
        keep = np.array(
            [(int(a), int(b), int(c)) not in ex_set for a, b, c in cand],
            dtype=bool,
        )
        if keep.any():
            cand = cand[keep]

    # Legacy: select_points_near then center_selection(selection_iterations).
    center = np.array([si, sj, sk], dtype=np.float64)
    inside = None
    n_iter = max(1, selection_iterations)
    for _ in range(n_iter):
        delta = cand - center
        mm_vec = delta @ M.T
        dist_sq = (mm_vec * mm_vec).sum(axis=1)
        inside = dist_sq <= r_sq
        if inside.any():
            center = cand[inside].mean(axis=0)
        else:
            break

    if inside is None or not inside.any():
        # Seed was a cloud click; keep at least the seed so UI has a blob.
        component = [[si, sj, sk]]
    else:
        sel = cand[inside]
        if len(sel) > max_voxels:
            # Keep the closest points to the final center rather than an arbitrary slice.
            delta = sel - center
            mm_vec = delta @ M.T
            order = np.argsort((mm_vec * mm_vec).sum(axis=1))
            sel = sel[order[:max_voxels]]
        component = [[int(round(v[0])), int(round(v[1])), int(round(v[2]))] for v in sel]

    arr = np.asarray(component, dtype=np.float64)
    cen = np.round(arr.mean(axis=0)).astype(int)
    cen = np.clip(cen, [0, 0, 0], np.array(shape) - 1)
    centroid_voxel = [int(cen[0]), int(cen[1]), int(cen[2])]
    mm = _voxel_to_mm(affine, *centroid_voxel).tolist()

    return jsonify(
        {
            "success": True,
            "voxels": component,
            "count": len(component),
            "centroid_voxel": centroid_voxel,
            "centroid_mm": [round(float(x), 2) for x in mm],
            "intensity_threshold": thr,
            "capped": len(component) >= max_voxels,
            "max_ball_mm": radius_mm,
            "selection_iterations": n_iter,
            "source": source,
        }
    )


@scans_bp.route("/<filename>/orientation", methods=["GET"])
def orientation(filename):
    """Anatomical axis directions (R/A/S/L/P/I) as unit vectors in cloud scene space.

    The cloud renders voxel (i,j,k) at (i*sx, j*sy, k*sz) where sx/sy/sz are the
    voxel spacings (norms of the affine columns). To place R/A/S/L/P/I labels the
    way the desktop tool does, we map each RAS direction into that scaled voxel
    space: scene_from_ras = diag(spacing) @ inv(affine[:3,:3]).
    """
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    _, affine, _ = _open_scan_dataobj(filepath)
    R3 = affine[:3, :3]
    spacing = np.array(_voxel_spacing_mm(affine), dtype=np.float64)
    scene_from_ras = np.diag(spacing) @ np.linalg.inv(R3)

    def dir_for(ras_vec):
        v = scene_from_ras @ np.asarray(ras_vec, dtype=np.float64)
        n = float(np.linalg.norm(v))
        if n < 1e-9:
            return [0.0, 0.0, 0.0]
        return [float(x) for x in (v / n)]

    return jsonify(
        {
            "R": dir_for([1, 0, 0]),
            "L": dir_for([-1, 0, 0]),
            "A": dir_for([0, 1, 0]),
            "P": dir_for([0, -1, 0]),
            "S": dir_for([0, 0, 1]),
            "I": dir_for([0, 0, -1]),
        }
    )


@scans_bp.route("/<filename>/mm_to_voxel", methods=["POST"])
def mm_to_voxel_endpoint(filename):
    """Map RAS mm → integer voxel index (rounded, clipped to volume)."""
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(force=True) or {}
    point_mm = body.get("point_mm")
    if not point_mm or len(point_mm) != 3:
        return jsonify({"error": "point_mm [r,a,s] is required"}), 400

    vol = _scan_vol(filepath, 99.96)
    v = np.asarray(vol.mm_to_voxel(point_mm)[:3], dtype=float)
    shape = vol.data.shape
    vi = np.round(v).astype(int)
    vi = np.clip(vi, [0, 0, 0], np.array(shape) - 1)
    return jsonify({"voxel": [int(vi[0]), int(vi[1]), int(vi[2])]})


@scans_bp.route("/<filename>/voxel_to_mm", methods=["POST"])
def voxel_to_mm_endpoint(filename):
    """Integer voxel [i,j,k] → RAS mm (voxel centre)."""
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(force=True) or {}
    voxel = body.get("voxel")
    if not voxel or len(voxel) != 3:
        return jsonify({"error": "voxel [i,j,k] is required"}), 400

    _, affine, shape = _open_scan_dataobj(filepath)
    i, j, k = int(voxel[0]), int(voxel[1]), int(voxel[2])
    if not (0 <= i < shape[0] and 0 <= j < shape[1] and 0 <= k < shape[2]):
        return jsonify({"error": "voxel out of volume bounds"}), 400

    mm = _voxel_to_mm(affine, i, j, k)
    return jsonify(
        {
            "mm": [
                round(float(mm[0]), 2),
                round(float(mm[1]), 2),
                round(float(mm[2]), 2),
            ]
        }
    )


@scans_bp.route("/<filename>/interpolate", methods=["POST"])
def interpolate_contacts(filename):
    """Legacy straight-line interpolation + proximity snap (matches desktop voxTool).

    Body: {
      start_voxel?: [i,j,k], end_voxel?: [i,j,k],
      start_mm?: [r,a,s], end_mm?: [r,a,s],
      low_label: int, high_label: int,
      labels?: [int, ...],          # interior labels; default low+1 .. high-1
      threshold_pct?: 99.96,
      lead_type?: "D"|"G"|"S",
      radius_mm?: float             # overrides lead_type default
    }
    """
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(force=True) or {}
    low_label = int(body.get("low_label", 0))
    high_label = int(body.get("high_label", 0))
    if high_label - low_label < 1:
        return jsonify(
            {"success": False, "error": "low_label and high_label must span at least 2 contacts"}
        ), 400

    threshold_pct = float(body.get("threshold_pct", 99.96))
    vol = _scan_vol(filepath, threshold_pct)
    start_vox = body.get("start_voxel")
    end_vox = body.get("end_voxel")
    if start_vox is None or end_vox is None:
        start_mm = body.get("start_mm")
        end_mm = body.get("end_mm")
        if (
            not start_mm
            or not end_mm
            or len(start_mm) != 3
            or len(end_mm) != 3
        ):
            return jsonify(
                {
                    "success": False,
                    "error": "start_voxel/end_voxel or start_mm/end_mm required",
                }
            ), 400
        start_vox = vol.mm_to_voxel(start_mm)[:3].tolist()
        end_vox = vol.mm_to_voxel(end_mm)[:3].tolist()

    labels = body.get("labels")
    if labels is not None:
        interior_labels = [int(x) for x in labels]
    else:
        interior_labels = list(range(low_label + 1, high_label))

    lead_type = body.get("lead_type")
    radius_mm = body.get("radius_mm")
    if radius_mm is None:
        radius_mm = lead_radius_mm(lead_type)
    else:
        radius_mm = float(radius_mm)

    existing = body.get("existing_voxels") or []

    result = interpolate_between_endpoints(
        vol,
        start_vox,
        end_vox,
        low_label,
        high_label,
        interior_labels,
        threshold_pct=threshold_pct,
        radius_mm=radius_mm,
        existing_voxels=existing,
    )
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result)


@scans_bp.route("/<filename>/interior_path", methods=["POST"])
def interior_path(filename):
    """Interior contact positions along a bright-voxel path between two endpoints.

    Fills the discrete label gap (low+1 .. high-1) by walking 26-connected voxels
    above an intensity percentile, then resampling arc length.

    The endpoint click is rarely *exactly* on a bright voxel and the metal
    contacts often appear as disconnected dots at very tight percentiles, so we
    auto-relax along three axes until A* succeeds:
      threshold_pct ↓  (more voxels in the mask)
      dilate ↑         (bridges 1-voxel gaps between contacts)
      margin_mm ↑      (catches bent leads that bow out of a thin ROI)

    Returns diagnostics describing what was tried so the client can report it.
    """
    data_dir = current_app.config["DATA_DIR"]
    filepath = _scan_filepath(filename)
    if not filepath:
        return jsonify({"error": f"Scan '{filename}' not found"}), 404

    body = request.get_json(force=True)
    start_mm = body.get("start_mm")
    end_mm = body.get("end_mm")
    low_label = int(body.get("low_label", 0))
    high_label = int(body.get("high_label", 0))
    if (
        not start_mm
        or not end_mm
        or len(start_mm) != 3
        or len(end_mm) != 3
        or high_label - low_label < 2
    ):
        return jsonify(
            {"success": False, "error": "start_mm, end_mm, low_label, high_label required"}
        ), 400

    base_threshold = float(body.get("threshold_pct", 99.96))
    base_margin = float(body.get("margin_mm", 12.0))

    vol = get_volume(filepath)
    v0 = np.asarray(vol.mm_to_voxel(start_mm)[:3], dtype=float)
    v1 = np.asarray(vol.mm_to_voxel(end_mm)[:3], dtype=float)
    mn_i = np.floor(np.minimum(v0, v1)).astype(int)
    mx_i = np.ceil(np.maximum(v0, v1)).astype(int)

    labels = body.get("labels")
    if labels is not None:
        interior_labels = [int(x) for x in labels]
        for ln in interior_labels:
            if not (low_label < ln < high_label):
                return jsonify(
                    {"success": False, "error": "each label must be between low and high"}
                ), 400
    else:
        interior_labels = list(range(low_label + 1, high_label))

    voxel_scale = float(np.mean(np.abs(np.diag(vol.affine[:3, :3]))))
    shape = vol.data.shape

    # Allow callers to cap retries (e.g. unit tests). Default to a reasonable matrix.
    threshold_attempts = list(
        body.get(
            "threshold_attempts",
            sorted({base_threshold, 99.9, 99.7, 99.4, 99.0}, reverse=True),
        )
    )
    dilate_attempts = list(body.get("dilate_attempts", [1, 2, 3]))
    margin_attempts = list(body.get("margin_attempts", sorted({base_margin, 18.0, 28.0})))

    # Endpoint-snap tolerance: allow the click to be up to ~snap radius away from
    # any bright voxel. Beyond that the user almost certainly clicked off-lead.
    endpoint_max_mm = float(body.get("endpoint_max_mm", 6.0))
    endpoint_max_vox = endpoint_max_mm / max(voxel_scale, 1e-6)

    diagnostics = {"attempts": [], "voxel_scale_mm": round(voxel_scale, 3)}

    chord_len_mm = float(np.linalg.norm(np.asarray(end_mm) - np.asarray(start_mm)))
    diagnostics["chord_mm"] = round(chord_len_mm, 2)

    path_l = None
    chosen = None
    chosen_offset = None
    chosen_endpoint_dists = None

    for margin_mm in margin_attempts:
        margin_vox = max(3, int(np.ceil(margin_mm / max(voxel_scale, 1e-6))))
        i0 = int(np.clip(mn_i[0] - margin_vox, 0, shape[0] - 1))
        j0 = int(np.clip(mn_i[1] - margin_vox, 0, shape[1] - 1))
        k0 = int(np.clip(mn_i[2] - margin_vox, 0, shape[2] - 1))
        i1 = int(np.clip(mx_i[0] + margin_vox + 1, 1, shape[0]))
        j1 = int(np.clip(mx_i[1] + margin_vox + 1, 1, shape[1]))
        k1 = int(np.clip(mx_i[2] + margin_vox + 1, 1, shape[2]))
        if i1 <= i0 or j1 <= j0 or k1 <= k0:
            continue

        sub = vol.data[i0:i1, j0:j1, k0:k1]

        for thr_pct in threshold_attempts:
            thr = float(np.percentile(vol.data, thr_pct))
            base_mask = sub >= thr
            base_count = int(base_mask.sum())
            if base_count == 0:
                diagnostics["attempts"].append(
                    {
                        "threshold_pct": thr_pct,
                        "margin_mm": margin_mm,
                        "dilate": 0,
                        "mask_voxels": 0,
                        "result": "empty_mask",
                    }
                )
                continue

            for dilate_iters in dilate_attempts:
                mask = base_mask
                for _ in range(max(0, dilate_iters)):
                    mask = _dilate_mask_26(mask)
                mask_count = int(mask.sum())

                start_l = tuple(int(round(x)) for x in (v0[0] - i0, v0[1] - j0, v0[2] - k0))
                goal_l = tuple(int(round(x)) for x in (v1[0] - i0, v1[1] - j0, v1[2] - k0))
                start_l = (
                    int(np.clip(start_l[0], 0, mask.shape[0] - 1)),
                    int(np.clip(start_l[1], 0, mask.shape[1] - 1)),
                    int(np.clip(start_l[2], 0, mask.shape[2] - 1)),
                )
                goal_l = (
                    int(np.clip(goal_l[0], 0, mask.shape[0] - 1)),
                    int(np.clip(goal_l[1], 0, mask.shape[1] - 1)),
                    int(np.clip(goal_l[2], 0, mask.shape[2] - 1)),
                )

                snapped_start, ds = _nearest_true_voxel(
                    mask, *start_l, max_radius=endpoint_max_vox
                )
                snapped_goal, dg = _nearest_true_voxel(
                    mask, *goal_l, max_radius=endpoint_max_vox
                )
                start_dist_mm = ds * voxel_scale if np.isfinite(ds) else float("inf")
                goal_dist_mm = dg * voxel_scale if np.isfinite(dg) else float("inf")

                if snapped_start is None or snapped_goal is None:
                    diagnostics["attempts"].append(
                        {
                            "threshold_pct": thr_pct,
                            "margin_mm": margin_mm,
                            "dilate": dilate_iters,
                            "mask_voxels": mask_count,
                            "start_dist_mm": round(start_dist_mm, 2),
                            "goal_dist_mm": round(goal_dist_mm, 2),
                            "result": "endpoint_off_lead",
                        }
                    )
                    continue

                p = _astar_on_mask(
                    mask, snapped_start, snapped_goal, vol.affine, (i0, j0, k0)
                )
                if p:
                    path_mm_check = _path_to_mm(vol, (i0, j0, k0), p)
                    arc = float(
                        np.sum(np.linalg.norm(np.diff(path_mm_check, axis=0), axis=1))
                    )
                    diagnostics["attempts"].append(
                        {
                            "threshold_pct": thr_pct,
                            "margin_mm": margin_mm,
                            "dilate": dilate_iters,
                            "mask_voxels": mask_count,
                            "start_dist_mm": round(start_dist_mm, 2),
                            "goal_dist_mm": round(goal_dist_mm, 2),
                            "result": "ok",
                            "path_voxels": len(p),
                            "arc_mm": round(arc, 2),
                        }
                    )
                    path_l = p
                    chosen = {
                        "threshold_pct": thr_pct,
                        "margin_mm": margin_mm,
                        "dilate": dilate_iters,
                        "mask_voxels": mask_count,
                        "start_dist_mm": round(start_dist_mm, 2),
                        "goal_dist_mm": round(goal_dist_mm, 2),
                        "path_voxels": len(p),
                        "arc_mm": round(arc, 2),
                    }
                    chosen_offset = (i0, j0, k0)
                    chosen_endpoint_dists = (start_dist_mm, goal_dist_mm)
                    break
                else:
                    diagnostics["attempts"].append(
                        {
                            "threshold_pct": thr_pct,
                            "margin_mm": margin_mm,
                            "dilate": dilate_iters,
                            "mask_voxels": mask_count,
                            "start_dist_mm": round(start_dist_mm, 2),
                            "goal_dist_mm": round(goal_dist_mm, 2),
                            "result": "no_path",
                        }
                    )
            if path_l:
                break
        if path_l:
            break

    if not path_l:
        # Pick the most informative reason for the user.
        last_off = next(
            (a for a in reversed(diagnostics["attempts"]) if a.get("result") == "endpoint_off_lead"),
            None,
        )
        if last_off:
            reason = (
                f"Endpoint isn't on a bright voxel "
                f"(start ≈ {last_off['start_dist_mm']}mm, "
                f"goal ≈ {last_off['goal_dist_mm']}mm from any super-threshold voxel). "
                "Reposition LA1 / LAend onto the metal contact."
            )
            err_kind = "endpoint_off_lead"
        else:
            reason = (
                "No connected bright path between the two endpoints, even after "
                "relaxing threshold/dilation/ROI. Check that both endpoints sit "
                "on the same physical lead."
            )
            err_kind = "no_path"
        diagnostics["reason"] = reason
        return jsonify(
            {
                "success": False,
                "error": err_kind,
                "message": reason,
                "diagnostics": diagnostics,
            }
        )

    path_mm = _path_to_mm(vol, chosen_offset, path_l)
    t_values = [(n - low_label) / float(high_label - low_label) for n in interior_labels]
    samples = _resample_polyline_mm(path_mm, t_values)
    if len(samples) != len(interior_labels):
        diagnostics["reason"] = "resample_failed"
        return jsonify(
            {
                "success": False,
                "error": "resample_failed",
                "message": "Internal: arc-length resampling did not return one sample per label.",
                "diagnostics": diagnostics,
            }
        )

    interior = []
    for n, mm in zip(interior_labels, samples):
        interior.append(
            {
                "label": str(n),
                "mm": [round(float(mm[0]), 1), round(float(mm[1]), 1), round(float(mm[2]), 1)],
            }
        )

    diagnostics["selected"] = chosen
    return jsonify({"success": True, "interior": interior, "diagnostics": diagnostics})
