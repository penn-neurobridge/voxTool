"""Capture VoxTool's Electrode View at rising CT thresholds for Figure 2.

Needs VoxTool running locally with the MNE sample CT opened once, and the
cloud caches for each threshold built (POST threshold_cloud, then poll
cloud_ready). Writes assets/screens/cloud_p{pct}.png at 2x.

    conda run -n voxfig python paper/figures/fig2/scripts/capture_thresholds.py
"""
import json
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5001/"
SCAN = "mne_sample_seeg_CT.nii.gz"
OUT = Path(__file__).resolve().parents[1] / "assets" / "screens"
# Whole skull, dense bone only, metal and teeth only. Lower percentiles would
# show skin, and so the face, so the series starts at bone.
THRESHOLDS = [90, 98, 99.96]


def wait_ready(pct, timeout=900):
    url = f"{URL}api/scans/{SCAN}/cloud_ready?threshold_pct={pct}"
    end = time.time() + timeout
    while time.time() < end:
        with urllib.request.urlopen(url) as r:
            if json.load(r)["ready"]:
                return
        time.sleep(5)
    raise TimeoutError(f"cloud at {pct} never became ready")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for pct in THRESHOLDS:
        wait_ready(pct)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--use-angle=metal", "--enable-webgl",
                                          "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.goto(URL)
        page.get_by_role("button", name="Load scan", exact=True).click()
        page.get_by_text(SCAN, exact=True).click()
        page.get_by_role("button", name="Load selected").click()
        page.wait_for_timeout(10000)
        page.get_by_text("Electrode View", exact=True).click()
        page.wait_for_timeout(8000)
        page.keyboard.press("f")  # hide the sidebar
        for pct in THRESHOLDS:
            box = page.get_by_role("textbox", name="Percentile for bright-voxel display, "
                                                   "snap, cloud pick, and interpolation "
                                                   "(default 99.96)")
            box.fill(str(pct))
            page.get_by_role("button", name="Update", exact=True).click()
            page.wait_for_timeout(20000)
            page.get_by_role("button", name="Reset view").click()
            page.wait_for_timeout(1500)
            # The same tilt for every threshold, so the panels line up.
            page.mouse.move(1000, 740)
            page.mouse.down()
            page.mouse.move(1000, 520, steps=25)
            page.mouse.move(1130, 520, steps=25)
            page.mouse.up()
            page.mouse.wheel(0, -150)
            page.wait_for_timeout(3000)
            page.screenshot(path=OUT / f"cloud_p{pct}.png")
        browser.close()
    print("wrote", sorted(x.name for x in OUT.glob("cloud_p*.png")))


if __name__ == "__main__":
    main()
