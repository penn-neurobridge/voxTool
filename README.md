# VoxTool

Electrode contact localization on post-implant CT. This repo includes:

1. **Desktop (legacy)** — Qt / `launch_pyloc.py`
2. **Cloud web app** — React frontend + Flask API on AWS (Slice view + Threshold cloud)

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

Right now everyone shares **one** cloud deployment: the same scan list and API. That is normal for an early shared demo; scans are stored in a shared S3 bucket. Coordinate JSON files saved with **Save as…** live on each user’s machine (private). See “Shared instance” below if you want per-lab isolation later.

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
