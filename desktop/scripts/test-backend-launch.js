#!/usr/bin/env node
"use strict";

/**
 * Smoke test for the desktop launch path, without Electron.
 *
 * Exercises exactly what main.js does at startup — pick a port, spawn the
 * backend, wait for health — and then drives a scan through the endpoints the
 * UI depends on. Run with:  node scripts/test-backend-launch.js [--packaged]
 */

const fs = require("fs");
const os = require("os");
const path = require("path");

const {
  findFreePort,
  startBackend,
  waitForHealth,
  stopBackend,
} = require("../backend-process");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const packaged = process.argv.includes("--packaged");

let failures = 0;
function check(name, ok, detail = "") {
  const mark = ok ? "  ok  " : " FAIL ";
  console.log(`[${mark}] ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures += 1;
}

/** Build a tiny NIfTI with a known straight electrode using the backend's own numpy. */
function makeFixture(python) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "voxtool-fixture-"));
  const out = path.join(dir, "fixture_ct.nii.gz");
  const script = `
import nibabel as nib, numpy as np
shape = (72, 72, 48)
vol = np.random.normal(110, 20, shape).astype(np.float32)
for i in range(6):
    x = 20 + i * 6
    vol[x-1:x+2, 36-1:36+2, 24-1:24+2] = 3000.0
aff = np.diag([1.0, 1.0, 1.0, 1.0]); aff[:3, 3] = [-36.0, -36.0, -24.0]
nib.save(nib.Nifti1Image(vol, aff), ${JSON.stringify(out)})
`;
  const { execFileSync } = require("child_process");
  execFileSync(python, ["-c", script], { stdio: "inherit" });
  return out;
}

/** An invented implant PDF whose channel map holds LA1-8 and RB1-6. */
function makeDocument(python, dir) {
  const out = path.join(dir, "invented_implant.pdf");
  const script = `
import pymupdf
doc = pymupdf.open()
page = doc.new_page()
grid = " ".join(f"LA{i}" for i in range(1, 9)) + "\\n" + " ".join(f"RB{i}" for i in range(1, 7))
page.insert_text((72, 72), "Channel map\\n" + grid, fontsize=10)
doc.save(${JSON.stringify(out)})
`;
  const { execFileSync } = require("child_process");
  execFileSync(python, ["-c", script], { stdio: "inherit" });
  return out;
}

/** Prefer the freeze venv (has nibabel); fall back to whatever CI exposes. */
function fixturePython() {
  if (process.env.VOXTOOL_PYTHON) return process.env.VOXTOOL_PYTHON;
  const isWin = process.platform === "win32";
  const venv = path.join(
    PROJECT_ROOT,
    "desktop",
    ".venv-build",
    isWin ? "Scripts" : "bin",
    isWin ? "python.exe" : "python"
  );
  if (fs.existsSync(venv)) return venv;
  return isWin ? "python" : "python3";
}

async function main() {
  const python = fixturePython();
  const port = await findFreePort();
  check("found a free loopback port", Number.isInteger(port) && port > 1024, `port ${port}`);

  if (packaged) {
    const exeName =
      process.platform === "win32" ? "voxtool-backend.exe" : "voxtool-backend";
    const exe = path.join(PROJECT_ROOT, "desktop", "resources", "backend", exeName);
    check("frozen backend is staged", fs.existsSync(exe), exe);
  }

  const log = [];
  const proc = startBackend({
    port,
    isDev: !packaged,
    projectRoot: PROJECT_ROOT,
    resourcesPath: path.join(PROJECT_ROOT, "desktop", "resources"),
    // Same path Electron uses in the packaged app: plain files, not _internal.
    staticDir: path.join(PROJECT_ROOT, "web", "frontend", "build"),
  });
  proc.stdout?.on("data", (d) => log.push(d.toString()));
  proc.stderr?.on("data", (d) => log.push(d.toString()));
  proc.on("error", (err) => log.push(`spawn error: ${err.message}\n`));

  const base = `http://127.0.0.1:${port}`;
  const api = (p) => `${base}/api/scans${p}`;

  try {
    const health = await waitForHealth(port, {
      timeoutMs: 60_000,
      proc,
      tail: () => log.slice(-15).join(""),
    });
    check("backend reports healthy", health.status === "ok");
    check("running in local mode", health.local === true);
    if (packaged) {
      check("UI bundle is packaged with the backend", health.ui === true, health.static_dir || "");
    }
    check(
      "state kept in per-user app folder",
      typeof health.data_dir === "string" && !health.data_dir.includes("web/backend/data"),
      health.data_dir
    );
    // Both are imported only on first use, so a build missing them would still
    // pass every check above and fail in front of a user.
    check("bundles the implant-document reader", health.features?.document_reading === true);
    check("bundles the Pennsieve agent client", health.features?.pennsieve === true);

    const uiRes = await fetch(`${base}/`);
    const html = await uiRes.text();
    check(
      "serves the built React UI",
      uiRes.ok && html.includes("<div id=\"root\">"),
      `HTTP ${uiRes.status}`
    );
    const scriptMatch = html.match(/\/static\/js\/main\.[^"']+\.js/);
    if (scriptMatch) {
      const jsRes = await fetch(`${base}${scriptMatch[0]}`, {
        signal: AbortSignal.timeout(30_000),
      });
      const head = (await jsRes.text()).slice(0, 60);
      check(
        "UI JavaScript bundle is downloadable",
        jsRes.ok && !head.includes("<!DOCTYPE") && !head.includes("<html"),
        `HTTP ${jsRes.status}`
      );
    } else {
      check("UI JavaScript bundle is downloadable", false, "no script tag in index.html");
    }

    // Open a scan in place, from a directory the app does not manage.
    const fixture = makeFixture(python);
    const openRes = await fetch(api("/open_local"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: fixture }),
    });
    const opened = await openRes.json();
    check("opens a scan in place from an arbitrary path", opened.success === true, opened.error || "");
    const name = opened.filename;

    const listed = await (await fetch(api("/"))).json();
    check("opened scan appears in the list", listed.includes(name));

    // The whole point of in-place: nothing gets copied next to the user's file.
    const siblings = fs.readdirSync(path.dirname(fixture));
    check(
      "no files written beside the user's scan",
      siblings.length === 1 && siblings[0] === path.basename(fixture),
      siblings.join(", ")
    );

    const orient = await (await fetch(api(`/${name}/orientation`))).json();
    check("returns anatomical orientation", Array.isArray(orient.R) && orient.R.length === 3);

    // Threshold cloud: kick the build, then poll like the UI does.
    await fetch(api(`/${name}/warm_cloud`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threshold_pct: 99.5 }),
    });
    let ready = false;
    for (let i = 0; i < 60 && !ready; i++) {
      const r = await (await fetch(api(`/${name}/cloud_ready?threshold_pct=99.5`))).json();
      ready = !!r.ready;
      if (!ready) await new Promise((res) => setTimeout(res, 500));
    }
    check("threshold cloud cache builds in the background", ready);

    const cloud = await (
      await fetch(api(`/${name}/threshold_cloud`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold_pct: 99.5, max_points: 100 }),
      })
    ).json();
    check("threshold cloud returns points", (cloud.points || []).length > 0, `${cloud.total_voxels} voxels`);

    // Contacts sit at voxel x = 20 + 6i, y = 36, z = 24 with a 1mm identity-ish affine.
    const snap = await (
      await fetch(api(`/${name}/snap`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ point_mm: [-15.0, 0.4, 0.4], radius_mm: 4, threshold_pct: 99.5 }),
      })
    ).json();
    check("snaps a click onto a contact", snap.success === true && snap.voxel_count > 0,
      `${snap.voxel_count} voxels at ${JSON.stringify(snap.center_mm)}`);

    const interp = await (
      await fetch(api(`/${name}/interpolate`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          low_label: 1,
          high_label: 6,
          start_mm: [-16, 0, 0],
          end_mm: [14, 0, 0],
          threshold_pct: 99.5,
          lead_type: "D",
        }),
      })
    ).json();
    const interior = interp.interior || [];
    check(
      "interpolates the interior contacts",
      interp.success === true && interior.length === 4 && interior.every((c) => c.snapped),
      `${interior.length} found, ${(interp.skipped || []).length} skipped`
    );

    // Closing must not delete the user's data.
    await fetch(api(`/${name}`), { method: "DELETE" });
    check("closing a scan leaves the file on disk", fs.existsSync(fixture));

    // Implant documents: read an invented channel map, no model needed.
    const doc = makeDocument(python, path.dirname(fixture));
    const form = new FormData();
    form.append("path", doc);
    form.append("provider", "none");
    const extracted = await (
      await fetch(`${base}/api/extract/leads`, { method: "POST", body: form })
    ).json();
    const counts = Object.fromEntries(
      (extracted.leads || []).map((l) => [l.name, l.contacts])
    );
    check(
      "reads leads from an implant document",
      extracted.success === true && counts.LA === 8 && counts.RB === 6,
      extracted.error || JSON.stringify(counts)
    );

    // Pennsieve answers with or without the agent installed, never a crash.
    const ps = await fetch(`${base}/api/pennsieve/status`);
    check("Pennsieve status answers", ps.ok, `HTTP ${ps.status}`);

    fs.rmSync(path.dirname(fixture), { recursive: true, force: true });
  } catch (err) {
    check("launch sequence completed", false, String(err.message || err));
    if (log.length) console.log("\n--- backend output ---\n" + log.slice(-25).join(""));
  } finally {
    stopBackend(proc);
  }

  console.log(failures === 0 ? "\nAll checks passed." : `\n${failures} check(s) failed.`);
  process.exit(failures === 0 ? 0 : 1);
}

main();
