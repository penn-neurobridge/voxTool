"""Capture VoxTool screenshots with the sample's contacts loaded and labeled.

Needs VoxTool running locally and assets/sample_seeg_voxel_coordinates.json
(map_contacts.py, then snap_contacts.py).

    conda run -n voxfig python paper/figures/fig1/scripts/capture_labeled.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

from capture_screens import URL, open_scan

FIG = Path(__file__).resolve().parents[1]
OUT = FIG / "assets" / "screens"
COORDS = FIG / "assets" / "sample_seeg_voxel_coordinates.json"
SCAN = "mne_sample_seeg_CT.nii.gz"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--use-angle=metal", "--enable-webgl",
                                          "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.on("dialog", lambda d: d.accept())
        page.goto(URL)
        open_scan(page, SCAN)
        page.locator('input[type="file"][accept^=".json"]').set_input_files(str(COORDS))
        page.wait_for_timeout(5000)
        page.screenshot(path=OUT / "labeled_app_slices.png")

        page.get_by_text("Electrode View", exact=True).click()
        page.wait_for_timeout(15000)
        page.screenshot(path=OUT / "labeled_app_cloud.png")
        page.keyboard.press("f")
        page.wait_for_timeout(3000)
        # Zoom in and tilt to an oblique view so the leads fill the frame.
        page.mouse.move(1000, 740)
        for _ in range(2):
            page.mouse.wheel(0, -150)
            page.wait_for_timeout(200)
        page.mouse.down()
        page.mouse.move(1000, 640, steps=20)
        page.mouse.move(1080, 640, steps=20)
        page.mouse.up()
        page.wait_for_timeout(2000)
        page.screenshot(path=OUT / "labeled_cloud_nosidebar.png")
        browser.close()
    print("wrote", sorted(x.name for x in OUT.glob("labeled_*.png")))


if __name__ == "__main__":
    main()
