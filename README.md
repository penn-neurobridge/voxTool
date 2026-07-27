# VoxTool

Electrode contact localization on post-implant CT. This repo includes:

1. **Desktop app (current)** — the cloud app packaged to run entirely offline (`desktop/`)
2. **Cloud web app** — React frontend + Flask API on AWS (Slice view + Threshold cloud)
3. **Desktop (legacy)** — the original Qt / Mayavi tool, `launch_pyloc.py`

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
2. Switch to **Threshold cloud**, adjust the CT threshold percentile if needed,
   and pick contacts on the bright metal cloud.
3. **Define leads**, then submit or interpolate contacts.
4. **Save Coordinates…** (`Ctrl/Cmd-S`) writes a legacy-compatible
   `voxel_coordinates.json` wherever you choose.
5. **Load Coordinates…** (`Ctrl/Cmd-Shift-O`) restores a previous session.

Derived data (the cached threshold cloud) is written to the per-user app folder,
never beside your scan — **File → Open App Data Folder** reveals it. Removing a
scan from the list only closes it; your file on disk is untouched.

### Building it yourself

See [`desktop/README.md`](desktop/README.md).

## Cloud demo (v1)

Live site (AWS CloudFront):

- **App:** https://d3mz57qb2jsoo.cloudfront.net  
- **API:** https://d3p0suxalkw0h5.cloudfront.net  

### Quick start for demos

1. Open the app URL above.
2. **Load scan** — upload a NIfTI (`.nii` / `.nii.gz`) or pick one already on the server.
3. Switch to **Threshold cloud** — adjust CT threshold (%ile) if needed, then pick contacts on the bright metal cloud.
4. **Define leads** → submit / interpolate contacts as needed.
5. **Save as…** — exports a `voxel_coordinates.json` to your computer (legacy-compatible).
6. **Load coordinates** — reopen that JSON later to restore annotations on the same scan.

Slice view (**NiiVue**) supports window presets (**Bone / Soft / Electrodes / Auto**) and layout (**4-up / A / C / S / 3D**).

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

```bash
# API
cd web/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app run   # or gunicorn, etc.

# Frontend
cd web/frontend
npm install
REACT_APP_API_URL=http://localhost:5000 npm start
```

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

## Other notes

- Contact lists are sorted by lead name, then contact number. Double-check indices after **Interpolate**.
- Cloud **Save as…** / **Load coordinates** use local JSON files (same idea as the legacy desktop dialogs).
