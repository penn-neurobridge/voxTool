"use strict";

/**
 * Launching and supervising the Flask backend.
 *
 * Kept out of main.js so it can be exercised without booting Electron
 * (see scripts/test-backend-launch.js).
 */

const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");

/**
 * Find a Python that can actually import the backend's dependencies.
 *
 * Only relevant when running from source: a packaged build ships a frozen
 * backend. Launching from Finder gives a minimal PATH, so "python3" alone is
 * not enough — and the first python3 on PATH is often a bare system one.
 */
let cachedPython;
function resolvePython(projectRoot) {
  if (cachedPython) return cachedPython;

  const probe = "import flask, nibabel, numpy";
  const candidates = [
    process.env.VOXTOOL_PYTHON,
    path.join(projectRoot || "", "desktop", ".venv-build", "bin", "python"),
    "python3",
    "/opt/homebrew/bin/python3",
    "/opt/homebrew/Caskroom/miniconda/base/bin/python3",
    path.join(os.homedir(), "miniconda3", "bin", "python3"),
    path.join(os.homedir(), "anaconda3", "bin", "python3"),
    "/usr/local/bin/python3",
    "/usr/bin/python3",
  ].filter(Boolean);

  const tried = [];
  for (const candidate of candidates) {
    try {
      execFileSync(candidate, ["-c", probe], { stdio: "pipe" });
      cachedPython = candidate;
      return candidate;
    } catch (err) {
      tried.push(`${candidate}: ${(err.stderr || "").toString().trim().split("\n").pop() || err.message}`);
    }
  }
  throw new Error(
    "No Python with the backend dependencies was found.\n" +
      "Install them with:  pip install -r web/backend/requirements-desktop.txt\n" +
      "or set VOXTOOL_PYTHON to the interpreter to use.\n\nTried:\n  " +
      tried.join("\n  ")
  );
}

/** Ask the OS for an unused loopback port, then hand it to Flask. */
function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function backendEnv(port, extra = {}) {
  const env = {
    ...process.env,
    VOXTOOL_LOCAL: "1",
    PORT: String(port),
    FLASK_DEBUG: "0",
    PYTHONUNBUFFERED: "1",
    PYTHONDONTWRITEBYTECODE: "1",
    ...extra,
  };
  // Belt and braces: no stray cloud config may leak into the offline build.
  delete env.DATA_S3_BUCKET;
  delete env.AWS_ACCESS_KEY_ID;
  delete env.AWS_SECRET_ACCESS_KEY;
  delete env.AWS_SESSION_TOKEN;
  return env;
}

/**
 * @param {object} opts
 * @param {number} opts.port
 * @param {boolean} opts.isDev  run from source vs the frozen executable
 * @param {string} [opts.projectRoot]     repo root (dev)
 * @param {string} [opts.resourcesPath]   Electron resourcesPath (packaged)
 */
function startBackend({ port, isDev, projectRoot, resourcesPath }) {
  if (isDev) {
    const backendDir = path.join(projectRoot, "web", "backend");
    const py = resolvePython(projectRoot);
    const env = backendEnv(port, {
      VOXTOOL_STATIC_DIR:
        process.env.VOXTOOL_STATIC_DIR ||
        path.join(projectRoot, "web", "frontend", "build"),
    });
    return spawn(py, ["app.py"], { cwd: backendDir, env });
  }

  const exeName =
    process.platform === "win32" ? "voxtool-backend.exe" : "voxtool-backend";
  const exe = path.join(resourcesPath, "backend", exeName);
  if (!fs.existsSync(exe)) {
    throw new Error(`Backend executable missing at ${exe}`);
  }
  return spawn(exe, [], { cwd: path.dirname(exe), env: backendEnv(port) });
}

/** Poll /api/health until the backend answers, the process dies, or we time out. */
async function waitForHealth(port, { timeoutMs = 90_000, proc = null, tail = () => "" } = {}) {
  const deadline = Date.now() + timeoutMs;
  const url = `http://127.0.0.1:${port}/api/health`;

  while (Date.now() < deadline) {
    if (proc && proc.exitCode !== null) {
      throw new Error(`Backend exited with code ${proc.exitCode}.\n\n${tail()}`);
    }
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return await res.json().catch(() => ({}));
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(
    `Backend did not become ready within ${Math.round(timeoutMs / 1000)}s.\n\n${tail()}`
  );
}

function stopBackend(proc) {
  if (!proc || proc.exitCode !== null) return;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(proc.pid), "/f", "/t"]);
    } else {
      proc.kill("SIGTERM");
      setTimeout(() => {
        if (proc.exitCode === null) proc.kill("SIGKILL");
      }, 3000).unref?.();
    }
  } catch {
    /* shutting down anyway */
  }
}

module.exports = {
  findFreePort,
  startBackend,
  waitForHealth,
  stopBackend,
  backendEnv,
  resolvePython,
};
