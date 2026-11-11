# Figure 2: the two coordinate systems (v1)

`fig2_v1.svg` (editable) and `fig2_v1.png` (2x preview).

- **A, voxel coordinates:** an axial CT slice and a zoom onto the voxel grid
  around contact LENT 3, with its (i, j, k) and the affine that maps it to
  millimetres. Rendered from the CT with matplotlib.
- **B, millimetre coordinates:** VoxTool 1.1.1's Electrode View at the 90th,
  98th and 99.96th percentiles (whole skull, dense bone, electrodes and teeth).
  The series starts at bone on purpose: lower thresholds show skin, and so the face.

Same public data as Figure 1 (MNE `sample_seeg`); the contact comes from
`../fig1/assets/sample_seeg_voxel_coordinates.json`.

## Rebuild

With VoxTool running and the sample CT opened once:

```bash
conda run -n voxfig python paper/figures/fig2/scripts/capture_thresholds.py
conda run -n voxfig python paper/figures/fig2/scripts/render_voxels.py
conda run -n voxfig python paper/figures/fig2/scripts/compose_fig2.py
```

`capture_thresholds.py` waits for each threshold's cloud cache; building the
90th-percentile one takes a few minutes the first time.
