# Professor review: try the web prototype

This document is for anyone (including course staff) who wants to **run the new browser-based voxTool prototype** on their machine and give structured feedback. The classic desktop app (`python launch_pyloc.py`) is unchanged; this is an **additional** path under `web/`.

---

## 1. What to install

- **Python 3.10+** (3.11 or 3.12 is fine)
- **Node.js 18+** and npm  
- A modern **Chrome or Firefox** window

Docker Compose under `web/docker-compose.yml` is still a **placeholder** (no Dockerfiles yet). Use the **two-terminal** flow below.

---

## 2. Get the code

```bash
git clone https://github.com/penn-neurobridge/voxTool.git
cd voxTool
git checkout web-app
```

---

## 3. Add a CT volume (required once)

NIfTI volumes are **not** stored in git (size + privacy).

1. Copy your CT (e.g. `example.nii.gz`) into:

   `voxTool/web/backend/data/`

2. The filename must match what you load in the UI (or adjust after **Load Scan**).

If you use the tracked demo annotation `web/backend/annotations/example.json`, it references **`example.nii.gz`** — put that file in `data/` with that exact name, or load your own scan and use **Load Coordinates** with a JSON that matches your filename.

---

## 4. Run the backend (terminal 1)

```bash
cd voxTool/web/backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Leave this running. The API listens on **http://127.0.0.1:5001** (health check: http://127.0.0.1:5001/api/health ).

---

## 5. Run the frontend (terminal 2)

```bash
cd voxTool/web/frontend
npm install
npm start
```

The app opens at **http://localhost:3000** and proxies API calls to port **5001**.

---

## 6. Suggested click path (about 10–15 minutes)

Use this sequence so you hit every major surface we care about.

| Step | Action | What to notice |
|------|--------|----------------|
| 1 | **Load Scan** → pick `example.nii.gz` (or your file) | Volume loads; multiplanar NiiVue appears. |
| 2 | **Define leads** → add at least one depth lead (e.g. 1×8), **select** it in **Label** | Sidebar matches desktop-style lead definition. |
| 3 | **Slices** tab: move crosshair, observe **snap** (centroid) when stable | Bright-voxel snap vs raw click. |
| 4 | Set **CT threshold (%ile)** → **Update** (default **99.96**, same as desktop) | Applies to slices, cloud, snap, and interpolate. |
| 5 | **Threshold cloud** tab: click **Refresh cloud** if needed after threshold change | Dense point cloud; orange blob after click. |
| 6 | With a lead selected, **click** on an electrode in the cloud → **Submit** (or **S**) | Contact list grows; yellow pending → committed. |
| 7 | Mark a **second** contact on the same lead, then **Interpolate** | Filled contacts along straight line + legacy snap. |
| 8 | Add a **second lead**, mark a few contacts, interpolate | **Two colors** of shaft lines in the cloud; slice view shows **connectome edges** between contacts. |
| 9 | **Save** / **Load Coordinates** round-trip with JSON | Same format family as desktop workflow. |

**Keyboard:** **S** submit pending contact, **Esc** cancel, **F** toggle sidebar (where implemented).

---

## 7. Feedback we are looking for

Short notes on any of these help us prioritize:

- **Clinical / labeling:** Is snap + cloud pick trustworthy enough vs desktop picking?
- **Interpolation:** Does straight-line + snap behavior match the desktop tool on real anatomy?
- **Cognitive load:** Two tabs (slices vs cloud) — is that clearer or more confusing than one desktop window?
- **Gaps:** What is still missing before you would assign this to a student or use it in lab?

Reply in email, a shared doc, or GitHub **Issues** on the repo — whatever is easiest.

---

## 8. Web prototype vs. classic desktop voxTool

This is **not** a line-by-line transcript of any single meeting; it is a concise list of **what the web branch adds or changes** relative to the original PyQt tool described in the root `README.md`.

| Area | Classic desktop (`launch_pyloc.py`) | Web prototype (`web/`) |
|------|-------------------------------------|-------------------------|
| **Host** | Local Qt app, conda env `vt` | Browser UI + Flask API |
| **Slice viewing** | Built-in slice / point cloud views | **[NiiVue](https://niivue.com/)** multiplanar + optional 3D render |
| **3D threshold cloud** | Point cloud in desktop viewer | **Separate tab**: Three.js cloud + **per-lead polylines** (thick screen-space lines, distinct colors) |
| **Picking** | Click CT / point cloud in-app | Slices: location + **snap** (3 mm, 99.96 %ile); Cloud: **26-connected bright blob** capped at ~6 mm from click |
| **Interpolation** | Straight line + proximity snap (`model/interpolator.py`) | Same legacy math via `/api/scans/.../interpolate` (straight chord + 3 mm snap for depth leads) |
| **CT threshold** | Single **99.96** percentile in desktop | One **CT threshold (%ile)** control shared across tabs |
| **Volume appearance** | Standard CT render + window presets | NiiVue **Bone / Electrodes / Soft / Auto** + Min/Max sliders (slices tab only) |
| **Persistence** | Save JSON from desktop | **Save / Load** via API + downloads; demo `example.json` can be tracked for teaching |
| **Bipolar pairs** | Checkbox on save | Same concept where wired in web save payload |

---

## 9. Branch and push

Active development for this prototype is on **`web-app`**. `master` remains the classic desktop line unless the team merges intentionally.

After `git pull` on `web-app`, repeat sections 4–5 whenever you want the latest behavior.
