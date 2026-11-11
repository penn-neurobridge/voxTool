"""Atlas region for every sample contact (FreeSurfer aparc+aseg, via MNE).

This is the kind of output a downstream pipeline such as iEEG-recon gives for
VoxTool's coordinates. Here it is computed with MNE on the public sample so the
figures can show real values. Writes assets/contact_labels.json.

    conda run -n voxfig python paper/figures/fig5/scripts/label_contacts.py
"""
import json
import re
from pathlib import Path

import mne

MISC = Path.home() / "mne_data" / "dl" / "mne-misc-data-0.30" / "seeg"
OUT = Path(__file__).resolve().parents[1] / "assets" / "contact_labels.json"


def main():
    raw = mne.io.read_raw_fif(MISC / "sample_seeg_ieeg.fif", verbose="error")
    trans = mne.coreg.estimate_head_mri_t("sample_seeg", MISC)
    montage = raw.get_montage()
    montage.apply_trans(trans)  # head -> MRI, as get_montage_volume_labels expects
    labels, _ = mne.get_montage_volume_labels(montage, "sample_seeg", subjects_dir=MISC,
                                              aseg="aparc+aseg", dist=2)
    out = {}
    for ch, regions in labels.items():
        lead = re.match(r"[A-Za-z']+", ch).group(0)
        out.setdefault(lead, {})[ch] = regions
    OUT.write_text(json.dumps(out, indent=1))
    for lead, chs in out.items():
        print(lead, len(chs), list(chs.items())[0])


if __name__ == "__main__":
    main()
