import { useCallback, useEffect, useState } from "react";

const API = process.env.REACT_APP_API_URL || "";

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

/**
 * Open a CT straight from Pennsieve: browse a dataset's folders, or paste a
 * file's Pennsieve ID. The scan is downloaded into the app data folder and then
 * opened exactly like one picked from disk (onOpened gets its local path).
 */
export default function PennsieveOpen({ open, onClose, onOpened }) {
  const [status, setStatus] = useState(null);
  const [dataset, setDataset] = useState("");
  const [folder, setFolder] = useState("");
  const [listing, setListing] = useState(null);
  const [packageId, setPackageId] = useState("");
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    setListing(null);
    setFolder("");
    setDownloading(null);
    fetch(`${API}/api/pennsieve/status?auto_start=1`)
      .then((r) => r.json())
      .then((d) => {
        setStatus(d);
        // Reading cannot put anything in the wrong place, so a lone dataset
        // is picked for you; uploads never do this.
        setDataset(d.datasets?.length === 1 ? d.datasets[0].id : "");
      })
      .catch((e) => setError(`Could not reach Pennsieve: ${e.message || e}`));
  }, [open]);

  useEffect(() => {
    if (!open || !dataset) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ dataset });
    if (folder) params.set("folder", folder);
    fetch(`${API}/api/pennsieve/browse?${params}`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        if (!d.success) throw new Error(d.error);
        setListing(d);
      })
      .catch((e) => !cancelled && setError(e.message || String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open, dataset, folder]);

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
  const busy = loading || !!downloading;

  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Open a scan from Pennsieve</h2>

        {error && <p className="import-error">{error}</p>}
        {!status && !error && <p className="muted">Checking your Pennsieve account…</p>}

        {blocked && (
          <p className="import-warning">
            {status.error || "Pennsieve is not ready on this machine."}
          </p>
        )}

        {status && !blocked && (
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
                onChange={(e) => {
                  setDataset(e.target.value);
                  setFolder("");
                  setListing(null);
                }}
                disabled={busy}
              >
                <option value="">— choose a dataset —</option>
                {(status.datasets || []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>

            {dataset && (
              <>
                <div className="pennsieve-crumbs">
                  <button type="button" disabled={busy || !folder} onClick={() => setFolder("")}>
                    {status.datasets?.find((d) => d.id === dataset)?.name || "Dataset"}
                  </button>
                  {(listing?.path || []).map((p, i, all) => (
                    <span key={p.id}>
                      /{" "}
                      <button
                        type="button"
                        disabled={busy || i === all.length - 1}
                        onClick={() => setFolder(p.id)}
                      >
                        {p.name}
                      </button>
                    </span>
                  ))}
                </div>

                <div className="pennsieve-list">
                  {loading && <div className="pennsieve-row muted">Loading…</div>}
                  {!loading && listing?.items?.length === 0 && (
                    <div className="pennsieve-row muted">This folder is empty.</div>
                  )}
                  {!loading &&
                    (listing?.items || []).map((item) =>
                      item.folder ? (
                        <div
                          key={item.id}
                          className="pennsieve-row pennsieve-row-folder"
                          onClick={() => !busy && setFolder(item.id)}
                        >
                          <span className="pennsieve-row-name">{item.name}/</span>
                        </div>
                      ) : (
                        <div
                          key={item.id}
                          className={`pennsieve-row ${item.scan ? "" : "pennsieve-row-other"}`}
                        >
                          <span className="pennsieve-row-name" title={item.id}>
                            {item.name}
                          </span>
                          <span className="pennsieve-row-size">{formatSize(item.bytes)}</span>
                          {item.scan && (
                            <button
                              type="button"
                              className="btn btn-compact btn-primary"
                              disabled={busy}
                              onClick={() => openPackage(item.id, item.name)}
                            >
                              Open
                            </button>
                          )}
                        </div>
                      )
                    )}
                </div>
              </>
            )}

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
    </div>
  );
}
