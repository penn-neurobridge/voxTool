#!/usr/bin/env python3
"""Score extraction against hand-written ground truth.

    python eval/run_eval.py                    # channel map only, no model
    python eval/run_eval.py --provider ollama  # with a local model

Samples live in ``eval/samples/`` and are git-ignored, because they are clinical
documents. Each sample is a document plus a ``<name>.expected.json`` written by
hand:

    {"leads": [{"name": "LA", "contacts": 12, "target": "Left Amygdala"}, ...]}

Reported per sample: which leads were missed, which were invented, and which had
the wrong contact count. Contact counts are the number that matters — a wrong
count silently truncates or over-runs a lead during annotation.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction import pipeline  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def load_expected(doc_path: str):
    base = os.path.splitext(doc_path)[0]
    for candidate in (f"{base}.expected.json", f"{doc_path}.expected.json"):
        if os.path.isfile(candidate):
            with open(candidate) as f:
                return json.load(f).get("leads", [])
    return None


def score(expected: list[dict], got_leads) -> dict:
    exp = {l["name"].upper(): l for l in expected}
    got = {l.name.upper(): l for l in got_leads}

    missing = sorted(set(exp) - set(got))
    extra = sorted(set(got) - set(exp))
    wrong_count = []
    for key in sorted(set(exp) & set(got)):
        want = exp[key].get("contacts")
        have = got[key].contacts
        if want is not None and want != have:
            wrong_count.append(f"{exp[key]['name']}: expected {want}, got {have}")

    matched = len(set(exp) & set(got))
    return {
        "expected": len(exp),
        "found": len(got),
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "wrong_count": wrong_count,
        "counts_correct": matched - len(wrong_count),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="none", help="none | ollama")
    ap.add_argument("--model", default=None)
    ap.add_argument("--samples", default=SAMPLES)
    args = ap.parse_args()

    docs = sorted(
        g
        for ext in ("pdf", "pptx")
        for g in glob.glob(os.path.join(args.samples, f"*.{ext}"))
    )
    if not docs:
        print(f"No documents in {args.samples}.")
        print("Put implant documents there plus a <name>.expected.json for each.")
        return 1

    totals = {"expected": 0, "matched": 0, "counts_correct": 0, "extra": 0}
    graded = 0

    for doc in docs:
        name = os.path.basename(doc)
        started = time.time()
        try:
            result = pipeline.run(doc, provider=args.provider, model=args.model)
        except Exception as e:  # noqa: BLE001
            print(f"\n{name}\n  FAILED: {e}")
            continue
        elapsed = time.time() - started

        print(f"\n{name}  ({elapsed:.1f}s, provider={result.provider})")
        print(
            f"  pages={result.document.get('pages')} "
            f"readable={result.document.get('readable_pages')} "
            f"scanned={result.document.get('scanned_pages')}"
        )
        print(f"  leads found: {len(result.leads)}  needing review: {result.needs_review}")
        for w in result.warnings:
            print(f"  ! {w}")

        expected = load_expected(doc)
        if expected is None:
            print("  (no .expected.json, not scored)")
            for lead in result.leads:
                print(f"    {lead.name:<6} {lead.contacts:>3}  {lead.target}")
            continue

        graded += 1
        s = score(expected, result.leads)
        totals["expected"] += s["expected"]
        totals["matched"] += s["matched"]
        totals["counts_correct"] += s["counts_correct"]
        totals["extra"] += len(s["extra"])

        print(
            f"  matched {s['matched']}/{s['expected']} leads, "
            f"{s['counts_correct']}/{s['expected']} with the right contact count"
        )
        if s["missing"]:
            print(f"  MISSED:  {', '.join(s['missing'])}")
        if s["extra"]:
            print(f"  EXTRA:   {', '.join(s['extra'])}")
        for line in s["wrong_count"]:
            print(f"  COUNT:   {line}")

    if graded:
        print(
            f"\n{'=' * 60}\n"
            f"{graded} scored document(s): "
            f"{totals['matched']}/{totals['expected']} leads found, "
            f"{totals['counts_correct']}/{totals['expected']} contact counts correct, "
            f"{totals['extra']} invented"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
