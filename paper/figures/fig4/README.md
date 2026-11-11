# Figure 4: labeling a patient step by step (v1)

`fig4_v1.svg` / `.png`. Every panel except the inset is a real VoxTool 1.1.1
screenshot or file, on the public MNE sample CT:

1. **Read the implant plan** with the local model (Ollama, qwen2.5:7b). The
   sample has no surgical plan, so `make_plan.py` builds an example one from
   its recorded channels; each target is the atlas region at the lead's
   deepest contact. The page says it is not a clinical document.
2. **Mark the two end contacts** of RAHP (loaded from a coordinates file).
3. **Interpolate:** VoxTool fills and snaps the 6 between.
4. **Save:** the TXT VoxTool exported (`assets/exported_voxel_coordinates.txt`).

The inset replays VoxTool's `snap()` (routes/scans.py) on the CT and draws one
slice of it (`render_snap.py`).

```bash
conda run -n voxfig python paper/figures/fig5/scripts/label_contacts.py   # targets for the plan
conda run -n voxfig python paper/figures/fig4/scripts/make_plan.py
conda run -n voxfig python paper/figures/fig4/scripts/capture_fig4.py     # VoxTool + Ollama running
conda run -n voxfig python paper/figures/fig4/scripts/render_snap.py
conda run -n voxfig python paper/figures/fig4/scripts/compose_fig4.py
```

RAHP is used because it sits near the middle of Electrode View's default
camera; the trackball zoom always heads for the screen centre, so leads near
the edge leave the frame.
