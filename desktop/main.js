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
  mainWindow.loadURL(`http://127.0.0.1:${port}/`);

  // Keep navigation inside the app; send anything external to the real browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(`http://127.0.0.1:${port}`)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/** Native "Load Scan" dialog, mirroring the legacy PyQt entry point. */
async function promptOpenScan() {
  const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
    title: "Select CT scan",
    properties: ["openFile"],
    filters: [
      { name: "NIfTI", extensions: ["nii", "nii.gz", "gz"] },
      { name: "All files", extensions: ["*"] },
    ],
  });
  if (canceled || !filePaths.length) return null;
  return filePaths[0];
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
