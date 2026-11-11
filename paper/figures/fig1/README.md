# Figure 1: overview (v1 layout)

`fig1_v1.svg` is the editable layout (open it in Affinity; images are linked from
`assets/`, so each one stays a separate layer you can swap). `fig1_v1.png` is a
2x preview.

All imagery is from MNE-Python's public `sample_seeg` subject (mne-misc-data
0.30, BSD-3). No lab or patient data is used. `private/` and `assets/raw/` are
git-ignored; keep anything not cleared for sharing there.

## Rebuild

1. Download mne-misc-data 0.30 to `~/mne_data/dl/` and convert
   `seeg/sample_seeg_CT.mgz` to `assets/raw/mne_sample_seeg_CT.nii.gz`.
2. Start VoxTool (`./run_demo.sh`) and open that file once.
3. In the `voxfig` conda env (mne-base, pyvista, nibabel, cairosvg, playwright):

```bash
conda run -n voxfig python paper/figures/fig1/scripts/capture_screens.py mne_sample_seeg_CT.nii.gz mne
conda run -n voxfig python paper/figures/fig1/scripts/render_brain.py
conda run -n voxfig python paper/figures/fig1/scripts/compose_fig1.py
```

## v2 (four panels, labeled contacts)

`fig1_v2.svg` / `.png` loads all 119 published sample contacts into VoxTool, so
the screenshots show real labeled leads. The contacts come from MNE's montage,
carried onto the CT with a CT-to-T1 rigid registration (as in MNE's sEEG
tutorial), then snapped with VoxTool's own `/snap` endpoint:

```bash
conda run -n voxfig python paper/figures/fig1/scripts/map_contacts.py   # ~3.5 min
conda run -n voxfig python paper/figures/fig1/scripts/snap_contacts.py  # VoxTool running
conda run -n voxfig python paper/figures/fig1/scripts/capture_labeled.py
conda run -n voxfig python paper/figures/fig1/scripts/compose_fig1_v2.py
```

## Still placeholders (hatched boxes)

- Operating-room photo (open craniotomy, ECoG grid + sEEG): needs a licensed source.
- Person in a CT scanner, next to the CT slice.

## Logos

`assets/logos/` holds the Pennsieve logo (`pennsieve-app` repo,
`src/assets/images/pennsieve-logo-full.svg`) and the OpenNeuro brand mark
(`openneuro` repo, `packages/openneuro-app/src/assets/brand_mark.png`). The
"OpenNeuro" wordmark next to the mark is typeset, not their artwork. Check each
project's brand rules before the figure is published.
- Coordinate values in panel 4 are shown as dots until this CT is labeled in VoxTool.
