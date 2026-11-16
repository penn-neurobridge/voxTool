"""Fill the contacts between two marked contacts of a lead.

Started as a port of the legacy voxTool interpolation (model/interpolator.py +
model/scan.py): evenly spaced points on the straight line between the two ends,
each pulled to the centroid of nearby bright voxels. Real depth leads bend, and
on a bent lead the straight-line guesses drift off it: several snapped onto the
same contact, or onto nothing, yet every one was reported as placed. Users saw
coordinates in the list for contacts that were never highlighted.

Now the fill walks the lead one contact at a time, inward from both marked ends,
predicting each contact from the contacts already found next to it, so the path
follows the bend. The snap ball is measured in millimetres (CT voxels are rarely
cubic). A contact is only placed when it lands on metal of its own; otherwise it
is returned in ``skipped`` with a reason, for the user to click by hand.
"""
from __future__ import annotations

import numpy as np

# Matches config.yml lead_types.*.radius
LEAD_RADIUS_MM = {"D": 3.0, "G": 3.0, "S": 5.0}

# Two contacts closer than this fraction of the contact spacing are the same
# contact. Neighbouring contacts are a full spacing apart, so half is a safe cut.
SAME_CONTACT_FRACTION = 0.5
# Snap ball radius as a fraction of the contact spacing (capped by the lead's radius).
SNAP_FRACTION = 0.5


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


def _snap_mm(points_mm: np.ndarray, seed_mm: np.ndarray, radius_mm: float, iterations: int):
    """Mean shift in millimetres: move to the centroid of bright voxels within
    ``radius_mm``, repeat. Returns (centre, voxel count, found metal)."""
    current = np.asarray(seed_mm, dtype=np.float64)
    count = 0
    for _ in range(max(1, iterations)):
        near = points_mm[np.linalg.norm(points_mm - current, axis=1) < radius_mm]
        if near.shape[0] == 0:
            break
        current = near.mean(axis=0)
        count = int(near.shape[0])
    return current, count, count > 0


def _unit(v: np.ndarray) -> np.ndarray | None:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else None


def _predict(known: dict[int, np.ndarray], label: int, low: int, high: int):
    """Where contact ``label`` should be, from the contacts already found.

    Steps in from the nearer found neighbour. Direction blends the local tangent
    (the last two found contacts on that side, which follows a bend) with the
    chord to the found contact on the far side (which keeps the walk heading for
    the other end). Step length is the measured spacing on that side when there
    is one, otherwise the chord spacing.
    """
    below = max(k for k in known if k < label)
    above = min(k for k in known if k > label)
    chord = (known[above] - known[below]) / float(above - below)  # per label, low→high

    if label - below <= above - label:
        anchor, sign, dist = below, 1.0, label - below
        prev = [k for k in known if k < below]
        back = max(prev) if prev else None
    else:
        anchor, sign, dist = above, -1.0, above - label
        prev = [k for k in known if k > above]
        back = min(prev) if prev else None

    step = chord
    if back is not None:
        tangent = (known[anchor] - known[back]) / float(anchor - back)
        u_t, u_c = _unit(tangent), _unit(chord)
        if u_t is not None and u_c is not None:
            u = _unit(0.65 * u_t + 0.35 * u_c)
            if u is not None:
                step = u * float(np.linalg.norm(tangent))
    return known[anchor] + sign * step * float(dist)


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
    known_contacts: list | None = None,
) -> dict:
    """Fill interior contact labels by walking the lead from both marked ends.

    ``known_contacts`` ([{label, voxel}]) are contacts of this lead the user
    already marked; they guide the walk. ``existing_voxels`` (unlabelled) only
    guard against placing a contact on top of one that exists.
    """
    span = high_label - low_label
    if span < 1:
        return {"success": False, "error": "high_label must exceed low_label"}

    aff = np.asarray(vol.affine, dtype=np.float64)
    lin, off = aff[:3, :3], aff[:3, 3]

    def to_mm(v):
        return lin @ np.asarray(v, dtype=np.float64) + off

    def to_vox(mm):
        return np.linalg.solve(lin, np.asarray(mm, dtype=np.float64) - off)

    points_mm = vol.points_above_threshold(threshold_pct).astype(np.float64) @ lin.T + off

    known: dict[int, np.ndarray] = {low_label: to_mm(start_vox), high_label: to_mm(end_vox)}
    for kc in known_contacts or []:
        try:
            lab = int(kc["label"])
            vox = kc["voxel"]
        except (KeyError, TypeError, ValueError):
            continue
        if low_label < lab < high_label and vox is not None and len(vox) == 3:
            known[lab] = to_mm(vox)

    spacing_mm = float(np.linalg.norm(known[high_label] - known[low_label])) / span
    same_mm = max(SAME_CONTACT_FRACTION * spacing_mm, 0.75)
    # A ball wider than half the spacing reaches the neighbouring contacts, and
    # the centroid then settles between two of them.
    snap_r = min(radius_mm, max(SNAP_FRACTION * spacing_mm, 1.0))
    occupied = [to_mm(v) for v in (existing_voxels or []) if v is not None and len(v) == 3]
    occupied += list(known.values())

    todo = sorted({int(x) for x in interior_labels if low_label < int(x) < high_label} - set(known))
    shape = np.array(vol.data.shape[:3])
    interior, skipped = [], []
    while todo:
        # Next: the unfilled contact closest to a found one, so every guess is
        # made from a neighbour at most a few contacts away.
        def gap(lab):
            below = max(k for k in known if k < lab)
            above = min(k for k in known if k > lab)
            return min(lab - below, above - lab)

        label = min(todo, key=lambda lab: (gap(lab), lab))
        todo.remove(label)

        seed = _predict(known, label, low_label, high_label)
        centre, count, ok = _snap_mm(points_mm, seed, snap_r, snap_iterations)
        if not ok:
            skipped.append({"label": label, "reason": "no_metal"})
            continue
        clash = min((float(np.linalg.norm(centre - o)) for o in occupied), default=np.inf)
        if clash < same_mm:
            skipped.append({"label": label, "reason": "same_contact_as_another"})
            continue

        known[label] = centre
        occupied.append(centre)
        cv = np.clip(np.round(to_vox(centre)).astype(int), 0, shape - 1)
        interior.append(
            {
                "label": str(label),
                "mm": [round(float(c), 1) for c in centre],
                "voxel": [int(cv[0]), int(cv[1]), int(cv[2])],
                "voxel_count": count,
                "snapped": True,
            }
        )

    interior.sort(key=lambda d: int(d["label"]))
    skipped.sort(key=lambda d: d["label"])
    return {
        "success": True,
        "interior": interior,
        "skipped": skipped,
        "method": "walk_from_both_ends",
        "radius_mm": round(snap_r, 2),
        "n_positions": span + 1,
    }
