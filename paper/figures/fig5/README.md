# Figure 5: from VoxTool's coordinates to brain regions (v1)

`fig5_v1.svg` / `.png`. iEEG-recon is drawn as a labeled black box; the module
descriptions follow its docs (github.com/penn-cnt/ieeg-recon, docs/source).
Module 1 of iEEG-recon is VoxTool.

The outputs are real but computed with MNE-Python on the public sample, standing
in for iEEG-recon's Modules 2 and 3: the rigid CT-to-MRI registration from
`../fig1/scripts/map_contacts.py`, and FreeSurfer aparc+aseg labels
(`label_contacts.py`). To show iEEG-recon's own outputs, run it on the sample.

```bash
conda run -n voxfig python paper/figures/fig5/scripts/label_contacts.py
conda run -n voxfig python paper/figures/fig5/scripts/render_overlay.py
conda run -n voxfig python paper/figures/fig5/scripts/compose_fig5.py
```
