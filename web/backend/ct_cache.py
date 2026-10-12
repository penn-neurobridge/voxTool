"""Lazy in-memory cache for loaded CT volumes.

Loading a NIfTI is expensive (disk I/O + decompression), and the snap endpoint
is called once per click. We keep the most recently used scans in memory.
"""
import os
import threading
import nibabel as nib
import numpy as np

_CACHE = {}
_LOCK = threading.Lock()
_MAX_ENTRIES = 4  # at most N scans cached at once


class CTVolume:
    """Holds the data we need to perform contact snapping."""

    def __init__(self, filepath):
        self.filepath = filepath
        img = nib.load(filepath)
        # float32 halves RAM (~500MB→~250MB for typical head CTs); required on
        # Render free tier (512MB).
        self.data = np.asarray(img.get_fdata(), dtype=np.float32).squeeze()
        self.affine = img.affine.astype(np.float64)
        self.inv_affine = np.linalg.inv(self.affine)
        # Threshold cache: maps threshold_pct -> Nx3 array of voxel indices
        # above the threshold value. We compute lazily.
        self._threshold_points = {}

    def points_above_threshold(self, threshold_pct):
        key = round(float(threshold_pct), 4)
        cached = self._threshold_points.get(key)
        if cached is not None:
            return cached
        threshold_value = np.percentile(self.data, threshold_pct)
        mask = self.data >= threshold_value
        indices = np.array(mask.nonzero()).T.astype(np.float32)
        # Cap memory: if more than ~5M points we keep them anyway since we need them
        self._threshold_points[key] = indices
        return indices

    def mm_to_voxel(self, mm):
        mm_h = np.array([mm[0], mm[1], mm[2], 1.0], dtype=np.float64)
        return (self.inv_affine @ mm_h)[:3]

    def voxel_to_mm(self, vox):
        vox_h = np.array([vox[0], vox[1], vox[2], 1.0], dtype=np.float64)
        return (self.affine @ vox_h)[:3]


def get_volume(filepath):
    abs_path = os.path.abspath(filepath)
    with _LOCK:
        vol = _CACHE.get(abs_path)
        if vol is not None:
            return vol
        if len(_CACHE) >= _MAX_ENTRIES:
            # Evict an arbitrary entry; we don't track LRU strictly.
            _CACHE.pop(next(iter(_CACHE)))
        vol = CTVolume(abs_path)
        _CACHE[abs_path] = vol
        return vol


def volume_is_cached(filepath: str) -> bool:
    abs_path = os.path.abspath(filepath)
    with _LOCK:
        return abs_path in _CACHE


def warm_volume(filepath: str) -> None:
    """Load CT into this worker's memory (same path local snap/pick uses)."""
    get_volume(filepath)
