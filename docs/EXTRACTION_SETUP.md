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

## Uploading to Pennsieve

`Upload to Pennsieve…` next to **Save as…** sends the finished annotations to a
Pennsieve dataset. Desktop only, for the same reason as extraction: the cloud
build has no authentication, and this endpoint would let anyone who found it
push files using this machine's Pennsieve credentials.

It drives the `pennsieve` CLI rather than the REST API. The agent already does
chunked, resumable uploads and owns the credentials in `~/.pennsieve/config.ini`,
so VoxTool never sees an API key and cannot leak one into a log. If the agent is
not running the dialog says so and offers to start it.

**Sending is opt-in.** The dialog previews by default — it reports the exact
destination and sends nothing until "Actually send it" is ticked. The server
defaults `dry_run` to true as well, so a mis-wired button cannot upload.

**The destination is always shown**: workspace, dataset, folder, filename.
Whatever lands in a dataset inherits that dataset's permissions, so choosing the
dataset *is* the access decision and must never be implicit. No dataset is
pre-selected, not even the agent's active one. The folder defaults to
`derivatives/voxtool_ct`, where the lab keeps VoxTool output. Pennsieve's upload
service source reuses an existing folder of the same name rather than making a
second one.

The first real upload (2026-10-06, a made-up test file into the VoxTool Test
sandbox in Penn CNT) landed in `derivatives/voxtool_ct` as intended. Its status
was still UPLOADED when the dialog's 90 s wait ran out, though the file was
already visible in the dataset, so the dialog said "sent". The sub-03 CT (77 MB,
to `primary/sub-03/ses-postimplant/ct`) did reach VERIFIED, after a few minutes
of repeated syncs. So the confirmation works but often arrives after the dialog
stops waiting; checking the dataset through the REST API would settle it
directly.

**Limiting uploads to one dataset.** Set `VOXTOOL_PENNSIEVE_DATASETS` to a
comma-separated list of `N:dataset:` ids and the dialog lists only those, and
the server refuses any other before running the CLI at all. Use it while
testing so that only the sandbox dataset can be reached.

**The CLI's word is never taken for anything.** Every `pennsieve` command exits 0
whether or not it worked. In particular, `dataset use` with a dataset the
signed-in workspace cannot see prints "Unknown Dataset" and leaves the previous
dataset active, and the upload would then go *there*. So each step is checked by
reading the agent's state back: the active dataset must equal the chosen one
before a manifest is created, the manifest must report exactly one file indexed,
and the result is decided by the file's status in `pennsieve manifest list`,
not by the upload command returning. The dialog reports one of three outcomes:
in the dataset, sent but still being imported by Pennsieve, or still uploading
in the background. The file waits in the app data folder's `pennsieve-outbox`
until the agent has sent it. `tests/test_pennsieve.py` covers each of these
against a fake CLI.

**The agent listens on the network.** Its gRPC port (9000) binds every
interface, not just this machine, and anyone who can reach it can ask for the
signed-in session. Stop it with `pennsieve agent stop` when you are not
uploading, especially on shared or public Wi-Fi.

Filenames are derived from the scan and stamped with the time —
`sub-03_ct.nii.gz` becomes `sub-03_voxel_coordinates_20260929-1804.json`. There
is deliberately no overwrite: re-annotating a subject adds a file rather than
replacing one, because losing an earlier annotation is worse than keeping two.

## Opening a scan from Pennsieve

**Load a CT Scan → From Pennsieve…** browses a dataset's folders, or takes a
file's Pennsieve ID (`N:package:…`) pasted in. The scan is downloaded into the
app data folder's `pennsieve-downloads`, one folder per package, and then
opened exactly like a scan picked from disk. A file already there at the right
size is reused, so reopening is instant. Like the rest of the app data, these
are copies of patient scans on this machine.

The CLI cannot do this: it has no command to list folders, and
`download package` writes into the agent's working directory in the background
without saying where. So `pennsieve_api.py` uses the REST API, with a session
token from the running agent's gRPC `ReAuthenticate` call — the route
Pennsieve's own Python client takes. VoxTool still never reads the API key; the
token lives in memory, expires within the hour, and belongs to whichever
profile the agent is signed in to, the same one uploads use.
`VOXTOOL_PENNSIEVE_DATASETS` limits browsing and downloads as it limits uploads.

Pennsieve's own Python package was not used: it brings pandas, boto3, numpy and
more, 261 MB against a ~110 MB installer. Only `grpcio` and `protobuf` are
added, and `pennsieve_agent/agent_pb2.py` is generated from the agent's
published proto (see that package for how to regenerate it).

**Never let an error repeat what was read from `~/.pennsieve/config.ini`.** The
CLI writes the default profile's key and secret above the first section header.
`configparser` rejects that and quotes the line in its error, which once printed
an API secret into the server log. The config is now scanned for the agent's
port alone, and these endpoints report unexpected errors by type only.

Verified on 2026-10-06: the sub-03 CT, opened from VoxTool Test by its ID,
arrived byte-for-byte identical to the original and opened normally; browsing
PennEPI00049 was refused by the dataset lock.

### Not done yet

- Only the coordinates are uploaded, not the CT or the implant document. The
  dialog sends JSON (VoxTool's full record), TXT (the layout of the lab's
  `electrodes.txt`), or both as one upload with a shared timestamp. The TXT
  writes a depth lead's dimensions as `N 1`, as the lab's files do, though the
  app stores it as `[1, N]`. Whether the TXT should be named exactly
  `electrodes.txt` is still open; Pennsieve would then keep re-uploads as
  `electrodes (1).txt` rather than replacing the file.
- Choosing an upload destination by its Pennsieve ID, or from the folder
  browser, is not done; the upload still takes a typed path, since
  `--target_path` takes nothing else. The browser's REST calls give the path
  for any folder ID, which is what that needs.
- The desktop installer has not been rebuilt with `grpcio` and `protobuf`; the
  PyInstaller spec names the new modules, but a packaged build is untested.
- API keys are per-workspace in Pennsieve, so working in a different workspace
  needs a new key and a second profile (`pennsieve profile create`).
