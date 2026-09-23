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

Measured on eleven real implant documents (Apple Silicon,
qwen2.5:7b-instruct). Ten share one format and carry 144 leads between them:

| | Leads found | Contact counts | Flagged |
|---|---|---|---|
| Channel map only | 142/144 | 140/144 | 1 |
| With the local model | **144/144** | **144/144** | 1 |

Four of the ten (sub-01, 02, 07, 08) were held out and never looked at while
the rules were being written. Three of those four scored perfectly with no code
changes at all; the fourth exposed a grid format that needed new handling. The
one flagged lead is a document that writes `RFp` in its lead table and `RPf` in
its grid — kept as two rows and marked as a probable transposition, because
merging them would be a guess.

Each of these came from a document and changed the code:

- **A recording can be shorter than the electrode.** One implant has 22
  twelve-contact leads, needing 264 channels against an amplifier's 256, so the
  last two are wired for 8 and 10. A grid cannot list contacts that do not
  exist but it can list fewer than exist, so the larger count wins.
- **Grids contain typos.** One has `LI4` twice where `LI3` belongs. That is
  reported as a probable mistyped cell, separately from scalp channels.
- **Lead tables are sometimes incomplete.** One omits a lead that is plainly in
  the grid. It is kept and flagged.
- **Some grids have no contact numbers**, repeating the bare label once per
  contact (`LI LI LI …`). The repeats are counted, but only on rows that are
  almost entirely bare labels.
- **Reference markers look like contacts.** `Ref: LF10` on the lead-table slide
  must not disqualify LF from being counted, and `RA5` in a green cell is a
  reference, not a five-contact lead.

## Known gaps

- **Scanned pages are reported, not read.** Pages with no text layer are listed
  in a warning so a short lead list cannot be mistaken for a complete one. OCR
  is not wired up. One of the eleven documents (sub-11) is a pure image with no
  text layer anywhere, so the tool currently extracts nothing from it at all.
- **One document uses a different system entirely** (sub-11: ROSA/DIXI, no
  channel map, electrodes named `1. aMTG-Amyg`). Those names will not survive
  VoxTool's save format, and it lists both implanted and intracerebral contact
  counts. Undecided pending the lab's convention.
- **Lead type** defaults to depth. Grids and strips need the model, or manual
  correction in the review screen.
- Only PDF and PPTX. Images are refused with a clear message.
