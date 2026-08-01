# VoxTool

Electrode contact localization on post-implant CT.

### [Download VoxTool for macOS or Windows →](../../releases/latest)

Runs fully offline; your scans never leave your computer. First launch shows an
"unidentified developer" or SmartScreen warning because the builds are not yet
code-signed — [how to get past it](#install).

There are three ways to run the current tool, and they are **the same program** —
one React interface and one Flask backend, packaged three ways. Picking, snapping,
interpolation and export are byte-for-byte the same code in all three, so a
localization done in one is identical to the same localization done in another.

| | How you get it | Where scans live | Needs internet |
| --- | --- | --- | --- |
| **Desktop app** | Download an installer | Read in place on your disk | No |
| **Run from source** | `git clone`, then one command | Read in place on your disk | Only to install |
| **Cloud web app** | Open a URL | Uploaded to shared AWS S3 | Yes |

Use the **desktop app** or **run from source** for identifiable or otherwise
restricted imaging. Both keep every scan on your machine. The cloud app is a
shared public demo — see the warning in its section below.

They cannot drift apart, because there is nothing to keep in sync: all three
build from `web/backend` and `web/frontend` on this branch. A single environment
variable, `VOXTOOL_LOCAL`, decides whether a scan is opened in place on disk or
uploaded to S3. Nothing else differs, and no algorithm reads it.

The original Qt / Mayavi tool (`launch_pyloc.py`) is still here as
[Desktop setup (legacy)](#desktop-setup-legacy), but it pins Python 2.7 and is
superseded by the three above.

## Desktop app (offline)

Same tool as the cloud version — same picking, snapping, interpolation and
export — but everything runs on your own machine. **No scan data leaves the
computer:** the app binds to loopback only and makes no outbound requests.

Use this build for any identifiable or otherwise restricted imaging.

### Install

Download the installer for your platform from the repository's
[Releases](../../releases) page, or from the artifacts of a
**Build desktop app** run under the Actions tab.

| Platform | File |
| -------- | ---- |
| macOS (Apple Silicon) | `VoxTool-<version>-arm64.dmg` |
| macOS (Intel) | `VoxTool-<version>.dmg` |
| Windows | `VoxTool Setup <version>.exe` |

**The builds are currently unsigned**, so the OS will warn you on first launch:

- **macOS** — the app is "damaged" or "from an unidentified developer". Right-click
  the app in Applications, choose **Open**, then **Open** again. Only needed once.
  If macOS refuses outright, run `xattr -dr com.apple.quarantine /Applications/VoxTool.app`.
- **Windows** — SmartScreen shows a blue "Windows protected your PC" box. Click
  **More info** → **Run anyway**.

Getting rid of these warnings needs an Apple Developer certificate (~$99/yr) and
a Windows code-signing certificate; see `desktop/README.md`.

### Using it

1. **Open Scan…** (`Ctrl/Cmd-O`) and choose a `.nii` / `.nii.gz`. It is read
   **in place** — the file is never copied, and there is no size limit.
2. Switch to **Electrode View**, adjust the CT threshold percentile if needed,
   and pick contacts on the bright metal cloud. This is the easiest mode for
   annotating; picks made here also show up on the slices in the lead's colour.
3. **Define leads**, then submit or interpolate contacts.
4. **Save Coordinates…** (`Ctrl/Cmd-S`) writes a legacy-compatible
   `voxel_coordinates.json` or `voxel_coordinates.txt` wherever you choose —
   pick the extension in the save dialog.
5. **Load Coordinates…** (`Ctrl/Cmd-Shift-O`) restores a previous session.

Derived data (the cached threshold cloud) is written to the per-user app folder,
never beside your scan — **File → Open App Data Folder** reveals it. Removing a
scan from the list only closes it; your file on disk is untouched.

### Building it yourself

See [`desktop/README.md`](desktop/README.md).

## Run from source

The clone-and-run route, like the legacy tool. Use it when you would rather not
install anything, when there is no installer for your platform, or to try a
change you just made. It runs the same code the installer ships.

**You need:** Python 3.9+ and [Node.js](https://nodejs.org) 18+ (Node compiles the
interface; it is not needed once built).

```bash
git clone https://github.com/penn-neurobridge/voxTool.git
cd voxTool
python3 run_voxtool.py
```

That is the whole thing. It opens your browser at the tool, ready to use.

The first run takes a few minutes: it creates a `.venv`, installs the backend
dependencies, and compiles the interface. Later runs start in a couple of
seconds. Press **Ctrl+C** in the terminal to stop.

Scans are read **in place** from wherever they already are — paste a full path
into the box in the **Load a CT Scan** dialog. A browser cannot see file paths
the way a native dialog can, which is the one visible difference from the
desktop app; everything downstream is identical.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--port 5001` | Use a fixed port instead of a free one |
| `--no-browser` | Do not open a browser |
| `--rebuild-ui` | Recompile the interface after changing frontend code |
| `--no-venv` | Use the current Python instead of creating `.venv` |

Notes:

- The server binds to `127.0.0.1`, so nothing on the network can reach your scans.
- Cached threshold clouds go to the per-user app folder, never next to your scan.
- It refuses to reuse an interface compiled for the cloud, which would otherwise
  send this "local" app back to AWS. If you have built the frontend for
  deployment, expect one automatic recompile.

## Cloud demo (v1)

Live site (AWS CloudFront):

- **App:** https://d3mz57qb2jsoo.cloudfront.net  
- **API:** https://d3p0suxalkw0h5.cloudfront.net  

### Quick start for demos

1. Open the app URL above.
2. **Load scan** — upload a NIfTI (`.nii` / `.nii.gz`) or pick one already on the server.
3. Switch to **Electrode View** — adjust CT threshold (%ile) if needed, then pick contacts on the bright metal cloud.
4. **Define leads** → submit / interpolate contacts as needed.
5. **Save as…** — exports `voxel_coordinates.json` or `voxel_coordinates.txt` to your computer (both legacy-compatible).
6. **Load coordinates** — reopen either file later to restore annotations on the same scan.

Slice view (**NiiVue**) supports window presets (**Bone / Soft / Electrodes / Auto**) and layout (**4-up / A / C / S / 3D**).

In a single plane (**A / C / S**) a slice navigator appears above the image with
a slider, prev/next buttons, and a `Axial slice 122 / 242` readout. The mouse
wheel and `↑`/`↓` step it too. Clicking only moves the crosshair *within* the
plane you clicked — it cannot change that plane's own slice, which is why 4-up
updates the other two panes but never the one under your cursor.

Contact markers clip to the slice you are on rather than floating over every
slice, and show through the skull in the 3D render so a whole implant is visible
at once.

### Notes for multi-user demos

> **The cloud deployment has no authentication.** Everyone shares one instance,
> and anyone with the URL can list and download every scan that has been
> uploaded to it. Treat it as a public demo and upload only de-identified data.
> Use the offline desktop app for anything restricted.

Scans live in a shared S3 bucket. Coordinate JSON files saved with **Save as…**
stay on each user's own machine. Per-user accounts and isolation are planned.

---

## Desktop setup (legacy)

- Clone the repository from GitHub
- Create a Conda environment from the definition file:

```bash
conda env create -f conda_env.yml
```

This creates an environment named `vt`.

## Running (desktop)

```bash
source activate vt   # or: conda activate vt
python launch_pyloc.py
```

## Usage (desktop / concepts carry to cloud)

0. Load a CT file, adjusting the threshold as necessary. To adjust the
   threshold, change the number in the bar marked `CT Threshold`, then press `Update`.
1. If continuing a previous localization: load the existing coordinates
   from a JSON coordinate file using **Load coordinates**.
2. Press **Define leads** to set names, shapes, and types for each implanted lead
   (shapes are rows × columns).
3. Select the lead in the **Label** dropdown.
4. Click the CT / threshold cloud to highlight the next contact, then **Submit**.
   - Or add endpoints / corners and press **Interpolate** to fill remaining contacts.
5. Press **Save as…** to save localized contacts as JSON.

## Local web development

To just run the tool, use `python3 run_voxtool.py` (above). For frontend work you
want hot reload, so run the two processes separately:

```bash
# API — VOXTOOL_LOCAL opens scans in place and skips S3
cd web/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-desktop.txt
VOXTOOL_LOCAL=1 PORT=5001 python desktop_server.py

# Frontend (separate terminal) — package.json proxies /api to port 5001
cd web/frontend
npm install
npm start
```

Drop `VOXTOOL_LOCAL` and install `requirements.txt` instead to develop against
cloud behaviour (uploads, S3, the 150 MB cap).

Infra lives under `terraform/` (dev: S3 + CloudFront + Elastic Beanstalk).

## Keyboard shortcuts (desktop)

| Button | Key Sequence |
| ------ | ------------ |
| Load Scan | Ctrl-O |
| Define Leads | Ctrl-D |
| Save As | Ctrl-S |
| Submit (contact panel) | S |
| Submit (lead definition window) | S |
| Delete (contact panel)| Delete |
| Delete (lead definition window)| Delete |
| Confirm (lead definition window) | Enter |

### Viewer keys (desktop and cloud)

| Action | Key |
| ------ | --- |
| Submit pending contact | S |
| Cancel pending contact | Esc |
| Show / hide the sidebar | F |
| 4-up / Axial / Coronal / Sagittal / 3D | 0 / 1 / 2 / 3 / 4 |
| Next / previous slice (single plane) | ↑ / ↓ (or PageUp / PageDown) |

### Mouse

| Action | Slices | Electrode View |
| ------ | ------ | -------------- |
| Place the crosshair / pick a contact | click | click |
| Move the image around | drag | Shift-drag (or right-drag) |
| Zoom | Ctrl/Cmd + scroll | scroll |
| Change slice | scroll | — |
| Rotate the 3D render | drag inside the 3D tile | drag |

Dragging the slices pans without moving the crosshair, so the point you are
about to Submit stays put while you look around. **Reset view** appears in the
corner once the image has been panned or zoomed.

## Other notes

- Contact lists are sorted by lead name, then contact number. Double-check indices after **Interpolate**.
- Cloud **Save as…** / **Load coordinates** use local JSON files (same idea as the legacy desktop dialogs).
