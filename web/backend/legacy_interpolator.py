"""Legacy voxTool interpolation math (ported from model/interpolator.py + model/scan.py).

Straight-line spacing between endpoints, then nearest-neighbor centroid snap within
a lead-type radius on the super-threshold point cloud.
"""
from __future__ import annotations

import numpy as np

# Matches config.yml lead_types.*.radius
LEAD_RADIUS_MM = {"D": 3.0, "G": 3.0, "S": 5.0}


def lead_radius_mm(lead_type: str | None) -> float:
    if not lead_type:
        return LEAD_RADIUS_MM["D"]
    return LEAD_RADIUS_MM.get(str(lead_type).upper(), LEAD_RADIUS_MM["D"])


def interpol_strip_voxel(coor1, coor2, n_positions: int) -> list[np.ndarray]:
    """Evenly spaced voxel points along A→B, including both endpoints.

    Mirrors model/interpolator.interpol_strip(coor1, coor2, m=n_positions, n=1).
    """
    A = np.asarray(coor1, dtype=np.float64)
    B = np.asarray(coor2, dtype=np.float64)
    if n_positions < 2:
        return [A.copy()]

    A2B = B - A
    mag = float(np.linalg.norm(A2B))
    if mag < 1e-9:
        return [A.copy()]

    unit = A2B / mag
    points: list[np.ndarray] = [A.copy()]
    denom = float(n_positions - 1)
    for i in range(n_positions):
        pt = A + (mag / denom) * float(i + 1) * unit
        points.append(pt.copy())
    return points[:-1]


def centered_snap_voxel(
    threshold_points: np.ndarray,
    seed_vox,
    radius_vox: float,
    iterations: int = 4,
) -> tuple[np.ndarray, int, bool]:
    """Iterative centroid refinement within a voxel-radius ball (legacy PointMask)."""
    current = np.asarray(seed_vox, dtype=np.float64)
    nearby_count = 0
    for _ in range(max(1, iterations)):
        dists = np.linalg.norm(threshold_points - current, axis=1)
        nearby = threshold_points[dists < radius_vox]
        if nearby.shape[0] == 0:
            break
        current = nearby.mean(axis=0)
        nearby_count = int(nearby.shape[0])
    return current, nearby_count, nearby_count > 0


def interpolate_between_endpoints(
    vol,
    start_vox,
    end_vox,
    low_label: int,
    high_label: int,
    interior_labels: list[int],
    *,
    threshold_pct: float = 99.96,
    radius_mm: float = 3.0,
    snap_iterations: int = 4,
    existing_voxels: list | None = None,
) -> dict:
    """Fill interior contact labels using legacy straight-line + proximity snap."""
    span = high_label - low_label
    if span < 1:
        return {"success": False, "error": "high_label must exceed low_label"}

    n_positions = span + 1
    line_pts = interpol_strip_voxel(start_vox, end_vox, n_positions)

    voxel_scale = float(np.mean(np.abs(np.diag(vol.affine[:3, :3]))))
    radius_vox = radius_mm / max(voxel_scale, 1e-6)
    threshold_points = vol.points_above_threshold(threshold_pct)

    anchors = list(existing_voxels or [])
    anchors.extend([np.asarray(start_vox, dtype=np.float64), np.asarray(end_vox, dtype=np.float64)])

    interior = []
    skipped = []
    for label in interior_labels:
        if not (low_label < label < high_label):
            continue
        idx = label - low_label
        if idx < 0 or idx >= len(line_pts):
            continue
        seed = line_pts[idx]
        snapped, count, ok = centered_snap_voxel(
            threshold_points, seed, radius_vox, iterations=snap_iterations
        )
        center = snapped if ok else seed

        dup = False
        for anc in anchors:
            if float(np.linalg.norm(center - np.asarray(anc, dtype=np.float64))) < 0.5:
                skipped.append({"label": label, "reason": "duplicate_center"})
                dup = True
                break
        if dup:
            continue

        anchors.append(center)
        mm = vol.voxel_to_mm(center.tolist())[:3]
        cv = np.round(center).astype(int)
        shape = vol.data.shape
        cv = np.clip(cv, [0, 0, 0], np.array(shape) - 1)
        interior.append(
            {
                "label": str(label),
                "mm": [round(float(mm[0]), 1), round(float(mm[1]), 1), round(float(mm[2]), 1)],
                "voxel": [int(cv[0]), int(cv[1]), int(cv[2])],
                "voxel_count": count,
                "snapped": ok,
            }
        )

    return {
        "success": True,
        "interior": interior,
        "skipped": skipped,
        "method": "legacy_straight_line",
        "radius_mm": radius_mm,
        "n_positions": n_positions,
    }
