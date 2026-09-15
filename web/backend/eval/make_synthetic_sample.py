#!/usr/bin/env python3
"""Write a synthetic implant document into eval/samples/ for end-to-end testing.

Modelled on the structure of a real document without using one: a proposed
layout, a final lead table that disagrees with it, a channel map, and a page of
scalp and EKG channels. The disagreement is the point — a real document had a
lead planned and then dropped in theatre, with a different target added, and the
whole reason for cross-checking against the channel map is to catch that.

    python eval/make_synthetic_sample.py
"""
from __future__ import annotations

import json
import os

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PDF = os.path.join(HERE, "samples", "synthetic_implant.pdf")
OUT_JSON = os.path.join(HERE, "samples", "synthetic_implant.expected.json")

# The final implant. LG is proposed but never implanted; LA is added instead.
FINAL = [
    ("LA", "Left Amygdala", 12),
    ("LB", "Left Hippocampal Head", 8),
    ("LC", "Left Hippocampal Tail", 12),
    ("LH", "Left Posterior PVNH", 12),
    ("LI", "Left Temporal Pole", 12),
    ("LT", "Left Anterior Ventral Insula", 8),
    ("LQ", "Left Anterior Dorsal Insula", 12),
    ("LY", "Left Anterior Cingulate", 12),
    ("LOf", "Left Orbitofrontal", 12),
    ("RB", "Right Hippocampal Head", 12),
    ("RC", "Right Hippocampal Tail", 12),
    ("RG", "Right Anterior PVNH", 12),
    ("RH", "Right Posterior PVNH", 12),
    ("RI", "Right Temporal Pole", 12),
    ("RT", "Right Anterior Ventral Insula", 8),
    ("RQ", "Right Anterior Dorsal Insula", 12),
    ("RY", "Right Anterior Cingulate", 12),
    ("ROf", "Right Orbitofrontal", 12),
]

PROPOSED_ONLY = ("LG", "Left PVNH lesion, anterior")


def _page(doc, lines, size=9):
    page = doc.new_page()
    y = 50
    for line in lines:
        page.insert_text((45, y), line, fontsize=size)
        y += size + 4
    return page


def build() -> None:
    os.makedirs(os.path.dirname(OUT_PDF), exist_ok=True)
    doc = pymupdf.open()

    # 1. Proposed layout, deliberately not the same as what was implanted.
    proposed = ["PROPOSED", "", "Lead    Target"]
    proposed += [f"{PROPOSED_ONLY[0]:<8}{PROPOSED_ONLY[1]}"]
    proposed += [f"{n:<8}{t}" for n, t, _ in FINAL if n != "LA"]
    _page(doc, proposed)

    # 2. Final lead table, the one that should win.
    final = ["FINAL IMPLANT", "", "Lead    Target                              # of contacts"]
    final += [f"{n:<8}{t:<36}{c}" for n, t, c in FINAL]
    _page(doc, final)

    # 3-4. Channel map: every contact, in amplifier order.
    tokens: list[str] = []
    for name, _, count in FINAL:
        # Case drifts in real documents; reproduce that so the parser is tested.
        spelling = name.upper() if name in ("LOf",) else name
        tokens += [f"{spelling}{i}" for i in range(1, count + 1)]
    tokens += ["FZ", "Cz", "C3", "C4", "EKG1", "EKG2"]

    rows, channel = [], 1
    for i in range(0, len(tokens), 16):
        chunk = tokens[i : i + 16]
        rows.append(" ".join(f"{t:>6}" for t in chunk))
        rows.append(" ".join(f"{channel + j:>6}" for j in range(len(chunk))))
        rows.append("")
        channel += len(chunk)

    half = len(rows) // 2
    _page(doc, ["CHANNEL MAP", ""] + rows[:half], size=7)
    _page(doc, ["CHANNEL MAP (continued)", ""] + rows[half:], size=7)

    doc.save(OUT_PDF)
    doc.close()

    with open(OUT_JSON, "w") as f:
        json.dump(
            {"leads": [{"name": n, "contacts": c, "target": t} for n, t, c in FINAL]},
            f,
            indent=2,
        )
    print(f"wrote {OUT_PDF}")
    print(f"wrote {OUT_JSON}  ({len(FINAL)} leads)")


if __name__ == "__main__":
    build()
