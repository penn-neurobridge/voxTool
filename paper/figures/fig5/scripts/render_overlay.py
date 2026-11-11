"""Figure 5 output panel: the CT's metal on the patient's MRI after CT-to-MRI
registration (what iEEG-recon's Module 2 does), for the public MNE sample.

Uses the rigid registration map_contacts.py saved, applied with MNE. Writes
assets/renders/ct_on_mri_coronal.png.

    conda run -n voxfig python paper/figures/fig5/scripts/render_overlay.py
"""
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import mne
import nibabel as nib
import numpy as np

matplotlib.use("Agg")

MISC = Path.home() / "mne_data" / "dl" / "mne-misc-data-0.30" / "seeg"
FIGS = Path(__file__).resolve().parents[2]
REG = FIGS / "fig1" / "assets" / "raw" / "ct_to_t1_reg_affine.npy"
OUT = FIGS / "fig5" / "assets" / "renders"
CHANNEL = "RAHP 3"  # coronal slice through the right hippocampal lead
WARM = "#e4572e"


def main():
    t1 = nib.load(MISC / "sample_seeg" / "mri" / "T1.mgz")
    ct = nib.load(MISC / "sample_seeg_CT.mgz")
    ct_in_t1 = mne.transforms.apply_volume_registration(ct, t1, np.load(REG), verbose=False)
    ct_data = np.asarray(ct_in_t1.dataobj)
    t1_data = np.asarray(t1.dataobj)

    raw = mne.io.read_raw_fif(MISC / "sample_seeg_ieeg.fif", verbose="error")
    trans = mne.coreg.estimate_head_mri_t("sample_seeg", MISC)
    montage = raw.get_montage()
    montage.apply_trans(trans)
    xyz = montage.get_positions()["ch_pos"][CHANNEL] * 1000.0
    vox = np.linalg.inv(t1.header.get_vox2ras_tkr()) @ np.r_[xyz, 1.0]
    i, j, k = np.round(vox[:3]).astype(int)

    # FreeSurfer's conformed T1 is LIA: axis 2 runs anterior -> posterior, so a
    # fixed index on it is a coronal slice; rows are axis 1 (inferior).
    mri = t1_data[:, :, k].T
    metal = ct_data[:, :, k].T
    # Thicken the overlay a little (max over neighbouring slices) so contacts read clearly.
    metal = np.max(ct_data[:, :, k - 2:k + 3], axis=2).T
    mask = np.ma.masked_where(metal < 2500, np.ones_like(metal, dtype=float))

    OUT.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(6, 6), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(mri, cmap="gray", vmin=0, vmax=np.percentile(mri, 99.5), interpolation="bilinear")
    ax.imshow(mask, cmap=matplotlib.colors.ListedColormap([WARM]), interpolation="nearest",
              alpha=0.95)
    ax.set_xlim(30, 226)
    ax.set_ylim(206, 30)
    ax.set_axis_off()
    fig.savefig(OUT / "ct_on_mri_coronal.png", facecolor="black")
    plt.close(fig)
    print("slice", k, "through", CHANNEL, "->", OUT / "ct_on_mri_coronal.png")


if __name__ == "__main__":
    main()
