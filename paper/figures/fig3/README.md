# Figure 3: where VoxTool runs and where the data lives (v1)

`fig3_v1.svg` / `.png`. A diagram, drawn from what the code does today:

- **A, the 2 × 2:** desktop app (or run from source) vs web app, CT on your
  computer vs in the cloud. Pennsieve works only in the desktop app
  (`web/backend/routes/pennsieve.py` refuses in cloud mode); the web app stores
  uploaded scans on the server and in S3 (`scan_store.py`) and has no login.
- **B, the Pennsieve flow:** VoxTool gets a session token from the local
  Pennsieve agent, browses and downloads through the REST API
  (`pennsieve_api.py`), and uploads through the agent (`pennsieve_sync.py`).
  OpenNeuro is shown as planned; there is no OpenNeuro code yet.

```bash
conda run -n voxfig python paper/figures/fig3/scripts/compose_fig3.py
```
