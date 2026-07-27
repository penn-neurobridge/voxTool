# VoxTool desktop build

Packages the existing VoxTool web app as an offline desktop application. It is
the *same* code as the cloud version, not a fork: the React UI and the Flask API
are unchanged, just wired together locally.

```
Electron window  →  http://127.0.0.1:<random port>  →  Flask (frozen)  →  your disk
```

## How it differs from the cloud build

Both builds run from the same source. The desktop build sets `VOXTOOL_LOCAL=1`,
which changes five things:

| | Cloud | Desktop |
| --- | --- | --- |
| Scan storage | uploaded into `backend/data`, mirrored to S3 | **opened in place**, never copied |
| Upload limit | 150 MB | none |
| Derived caches | written beside the scan / to S3 | per-user app data folder |
| Cloud cache build | detached subprocess | background thread |
| Network binding | `0.0.0.0`, public via CloudFront | `127.0.0.1` only |

`boto3` is excluded from the frozen bundle, so the desktop app has no code path
that can reach AWS at all.

## Layout

| Path | Purpose |
| --- | --- |
| `main.js` | Electron entry: starts the backend, opens the window, native menus |
| `backend-process.js` | Port selection, backend spawn, health polling (no Electron dependency, so it is testable) |
| `preload.js` | Exposes `window.voxtoolDesktop` to the UI — native file dialog + menu events |
| `scripts/build-backend.js` | Freezes the Flask app with PyInstaller into `resources/backend` |
| `scripts/test-backend-launch.js` | Headless end-to-end check of the startup path |
| `scripts/fix-electron-signature.js` | Repairs Electron's ad-hoc signature on macOS (postinstall) |
| `scripts/make-icon.py` | Regenerates `build/icon.png` |

## Running from source

Requires Node 20+ and a Python 3.11+ with the backend dependencies:

```bash
pip install -r ../web/backend/requirements-desktop.txt

cd desktop
npm install
npm run build:frontend   # compiles the React UI into web/frontend/build
npm start
```

`backend-process.js` searches for a Python that can import flask, nibabel and
numpy (checking common Homebrew/conda locations, not just `PATH`). Override it
with `VOXTOOL_PYTHON=/path/to/python`.

### Checking things work without opening a window

```bash
npm test
```

This runs the real startup sequence — free port, spawn backend, poll health —
then drives a synthetic CT through open-in-place, threshold cloud, snap and
interpolate, and asserts that nothing was written next to the scan file.

## Building installers

```bash
npm run dist:mac     # .dmg + .zip
npm run dist:win     # NSIS .exe   (must run on Windows)
```

`npm run dist` does the whole chain: build the frontend, freeze the backend with
PyInstaller, then package with electron-builder.

**You cannot build a Windows installer on a Mac.** Use the
**Build desktop app** GitHub Actions workflow, which builds macOS arm64, macOS
x64 and Windows x64 on their own runners and uploads all three as artifacts.
Trigger it from the Actions tab, or push a `v*` tag.

## Code signing

Builds are currently unsigned, so users see a Gatekeeper / SmartScreen warning
once (the main `README.md` documents the click-through). To sign properly:

- **macOS** — an Apple Developer ID Application certificate. Set `CSC_LINK` and
  `CSC_KEY_PASSWORD` in the workflow, remove `"identity": null` from
  `package.json`, set `hardenedRuntime: true`, and add notarization credentials
  (`APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`).
- **Windows** — an OV/EV code-signing certificate via `CSC_LINK` /
  `CSC_KEY_PASSWORD`, and drop `signAndEditExecutable: false`.

## Troubleshooting

**The app window never appears.** `main.js` writes a startup log to the app data
folder — `~/Library/Application Support/VoxTool/voxtool.log` on macOS,
`%APPDATA%\VoxTool\voxtool.log` on Windows. **Help → Backend Log** shows the
same output in-app.

**`npm start` dies immediately with SIGKILL (macOS).** Recent macOS kills the
Electron binary npm downloads because its signature no longer seals its
resources. The `postinstall` hook re-signs it automatically; if it did not run:

```bash
codesign --force --deep --sign - node_modules/electron/dist/Electron.app
```

**The packaged macOS app starts but no window appears, and no log is written.**
Seen on at least one macOS 26 machine where Gatekeeper's assessment of ad-hoc
signatures is unreliable — `spctl -a -vvv VoxTool.app` reported
`notarization indicates this code has been revoked` for a locally built,
never-downloaded bundle, and the stock Electron binary was SIGKILLed even for
`electron --version`. The bundled backend is byte-identical to the staged copy
that runs fine, so this is signature assessment rather than a broken build.

If you hit this, the reliable fix is a **properly signed and notarized build**
(see above). To confirm it is machine-specific rather than a packaging problem,
test the same artifact on a different Mac. Windows builds are unaffected.

**"No Python with the backend dependencies was found."** Install them, or point
`VOXTOOL_PYTHON` at the right interpreter. Only affects running from source.

**Data folder is not writable.** The backend falls back to `~/.voxtool` and then
to a temp directory, logging which one it used. Force a location with
`VOXTOOL_DATA_DIR`.
