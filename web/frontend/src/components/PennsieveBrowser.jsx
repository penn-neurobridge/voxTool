import { useEffect, useState } from "react";

const API = process.env.REACT_APP_API_URL || "";

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

/**
 * One folder of a Pennsieve dataset at a time, with a breadcrumb back up.
 *
 * Opening a scan passes onOpenFile, and NIfTI files get an Open button.
 * Choosing an upload folder passes onChooseFolder instead, and the folder
 * being shown can be picked with "Use this folder".
 */
export default function PennsieveBrowser({
  dataset,
  datasetName,
  busy,
  onOpenFile,
  onChooseFolder,
}) {
  const [folder, setFolder] = useState("");
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setFolder("");
  }, [dataset]);

  useEffect(() => {
    if (!dataset) return;
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
  }, [dataset, folder]);

  if (!dataset) return null;
  const locked = busy || loading;
  const path = listing?.path || [];

  return (
    <>
      {error && <p className="import-error">{error}</p>}

      <div className="pennsieve-crumbs">
        <button type="button" disabled={locked || !folder} onClick={() => setFolder("")}>
          {datasetName || "Dataset"}
        </button>
        {path.map((p, i) => (
          <span key={p.id}>
            /{" "}
            <button
              type="button"
              disabled={locked || i === path.length - 1}
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
                onClick={() => !locked && setFolder(item.id)}
              >
                <span className="pennsieve-row-name">{item.name}/</span>
              </div>
            ) : (
              <div
                key={item.id}
                className={`pennsieve-row ${
                  onOpenFile && item.scan ? "" : "pennsieve-row-other"
                }`}
              >
                <span className="pennsieve-row-name" title={item.id}>
                  {item.name}
                </span>
                <span className="pennsieve-row-size">{formatSize(item.bytes)}</span>
                {onOpenFile && item.scan && (
                  <button
                    type="button"
                    className="btn btn-compact btn-primary"
                    disabled={locked}
                    onClick={() => onOpenFile(item)}
                  >
                    Open
                  </button>
                )}
              </div>
            )
          )}
      </div>

      {onChooseFolder && listing && (
        <div className="modal-actions" style={{ marginTop: -4, marginBottom: 12 }}>
          <button
            type="button"
            className="btn btn-compact btn-primary"
            disabled={locked}
            onClick={() =>
              onChooseFolder({
                id: folder,
                path: path.map((p) => p.name).join("/"),
              })
            }
          >
            Use this folder{path.length ? `: ${path.map((p) => p.name).join("/")}` : " (dataset root)"}
          </button>
        </div>
      )}
    </>
  );
}
