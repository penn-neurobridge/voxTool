#!/usr/bin/env node
"use strict";

/**
 * Repair the ad-hoc signature on the Electron binary npm downloads (macOS only).
 *
 * The published archive unpacks with a signature that no longer seals its
 * resources, and recent macOS SIGKILLs the process on launch rather than
 * reporting anything useful. Re-signing ad-hoc makes `npm start` work from
 * source. Packaged builds are signed by electron-builder and unaffected.
 */

const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

if (process.platform !== "darwin") process.exit(0);

const appPath = path.join(
  __dirname,
  "..",
  "node_modules",
  "electron",
  "dist",
  "Electron.app"
);

if (!fs.existsSync(appPath)) process.exit(0);

function signatureIsValid() {
  try {
    execFileSync("codesign", ["--verify", "--deep", appPath], { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

if (signatureIsValid()) process.exit(0);

try {
  console.log("Repairing Electron's code signature for local development…");
  execFileSync("xattr", ["-cr", appPath], { stdio: "pipe" });
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", appPath], {
    stdio: "pipe",
  });
  console.log(
    signatureIsValid()
      ? "Electron signature repaired."
      : "Electron signature still looks off; `npm start` may fail."
  );
} catch (err) {
  console.warn(
    `Could not re-sign Electron (${err.message}).\n` +
      "If `npm start` dies with SIGKILL, run:\n" +
      `  codesign --force --deep --sign - "${appPath}"`
  );
}
