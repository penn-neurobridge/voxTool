# Implant document extraction: running and testing it

Phase 1 and 2 of [the project plan](LLM_ANNOTATION_PLAN.md). Reads the implant
document and pre-fills the lead definitions. Everything runs on the machine
doing the annotation; nothing is uploaded.

## Why this only runs locally

The endpoints refuse every request unless `VOXTOOL_LOCAL` is set, which the
desktop app sets for itself. The cloud deployment has no authentication, so an
endpoint that accepts clinical documents must not exist there at all rather than
merely be unadvertised.

Development happens on the `llm-extraction` branch for the same reason. The
frontend deploy workflow only fires on `web-app` and `main`, so work in progress
cannot reach the public demo by accident.

## Running it

From the repository root:

```bash
./run_demo.sh
```

Then open <http://127.0.0.1:5001>. Ctrl-C to stop.

The script creates the Python environment and builds the interface if they are
missing, starts Ollama if it is installed, and reports what it found. First run
takes a few minutes; after that it is seconds.

In the app: **Define leads → Read from document…**, choose the PDF or PPTX,
review the table, press Add.

## Two ways to read a document

**Channel map only** (default, no model needed). Implant documents contain a
grid mapping every contact to an amplifier channel — `LA1 LA2 ... LA12 LB1 ...`.
That grid is mechanical, so a regex reads it exactly. It yields every lead name
and contact count but no anatomical targets.

**Local model** adds the targets by reading the lead table, and fills in leads
that never reached the channel map. Requires [Ollama](https://ollama.com):

```bash
ollama serve
ollama pull qwen2.5:7b-instruct        # or set VOXTOOL_LLM_MODEL
```

The model is asked for JSON constrained to a schema, so malformed output is not
a failure mode it can have. Wrong *values* still are, which is what the review
screen and the cross-check below are for.

## The cross-check

The two sources are reconciled rather than merged:

- Both agree → marked confident.
- Counts differ → the channel map wins, and the row is flagged with what each
  source said.
- In the document but not the channel map → kept and flagged as a probable
  proposed lead that was never implanted.
- In the channel map but not the document → kept and flagged, target unknown.

That third case is the one that matters. Real implant documents contain a
proposed layout as well as the final one, and they disagree — a planned lead is
dropped in theatre and a different target added. A model reading the document
has no reliable way to know which table won. The channel map does, because it
reflects what was actually wired up.

## Evaluating

```bash
cd web/backend
python eval/make_synthetic_sample.py     # invented document, safe to share
python eval/run_eval.py                  # channel map only
python eval/run_eval.py --provider ollama
```

Put real documents in `eval/samples/` with a hand-written
`<name>.expected.json` next to each. **That directory is git-ignored** — these
are clinical records and the repository is shared.

Measured on six real implant documents (Apple Silicon, qwen2.5:7b-instruct),
78 leads in total:

| | Leads found | Contact counts | Invented |
|---|---|---|---|
| Channel map only | 76/78 | 74/78 | 1 |
| With the local model | 78/78 | 78/78 | 1 |

The single "invented" lead is real: one document writes `RFp` in the lead table
and `RPf` in the channel map. Both are kept and flagged as a probable
transposition rather than merged, because merging them would be a guess.

What the documents taught us, each of which changed the code:

- **A recording can be shorter than the electrode.** One implant has 22
  twelve-contact leads, which needs 264 channels against an amplifier's 256, so
  the last two leads are wired for 8 and 10. The grid cannot list contacts that
  do not exist but it can list fewer than exist, so the larger number wins and
  the row is flagged.
- **Grids contain typos.** One has `LI4` twice where `LI3` belongs, leaving a
  hole mid-lead. That is reported as a probable mistyped cell, separately from
  scalp channels, and the count comes from the lead table instead.
- **Lead tables are sometimes incomplete.** One omits a lead from the final
  table that is plainly in the channel map. It is kept and flagged.
- **Not every document has a channel map.** A ROSA/DIXI list has none at all, so
  the model is the only source — see Known gaps.

## Known gaps

- **Scanned pages are reported, not read.** Pages with no text layer are listed
  in a warning so a short lead list cannot be mistaken for a complete one. OCR
  is not wired up.
- **Lead type** defaults to depth. Grids and strips need the model, or manual
  correction in the review screen.
- Only PDF and PPTX. Images are refused with a clear message.
