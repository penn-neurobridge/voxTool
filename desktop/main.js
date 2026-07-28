"use strict";

/**
 * VoxTool desktop shell.
 *
 * Starts the same Flask backend the cloud build uses, bound to loopback on an
 * ephemeral port, and points a browser window at it. Everything stays on the
 * machine: no S3, no CloudFront, no outbound requests.
 */

const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const {
  findFreePort,
  startBackend,
  waitForHealth,
  stopBackend,
} = require("./backend-process");

const isDev = !app.isPackaged;
const PROJECT_ROOT = path.resolve(__dirname, "..");

let backend = null;
let mainWindow = null;
let backendPort = 0;
let backendLog = [];
let logStream = null;

/** Persist startup output so a failure is diagnosable after the fact. */
function logFilePath() {
  return path.join(app.getPath("userData"), "voxtool.log");
}

function openLogFile() {
  try {
    const dir = app.getPath("userData");
    fs.mkdirSync(dir, { recursive: true });
    logStream = fs.createWriteStream(logFilePath(), { flags: "w" });
    logStream.write(
      `VoxTool ${app.getVersion()} — ${new Date().toISOString()}\n` +
        `packaged=${!isDev} platform=${process.platform} ${process.arch}\n\n`
    );
  } catch {
    logStream = null;
  }
}

function logLine(line) {
  backendLog.push(line);
  if (backendLog.length > 400) backendLog = backendLog.slice(-200);
  if (isDev) process.stdout.write(`[backend] ${line}`);
  try {
    logStream?.write(line.endsWith("\n") ? line : `${line}\n`);
  } catch {
    /* logging must never break startup */
  }
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 950,
    minWidth: 1024,
    minHeight: 700,
    backgroundColor: "#0a0a10",
    title: "VoxTool",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());

  const url = `http://127.0.0.1:${port}/`;
  mainWindow.loadURL(url);

  mainWindow.webContents.on(
    "did-fail-load",
    (_e, errorCode, errorDescription, validatedURL) => {
      logLine(`did-fail-load ${errorCode} ${errorDescription} ${validatedURL}\n`);
      dialog.showErrorBox(
        "VoxTool could not load the interface",
        `${errorDescription} (${errorCode})\n\nURL: ${validatedURL}\n\n` +
          `Log: ${logFilePath()}`
      );
    }
  );

  // Blank window with only the Electron background usually means index.html
  // loaded but the JS bundle 404'd. Surface that instead of a silent black screen.
  mainWindow.webContents.on("did-finish-load", async () => {
    try {
      const info = await mainWindow.webContents.executeJavaScript(`({
        title: document.title,
        hasRoot: !!document.getElementById("root"),
        rootKids: document.getElementById("root")?.childElementCount || 0,
        scripts: [...document.scripts].map(s => s.src),
        bodyText: (document.body?.innerText || "").slice(0, 200)
      })`);
      logLine(`ui-check ${JSON.stringify(info)}\n`);
      if (info.hasRoot && info.rootKids === 0) {
        setTimeout(async () => {
          if (!mainWindow) return;
          const again = await mainWindow.webContents.executeJavaScript(
            `document.getElementById("root")?.childElementCount || 0`
          );
          if (again === 0) {
            dialog.showErrorBox(
              "VoxTool interface did not start",
              "The window opened but the UI never rendered. This usually means " +
                "the bundled frontend files are missing from the backend.\n\n" +
                `Details are in:\n${logFilePath()}\n\n` +
                "Also try Help → Backend Log."
            );
          }
        }, 2500);
      }
    } catch (err) {
      logLine(`ui-check failed: ${err.message}\n`);
    }
  });

  // Keep navigation inside the app; send anything external to the real browser.
  mainWindow.webContents.setWindowOpenHandler(({ url: openUrl }) => {
    shell.openExternal(openUrl);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, navUrl) => {
    if (!navUrl.startsWith(`http://127.0.0.1:${port}`)) {
      event.preventDefault();
      shell.openExternal(navUrl);
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/** Native "Load Scan" dialog, mirroring the legacy PyQt entry point. */
async function promptOpenScan() {
  // Windows rejects extension strings that contain a dot (e.g. "nii.gz"), and
  // can fail the dialog with no visible error. List each suffix separately.
  try {
    const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
      title: "Select CT scan",
      properties: ["openFile"],
      filters: [
        { name: "NIfTI", extensions: ["nii", "gz"] },
        { name: "All files", extensions: ["*"] },
      ],
    });
    if (canceled || !filePaths.length) return null;
    return filePaths[0];
  } catch (err) {
    dialog.showErrorBox(
      "Could not open file dialog",
      String(err.message || err)
    );
    return null;
  }
}

function buildMenu() {
  const isMac = process.platform === "darwin";
  const send = (channel) => () => mainWindow?.webContents.send(channel);

  const template = [
    ...(isMac ? [{ role: "appMenu" }] : []),
    {
      label: "File",
      submenu: [
        {
          label: "Open Scan…",
          accelerator: "CmdOrCtrl+O",
          click: async () => {
            const p = await promptOpenScan();
            if (p) mainWindow?.webContents.send("voxtool:open-scan", p);
          },
        },
        { type: "separator" },
        {
          label: "Load Coordinates…",
          accelerator: "CmdOrCtrl+Shift+O",
          click: send("voxtool:load-coordinates"),
        },
        {
          label: "Save Coordinates…",
          accelerator: "CmdOrCtrl+S",
          click: send("voxtool:save-coordinates"),
        },
        { type: "separator" },
        {
          label: "Open App Data Folder",
          click: async () => {
            try {
              const res = await fetch(
                `http://127.0.0.1:${backendPort}/api/health`
              );
              const info = await res.json();
              if (info.data_dir) shell.openPath(path.dirname(info.data_dir));
            } catch {
              /* backend not reachable; nothing useful to open */
            }
          },
        },
        { type: "separator" },
        isMac ? { role: "close" } : { role: "quit" },
      ],
    },
    { role: "editMenu" },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    { role: "windowMenu" },
    {
      role: "help",
      submenu: [
        {
          label: "Backend Log",
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: "info",
              title: "Backend log",
              message: `VoxTool backend (port ${backendPort})`,
              detail: backendLog.slice(-40).join("") || "No output yet.",
            });
          },
        },
        {
          label: "About VoxTool",
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: "info",
              title: "About VoxTool",
              message: `VoxTool ${app.getVersion()}`,
              detail:
                "Local desktop build. Scans are read in place from your disk and " +
                "nothing is uploaded — this app makes no network requests.",
            });
          },
        },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function registerIpc() {
  ipcMain.handle("voxtool:pick-scan", async () => promptOpenScan());
  ipcMain.handle("voxtool:get-port", () => backendPort);
  ipcMain.handle("voxtool:show-item", (_e, p) => {
    if (p && fs.existsSync(p)) shell.showItemInFolder(p);
  });
}

const shutdownBackend = () => stopBackend(backend);

async function bootstrap() {
  openLogFile();
  try {
    backendPort = await findFreePort();
    logLine(`starting backend on 127.0.0.1:${backendPort}\n`);
    backend = startBackend({
      port: backendPort,
      isDev,
      projectRoot: PROJECT_ROOT,
      resourcesPath: process.resourcesPath,
    });

    backend.stdout?.on("data", (d) => logLine(d.toString()));
    backend.stderr?.on("data", (d) => logLine(d.toString()));
    backend.on("error", (err) => logLine(`spawn error: ${err.message}\n`));
    backend.on("exit", (code) => {
      logLine(`backend exited (${code})\n`);
      if (code !== 0 && code !== null && mainWindow) {
        dialog.showErrorBox(
          "VoxTool backend stopped",
          `The processing backend exited unexpectedly (code ${code}).\n\n` +
            backendLog.slice(-15).join("")
        );
      }
    });

    await waitForHealth(backendPort, {
      proc: backend,
      tail: () => backendLog.slice(-15).join(""),
    });
    // Confirm the frozen backend actually has the React bundle. Without it the
    // window is just the Electron background color (looks like a black screen).
    try {
      const res = await fetch(`http://127.0.0.1:${backendPort}/api/health`);
      const health = await res.json();
      logLine(`health ${JSON.stringify(health)}\n`);
      if (health.ui === false) {
        throw new Error(
          "Backend started but the UI bundle is missing (health.ui=false). " +
            "Rebuild the desktop app so the frontend is packaged into the backend."
        );
      }
    } catch (err) {
      if (String(err.message || err).includes("UI bundle")) throw err;
      logLine(`post-health check: ${err.message}\n`);
    }
    logLine("backend healthy; opening window\n");
    registerIpc();
    buildMenu();
    createWindow(backendPort);
  } catch (err) {
    const message = String(err.message || err);
    logLine(`STARTUP FAILED: ${message}\n`);
    dialog.showErrorBox(
      "VoxTool failed to start",
      `${message}\n\nDetails were written to:\n${logFilePath()}`
    );
    app.quit();
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(bootstrap);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0 && backendPort) {
      createWindow(backendPort);
    }
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("before-quit", shutdownBackend);
  app.on("will-quit", shutdownBackend);
  process.on("exit", shutdownBackend);
}
