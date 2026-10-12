"use strict";

/**
 * Bridge between the Electron shell and the React UI.
 *
 * The renderer stays sandboxed: it gets a native file picker and menu events,
 * not filesystem access. Presence of `window.voxtoolDesktop` is what the UI
 * uses to decide whether to offer "open in place" instead of "upload".
 */

const { contextBridge, ipcRenderer } = require("electron");

const on = (channel) => (handler) => {
  if (typeof handler !== "function") return () => {};
  const wrapped = (_event, ...args) => handler(...args);
  ipcRenderer.on(channel, wrapped);
  return () => ipcRenderer.removeListener(channel, wrapped);
};

contextBridge.exposeInMainWorld("voxtoolDesktop", {
  isDesktop: true,
  platform: process.platform,

  /** Native open dialog. Resolves to an absolute path, or null if cancelled. */
  pickScan: () => ipcRenderer.invoke("voxtool:pick-scan"),
  getPort: () => ipcRenderer.invoke("voxtool:get-port"),
  showItemInFolder: (p) => ipcRenderer.invoke("voxtool:show-item", p),

  onOpenScan: on("voxtool:open-scan"),
  onSaveCoordinates: on("voxtool:save-coordinates"),
  onLoadCoordinates: on("voxtool:load-coordinates"),
});
