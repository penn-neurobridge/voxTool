import { useCallback, useEffect, useState } from "react";

const API = process.env.REACT_APP_API_URL || "";

/**
 * Send the finished annotations to Pennsieve.
 *
 * The destination is always spelled out before anything moves: workspace,
 * dataset, folder, filename. Whatever lands in a dataset inherits that
 * dataset's permissions, so choosing the dataset *is* the access decision and
 * it should never be implicit.
 *
 * "Send for real" is off by default. Leaving it off reports exactly what would
 * happen and sends nothing. Nor is a dataset ever pre-selected, not even the
 * agent's active one, which may be a real dataset left over from last time.
 */
export default function PennsieveUpload({ open, onClose, document, scanFilename, counts }) {
  const [status, setStatus] = useState(null);
  const [dataset, setDataset] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [reallySend, setReallySend] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (!open) return;
    setError("");
    setResult(null);
    setReallySend(false);
    setDataset("");
    // The lab keeps VoxTool output here, beside the other derivatives.
    setTargetPath("derivatives/voxtool_ct");
    fetch(`${API}/api/pennsieve/status?auto_start=1`)
      .then((r) => r.json())
      .then(setStatus)
      .catch((e) => setError(`Could not reach Pennsieve: ${e.message || e}`));
  }, [open]);

  const send = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/pennsieve/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document,
          scan_filename: scanFilename,
          dataset_id: dataset,
          target_path: targetPath,
          dry_run: !reallySend,
        }),
        signal: AbortSignal.timeout(600_000),
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
      setResult(data);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }, [document, scanFilename, dataset, targetPath, reallySend]);

  if (!open) return null;

  const blocked = status && (!status.installed || !status.agent_running);
  const chosen = status?.datasets?.find((d) => d.id === dataset);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Upload to Pennsieve</h2>

        {error && <p className="import-error">{error}</p>}

        {!status && !error && <p className="muted">Checking your Pennsieve account…</p>}

        {blocked && (
          <p className="import-warning">
            {status.error ||
              "Pennsieve is not ready on this machine."}{" "}
            {status.installed
              ? "Start it with `pennsieve agent` in a terminal, then reopen this window."
              : "Install the Pennsieve agent and sign in, then reopen this window."}
          </p>
        )}

        {status && !blocked && !result && (
          <>
            <div className="pennsieve-dest">
              <div>
                <span className="muted">Signed in as</span> <strong>{status.user}</strong>
              </div>
              <div>
                <span className="muted">Workspace</span> <strong>{status.workspace}</strong>
              </div>
            </div>

            <div className="field">
              <label>Dataset</label>
              <select
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
                disabled={busy}
              >
                <option value="">— choose a dataset —</option>
                {(status.datasets || []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              {status.restricted && (
                <p className="muted">
                  This machine only uploads to the datasets listed here.
                </p>
              )}
            </div>

            <div className="field">
              <label>Folder in the dataset</label>
              <input
                type="text"
                value={targetPath}
                placeholder="derivatives/voxtool_ct"
                onChange={(e) => setTargetPath(e.target.value)}
                disabled={busy}
              />
            </div>

            <p className="pennsieve-summary">
              Sending <strong>{counts?.leads ?? 0}</strong> lead
              {counts?.leads === 1 ? "" : "s"} and{" "}
              <strong>{counts?.contacts ?? 0}</strong> contact
              {counts?.contacts === 1 ? "" : "s"}. The filename is stamped with the
              date and time, so an earlier upload is never overwritten.
            </p>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={reallySend}
                onChange={(e) => setReallySend(e.target.checked)}
                disabled={busy}
              />
              Actually send it (leave unticked to preview only)
            </label>

            {busy && reallySend && (
              <p className="import-progress">
                Uploading, then waiting for Pennsieve to confirm the file
                arrived. This can take a minute or two.
              </p>
            )}

            <div className="modal-actions modal-actions-scan">
              <button className="btn" onClick={onClose} disabled={busy}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={send}
                disabled={busy || !dataset}
              >
                {busy
                  ? reallySend
                    ? "Uploading…"
                    : "Checking…"
                  : reallySend
                  ? "Upload"
                  : "Preview"}
              </button>
            </div>
          </>
        )}

        {result && (
          <>
            <p className={result.uploaded ? "pennsieve-ok" : "import-warning"}>
              {result.dry_run ? "Preview only — nothing was sent." : result.message}
            </p>
            <table className="pennsieve-result">
              <tbody>
                <tr>
                  <th>File</th>
                  <td>{result.filename}</td>
                </tr>
                <tr>
                  <th>Dataset</th>
                  <td>{chosen?.name || result.dataset}</td>
                </tr>
                <tr>
                  <th>Folder</th>
                  <td>{result.target_path || "(dataset root)"}</td>
                </tr>
                <tr>
                  <th>Size</th>
                  <td>{(result.bytes / 1024).toFixed(1)} KB</td>
                </tr>
              </tbody>
            </table>
            <div className="modal-actions modal-actions-scan">
              {result.dry_run && (
                <button className="btn" onClick={() => setResult(null)}>
                  Back
                </button>
              )}
              <button className="btn btn-primary" onClick={onClose}>
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
