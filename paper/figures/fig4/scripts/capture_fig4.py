"""Capture Figure 4's steps in the real app: read the plan, mark a lead's two
end contacts, interpolate the rest, save.

Needs VoxTool running locally (./run_demo.sh, with Ollama for the local model)
and the sample CT opened once. Writes PNGs to assets/screens/ and the exported
coordinates to assets/exported_voxel_coordinates.txt.

    conda run -n voxfig python paper/figures/fig4/scripts/capture_fig4.py
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5001/"
SCAN = "mne_sample_seeg_CT.nii.gz"
FIGS = Path(__file__).resolve().parents[2]
A = FIGS / "fig4" / "assets"
OUT = A / "screens"
PLAN = A / "example_implant_plan.pdf"
ALL = FIGS / "fig1" / "assets" / "sample_seeg_voxel_coordinates.json"
ENDS = A / "lead_ends_only.json"
# RAHP sits near the middle of Electrode View's default camera, so zooming
# (which always heads for the screen centre) keeps it in frame.
LEAD = "RAHP"
ZOOM_TICKS = 3
# Where RAHP lands after that zoom, in 2x screenshot pixels (x0, y0, x1, y1).
LEAD_CROP = (1928, 1035, 2576, 1300)


def write_ends_file():
    """Every lead defined, but only LEAD's first and last contact placed."""
    doc = json.loads(ALL.read_text())
    for name, lead in doc["leads"].items():
        if name == LEAD:
            lead["contacts"] = [lead["contacts"][0], lead["contacts"][-1]]
        else:
            lead["contacts"] = []
    ENDS.write_text(json.dumps(doc, indent=1))
    return doc["leads"][LEAD]["dimensions"][1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    n_contacts = write_ends_file()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--use-angle=metal", "--enable-webgl",
                                          "--ignore-gpu-blocklist"])
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000},
                                  device_scale_factor=2, accept_downloads=True)
        # Without the native save picker the app asks json/txt and downloads instead.
        ctx.add_init_script("delete window.showSaveFilePicker;")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept("txt" if d.type == "prompt" else None))
        page.goto(URL)
        page.get_by_role("button", name="Load scan", exact=True).click()
        page.get_by_text(SCAN, exact=True).click()
        page.get_by_role("button", name="Load selected").click()
        page.wait_for_timeout(10000)

        # 1 · Read the implant plan with the local model.
        page.get_by_role("button", name="▶ Define leads").click()
        page.get_by_role("button", name="Read from document…").click()
        page.locator(".modal select").select_option("ollama")
        page.locator('input[type="file"][accept=".pdf,.pptx"]').set_input_files(str(PLAN))
        page.get_by_role("button", name="Back").wait_for(timeout=300000)
        page.wait_for_timeout(1000)
        page.locator(".modal").screenshot(path=OUT / "step1_plan_read.png")
        page.locator(".modal .btn-primary").click()
        page.wait_for_timeout(1500)

        # 2 · The two end contacts of one lead.
        page.locator('input[type="file"][accept^=".json"]').set_input_files(str(ENDS))
        page.wait_for_timeout(4000)
        page.get_by_text("Electrode View", exact=True).click()
        page.wait_for_timeout(15000)
        page.mouse.move(1212, 747)
        for _ in range(ZOOM_TICKS):
            page.mouse.wheel(0, -150)
            page.wait_for_timeout(300)
        page.wait_for_timeout(2500)  # let the trackball damping settle
        page.screenshot(path=OUT / "step2_ends.png")

        # 3 · Interpolate fills in the contacts between them.
        page.locator("select").first.select_option(label=f"{LEAD} (1×{n_contacts})")
        page.get_by_role("button", name="Interpolate").click()
        page.wait_for_timeout(8000)
        page.screenshot(path=OUT / "step3_interpolated.png")
        # The status message by itself: its size depends on what it says.
        page.locator(".interp-status").screenshot(path=OUT / "step3_status.png")

        # 4 · Save as TXT.
        with page.expect_download() as dl:
            page.get_by_text("Save as…", exact=True).click()
        dl.value.save_as(A / "exported_voxel_coordinates.txt")
        browser.close()
    (A / "lead_crop_box.json").write_text(json.dumps(LEAD_CROP))
    print("wrote", sorted(x.name for x in OUT.glob("step*.png")))


if __name__ == "__main__":
    main()
