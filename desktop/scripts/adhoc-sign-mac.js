#!/usr/bin/env node
"use strict";

/**
 * Ad-hoc sign the packaged macOS app (electron-builder afterPack hook).
 *
 * We ship without a certificate, and `identity: null` makes electron-builder
 * skip signing altogether. On Intel that just means an unidentified-developer
 * prompt, but on Apple Silicon a bundle carrying no signature of its own is
 * treated as revoked code: macOS reports "VoxTool contains malware" and gives
 * the user no way through — neither right-click Open nor clearing the
 * quarantine attribute helps, because neither creates the missing signature.
 *
 * An ad-hoc signature costs nothing, needs no certificate, and reduces that to
 * the ordinary prompt the release notes describe. It has to happen here rather
 * than after the fact: afterPack runs before the DMG and ZIP are assembled, so
 * the artifacts we upload contain the signed bundle.
 */

const { execFileSync } = require("child_process");
const path = require("path");

/**
 * Extended attributes copied in from the working tree make codesign bail with
 * "resource fork, Finder information, or similar detritus not allowed".
 * Stripping them is advisory cleanup, so its own exit status is not useful.
 */
function stripExtendedAttributes(appPath) {
  try {
    execFileSync("xattr", ["-cr", appPath], { stdio: "pipe" });
  } catch {
    /* codesign is the real check */
  }
}

function hasFinderInfo(appPath) {
  try {
    const attrs = execFileSync("xattr", [appPath], { encoding: "utf8" });
    return attrs.includes("com.apple.FinderInfo");
  } catch {
    return false;
  }
}

module.exports = async function adhocSignMac(context) {
  if (context.electronPlatformName !== "darwin") return;

  const appPath = path.join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`
  );

  console.log(`Ad-hoc signing ${appPath}`);
  stripExtendedAttributes(appPath);

  try {
    execFileSync("codesign", ["--force", "--deep", "--sign", "-", appPath], {
      stdio: "inherit",
    });
    // Catches a bundle whose seal cannot be satisfied — a dangling symlink
    // among the resources, say — while it is still cheap to fix.
    execFileSync("codesign", ["--verify", "--strict", appPath], {
      stdio: "inherit",
    });
  } catch (err) {
    if (hasFinderInfo(appPath)) {
      throw new Error(
        "codesign rejected the bundle because com.apple.FinderInfo came back " +
          "after being stripped. A file provider is rewriting it — iCloud " +
          "Drive's Desktop & Documents sync does this within a second or two, " +
          "which no amount of retrying can outrun. Build to a location it does " +
          "not manage:\n\n" +
          "  npx electron-builder --mac -c.directories.output=/tmp/voxtool-dist"
      );
    }
    throw err;
  }
};
