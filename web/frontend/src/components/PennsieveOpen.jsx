import { useCallback, useEffect, useState } from "react";
import PennsieveBrowser from "./PennsieveBrowser";
import PennsieveConnect from "./PennsieveConnect";

const API = process.env.REACT_APP_API_URL || "";

/**
 * Open a CT straight from Pennsieve: browse a dataset's folders, or paste a
 * file's Pennsieve ID. The scan is downloaded into the app data folder and then
 * opened exactly like one picked from disk (onOpened gets its local path).
 */
export default function PennsieveOpen({ open, onClose, onOpened }) {
  const [status, setStatus] = useState(null);
  const [dataset, setDataset] = useState("");
  const [packageId, setPackageId] = useState("");
  const [downloading, setDownloading] = useState(null);
  const [error, setError] = useState("");
  const [managing, setManaging] = useState(false);

  const loadStatus = useCallback(() => {
    setStatus(null);
    fetch(`${API}/api/pennsieve/status?auto_start=1`)
      .then((r) => r.json())
      .then((d) => {
        setStatus(d);
        // Reading cannot put anything in the wrong place, so a lone dataset
        // is picked for you; uploads never do this.
        setDataset(d.datasets?.length === 1 ? d.datasets[0].id : "");
      })
      .catch((e) => setError(`Could not reach Pennsieve: ${e.message || e}`));
  }, []);

  useEffect(() => {
    if (!open) return;
    setError("");
    setDownloading(null);
    loadStatus();
  }, [open, loadStatus]);

  const openPackage = useCallback(
    async (id, label) => {
      setError("");
      setDownloading(label || id);
      try {
        const res = await fetch(`${API}/api/pennsieve/open`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ package_id: id }),
          signal: AbortSignal.timeout(900_000),
        });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
        onOpened(data.path);
      } catch (e) {
        setError(e.message || String(e));
      } finally {
        setDownloading(null);
      }
    },
    [onOpened]
  );

  if (!open) return null;

  const blocked = status && (!status.installed || !status.agent_running);
  const busy = !!downloading;

  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Open a scan from Pennsieve</h2>

        {error && <p className="import-error">{error}</p>}
        {!status && !error && <p className="muted">Checking your Pennsieve account…</p>}

        {blocked && (
          <>
            <p className="import-warning">
              {status.error || "Pennsieve is not ready on this computer."}
            </p>
            <div className="modal-actions">
              <button type="button" className="btn btn-primary" onClick={() => setManaging(true)}>
                Connect to Pennsieve…
              </button>
            </div>
          </>
        )}

        {status && !blocked && (
          <>
            <div className="pennsieve-dest">
              <div>
                <span className="muted">Signed in as</span> <strong>{status.user}</strong>
              </div>
              <div>
                <span className="muted">Workspace</span> <strong>{status.workspace}</strong>{" "}
                <button
                  type="button"
                  className="link-button"
                  disabled={busy}
                  onClick={() => setManaging(true)}
                >
                  Change…
                </button>
              </div>
            </div>

            <div className="field">
              <label>Dataset</label>
              <select value={dataset} onChange={(e) => setDataset(e.target.value)} disabled={busy}>
                <option value="">— choose a dataset —</option>
                {(status.datasets || []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>

            <PennsieveBrowser
              dataset={dataset}
              datasetName={status.datasets?.find((d) => d.id === dataset)?.name}
              busy={busy}
              onOpenFile={(item) => openPackage(item.id, item.name)}
            />

            <form
              className="field"
              onSubmit={(e) => {
                e.preventDefault();
                if (packageId.trim()) openPackage(packageId.trim());
              }}
            >
              <label>Or paste a file's Pennsieve ID</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  type="text"
                  style={{ flex: 1 }}
                  placeholder="N:package:…"
                  value={packageId}
                  onChange={(e) => setPackageId(e.target.value)}
                  disabled={busy}
                />
                <button type="submit" className="btn" disabled={busy || !packageId.trim()}>
                  Open
                </button>
              </div>
            </form>

            {downloading && (
              <p className="import-progress">
                Downloading {downloading} from Pennsieve… A CT is usually 50–300 MB, so
                this can take a minute. It is kept in VoxTool's app data folder, so
                opening it again is instant.
              </p>
            )}
          </>
        )}

        <div className="modal-actions modal-actions-scan">
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>

      <PennsieveConnect
        open={managing}
        onClose={(changed) => {
          setManaging(false);
          if (changed) loadStatus();
        }}
      />
    </div>
  );
}
