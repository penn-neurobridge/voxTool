"""Interpolation must put each filled contact on its own contact, or say it could not.

The lab reported contacts that interpolation listed with coordinates but that
Electrode View never highlighted. The fill seeded every contact from the
straight line between the two marked ends, so on a bent lead the guesses
drifted off it and several snapped onto the same contact (or onto nothing),
while every one was reported as placed. These tests build depth leads with
known contact positions on a CT grid with non-cubic voxels.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from legacy_interpolator import interpolate_between_endpoints  # noqa: E402

# The MNE sample sEEG CT's voxels; clinical CTs are similar (thin in-plane, thick slices).
ZOOMS = np.array([0.415, 0.415, 0.833])
AFFINE = np.diag([*ZOOMS, 1.0])


def make_lead(n, spacing, sagitta, direction, bend=(0.3, -1.0, 0.2), start=(60.0, 60.0, 40.0)):
    """Contact centres (mm) and axes for a lead bowed by ``sagitta`` mm at its middle."""
    d = np.asarray(direction, float)
    d /= np.linalg.norm(d)
    b = np.asarray(bend, float)
    b -= d * (b @ d)
    b /= np.linalg.norm(b)
    length = spacing * (n - 1)
    s = np.linspace(0, length, 4000)
    curve = (np.asarray(start) + np.outer(s, d)
             + np.outer(4 * sagitta * (s / length) * (1 - s / length), b))
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
    idx = [int(np.argmin(abs(arc - arc[-1] * k / (n - 1)))) for k in range(n)]
    tangents = np.gradient(curve, axis=0)[idx]
    return curve[idx], tangents / np.linalg.norm(tangents, axis=1)[:, None]


def metal_voxels(centres, axes, radius=1.0, half_length=1.2):
    """Voxels inside each contact: a 2.4 mm x 2 mm cylinder, roughly how a contact blooms on CT."""
    out = set()
    for c, t in zip(centres, axes):
        lo = np.floor((c - 3) / ZOOMS).astype(int)
        hi = np.ceil((c + 3) / ZOOMS).astype(int)
        grid = np.stack(np.meshgrid(*[np.arange(a, b) for a, b in zip(lo, hi)], indexing="ij"), -1)
        grid = grid.reshape(-1, 3)
        rel = grid * ZOOMS - c
        along = rel @ t
        across = np.linalg.norm(rel - np.outer(along, t), axis=1)
        out.update(map(tuple, grid[(abs(along) <= half_length) & (across <= radius)]))
    return out


class FakeVol:
    def __init__(self, voxels):
        self.affine = AFFINE
        self.data = type("Shape", (), {"shape": (400, 400, 200)})()
        self._pts = np.array(sorted(voxels), dtype=np.float32)

    def points_above_threshold(self, threshold_pct):
        return self._pts


def run(centres, others=(), known=None):
    vol = FakeVol(set().union(metal_voxels(*centres), *[metal_voxels(*o) for o in others]))
    pts = centres[0]
    n = len(pts)
    ends = [np.linalg.solve(AFFINE[:3, :3], p) for p in (pts[0], pts[-1])]
    return interpolate_between_endpoints(
        vol, ends[0], ends[1], 1, n, list(range(2, n)), radius_mm=3.0,
        known_contacts=known,
    )


def placed_on(result, truth):
    """label -> index of the real contact it landed on (within 1 mm), else None."""
    out = {}
    for item in result["interior"]:
        d = np.linalg.norm(truth - np.array(item["mm"]), axis=1)
        out[int(item["label"])] = int(np.argmin(d)) + 1 if d.min() < 1.0 else None
    return out


@pytest.mark.parametrize("direction", [(1, 0.15, 0.1), (0.1, 0.15, 1), (1, 1, 1)])
@pytest.mark.parametrize("sagitta", [0, 4, 9])
@pytest.mark.parametrize("n,spacing", [(12, 3.5), (16, 3.5), (10, 5.0)])
def test_every_contact_lands_on_its_own_contact(n, spacing, sagitta, direction):
    lead = make_lead(n, spacing, sagitta, direction)
    # A neighbouring lead 6 mm away, as in any real implant.
    shift = np.array([1.0, 0, 0]) if direction[2] == 1 else np.array([0, 0, 1.0])
    neighbour = make_lead(n, spacing, 0, direction, start=np.array([60.0, 60.0, 40.0]) + 6 * shift)
    result = run(lead, [neighbour])
    got = placed_on(result, lead[0])
    wrong = {lab: hit for lab, hit in got.items() if hit != lab}
    assert not wrong, f"placed on the wrong contact: {wrong}"
    # Every interior contact is accounted for: placed or reported as skipped.
    skipped = {s["label"] for s in result["skipped"]}
    assert set(got) | skipped == set(range(2, n))
    if sagitta <= 4:
        assert not skipped


def test_reports_rather_than_doubles_up_when_the_lead_bends_too_far():
    lead = make_lead(12, 3.5, 13, (0.1, 0.15, 1))
    result = run(lead)
    got = placed_on(result, lead[0])
    assert all(hit == lab for lab, hit in got.items())
    assert result["skipped"], "a contact it could not find must be reported, not guessed"
    assert {s["reason"] for s in result["skipped"]} <= {"no_metal", "same_contact_as_another"}


def test_a_contact_marked_by_hand_rescues_a_bend_too_far():
    lead = make_lead(12, 3.5, 13, (0.1, 0.15, 1))
    pts = lead[0]
    marked = [{"label": k, "voxel": list(np.linalg.solve(AFFINE[:3, :3], pts[k - 1]))}
              for k in (4, 6, 9)]
    result = run(lead, known=marked)
    got = placed_on(result, pts)
    assert all(hit == lab for lab, hit in got.items())
    assert len(got) >= 6


def test_never_places_two_contacts_on_one():
    lead = make_lead(16, 3.5, 9, (1, 1, 1))
    result = run(lead)
    mm = np.array([item["mm"] for item in result["interior"]])
    gaps = np.linalg.norm(mm[:, None] - mm[None], axis=2) + np.eye(len(mm)) * 99
    assert gaps.min() > 1.75
