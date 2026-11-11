"""Capture high-resolution VoxTool screenshots for Figure 1.

Needs VoxTool running locally (./run_demo.sh) with the scan already opened once
(POST /api/scans/open_local). Writes PNGs at 2x device scale to assets/screens/.

    conda run -n voxfig python paper/figures/fig1/scripts/capture_screens.py SCAN_NAME
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5001/"
OUT = Path(__file__).resolve().parents[1] / "assets" / "screens"


def open_scan(page, scan):
    page.get_by_role("button", name="Load scan", exact=True).click()
    page.get_by_text(scan, exact=True).click()
    page.get_by_role("button", name="Load selected").click()
    page.wait_for_timeout(12000)  # NiiVue load + 3D volume render


def main(scan, tag):
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--use-angle=metal", "--enable-webgl", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.goto(URL)
        open_scan(page, scan)

        page.screenshot(path=OUT / f"{tag}_app_slices.png")

        # Electrode View: the thresholded bright-voxel cloud.
        page.get_by_text("Electrode View", exact=True).click()
        page.wait_for_timeout(15000)
        page.screenshot(path=OUT / f"{tag}_app_cloud.png")

        # Same views without the sidebar, for tighter panels.
        page.keyboard.press("f")
        page.wait_for_timeout(3000)
        page.screenshot(path=OUT / f"{tag}_cloud_nosidebar.png")
        page.get_by_role("button", name="Slices (NiiVue)").click()
        page.wait_for_timeout(8000)
        page.screenshot(path=OUT / f"{tag}_slices_nosidebar.png")
        browser.close()
    print("wrote", sorted(x.name for x in OUT.glob(f"{tag}_*.png")))


if __name__ == "__main__":
    # A third argument sends the PNGs elsewhere, e.g. private/ for scans not cleared to share.
    if len(sys.argv) > 3:
        OUT = Path(sys.argv[3]).resolve()
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "mne")
