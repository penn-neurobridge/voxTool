# Evaluation samples

Put implant documents here (`.pdf` / `.pptx`) together with a hand-written
`<name>.expected.json` for each:

```json
{
  "leads": [
    {"name": "LA", "contacts": 12, "target": "Left Amygdala"},
    {"name": "LB", "contacts": 8,  "target": "Left Hippocampal Head"}
  ]
}
```

Nothing in this directory is committed. These are clinical documents and the
repository is shared, so they stay on the machine doing the evaluation.

Run: `python eval/run_eval.py` from `web/backend`.
