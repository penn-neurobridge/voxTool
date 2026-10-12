#!/usr/bin/env node
"use strict";

/**
 * Freeze the Flask backend into a standalone executable and stage it where
 * electron-builder expects it (desktop/resources/backend).
 *
 * Creates a throwaway virtualenv so the bundle contains only what the desktop
 * build needs — notably not boto3, so the offline app has no way to reach S3.
 */

const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_DIR = path.join(ROOT, "web", "backend");
const FRONTEND_BUILD = path.join(ROOT, "web", "frontend", "build");
const VENV_DIR = path.join(ROOT, "desktop", ".venv-build");
const STAGE_DIR = path.join(ROOT, "desktop", "resources", "backend");

const isWin = process.platform === "win32";
const venvBin = path.join(VENV_DIR, isWin ? "Scripts" : "bin");
const venvPython = path.join(venvBin, isWin ? "python.exe" : "python");

function run(cmd, args, opts = {}) {
  console.log(`\n$ ${cmd} ${args.join(" ")}`);
  execFileSync(cmd, args, { stdio: "inherit", ...opts });
}

function basePython() {
  if (process.env.VOXTOOL_PYTHON) return process.env.VOXTOOL_PYTHON;
  return isWin ? "python" : "python3";
}

/**
 * Refuse to stage a tree whose symlinks lead outside it.
 *
 * A link that escapes the bundle still resolves on the machine that built it,
 * so nothing downstream notices — not electron-builder, not the packaged
 * launch test. The failure surfaces only once a user runs the installer, as
 * "Failed to load Python shared library".
 */
function assertSelfContained(dir) {
  const offenders = [];

  const walk = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isSymbolicLink()) {
        const target = fs.readlinkSync(full);
        const resolved = path.resolve(path.dirname(full), target);
        const escapes = path.relative(dir, resolved).startsWith("..");
        if (path.isAbsolute(target) || escapes) {
          offenders.push(`${path.relative(dir, full)} -> ${target}`);
        } else if (!fs.existsSync(resolved)) {
          offenders.push(`${path.relative(dir, full)} -> ${target} (dangling)`);
        }
      } else if (entry.isDirectory()) {
        walk(full);
      }
    }
  };

  walk(dir);

  if (offenders.length) {
    console.error(
      `\n${offenders.length} symlink(s) in the staged backend point outside it, ` +
        "so the build would only run on this machine:\n  " +
        offenders.join("\n  ")
    );
    process.exit(1);
  }
}

function main() {
  if (!fs.existsSync(path.join(FRONTEND_BUILD, "index.html"))) {
    console.error(
      `\nFrontend build missing at ${FRONTEND_BUILD}\n` +
        "Run `npm run build:frontend` (or npm run dist) first.\n"
    );
    process.exit(1);
  }

  if (!fs.existsSync(venvPython)) {
    console.log("Creating build virtualenv…");
    run(basePython(), ["-m", "venv", VENV_DIR]);
  }

  run(venvPython, ["-m", "pip", "install", "--upgrade", "pip", "wheel"]);
  run(venvPython, [
    "-m",
    "pip",
    "install",
    "-r",
    path.join(BACKEND_DIR, "requirements-desktop.txt"),
  ]);
  run(venvPython, ["-m", "pip", "install", "pyinstaller>=6.6"]);

  const workDir = path.join(os.tmpdir(), "voxtool-pyinstaller");
  const distDir = path.join(ROOT, "desktop", ".dist-backend");
  fs.rmSync(distDir, { recursive: true, force: true });

  run(
    venvPython,
    [
      "-m",
      "PyInstaller",
      "--noconfirm",
      "--clean",
      "--distpath",
      distDir,
      "--workpath",
      workDir,
      "voxtool-backend.spec",
    ],
    {
      cwd: BACKEND_DIR,
      env: { ...process.env, VOXTOOL_FRONTEND_BUILD: FRONTEND_BUILD },
    }
  );

  const built = path.join(distDir, "voxtool-backend");
  if (!fs.existsSync(built)) {
    console.error(`PyInstaller produced nothing at ${built}`);
    process.exit(1);
  }

  fs.rmSync(STAGE_DIR, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(STAGE_DIR), { recursive: true });
  // verbatimSymlinks is load-bearing: without it cpSync resolves every relative
  // symlink against the source tree and writes it back as an absolute path, so
  // the Python.framework links inside PyInstaller's output end up pointing at
  // .dist-backend on the build machine. They resolve fine there — including on
  // CI, which is why this shipped — and dangle on every user's disk.
  fs.cpSync(built, STAGE_DIR, { recursive: true, verbatimSymlinks: true });
  assertSelfContained(STAGE_DIR);

  const exeName = isWin ? "voxtool-backend.exe" : "voxtool-backend";
  const exePath = path.join(STAGE_DIR, exeName);
  if (!fs.existsSync(exePath)) {
    console.error(`Expected executable missing: ${exePath}`);
    process.exit(1);
  }
  if (!isWin) fs.chmodSync(exePath, 0o755);

  // PyInstaller 6 onedir puts datas under _internal/; older layouts keep them
  // next to the exe. Either way the UI must be findable or Electron opens black.
  const uiCandidates = [
    path.join(STAGE_DIR, "frontend", "index.html"),
    path.join(STAGE_DIR, "_internal", "frontend", "index.html"),
  ];
  const uiIndex = uiCandidates.find((p) => fs.existsSync(p));
  if (!uiIndex) {
    console.error(
      "Frontend was not bundled into the frozen backend.\n" +
        `Looked for:\n  ${uiCandidates.join("\n  ")}\n` +
        `Contents of ${STAGE_DIR}:\n  ${fs.readdirSync(STAGE_DIR).join("\n  ")}`
    );
    process.exit(1);
  }
  console.log(`\nBackend staged at ${STAGE_DIR}`);
  console.log(`UI bundle at ${uiIndex}`);
}

if (require.main === module) main();

module.exports = { assertSelfContained };
