import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.REACT_APP_API_URL || "";

/**
 * Read an implant document and pre-fill the lead definitions.
 *
 * Nothing here writes to the app until the user presses Confirm, and every
 * value stays editable until they do. Leads the backend flagged for review are
 * marked with the reason, so the person confirming sees what the extraction was
 * unsure about instead of a flat list that all looks equally trustworthy.
 *
 * Only rendered when the backend reports it is running locally; the cloud
 * deployment refuses these endpoints outright.
 */
export default function DocumentImport({ open, onClose, onConfirm, existingLeads }) {
  const [status, setStatus] = useState(null);
  const [provider, setProvider] = useState("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [rows, setRows] = useState([]);
  const fileRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setError("");
    fetch(`${API}/api/extract/status`)
      .then((r) => r.json())
      .then((d) => {
        if (!d.success) throw new Error(d.error || "unavailable");
        setStatus(d);
        setProvider(d.providers?.ollama ? "ollama" : "none");
      })
      .catch((e) => setError(`Extraction is unavailable: ${e.message || e}`));
  }, [open]);

  const upload = useCallback(
    async (file) => {
      if (!file) return;
      setBusy(true);
      setError("");
      setResult(null);
      try {
        const form = new FormData();
        form.append("file", file);
        form.append("provider", provider);
        const res = await fetch(`${API}/api/extract/leads`, {
          method: "POST",
          body: form,
          // A local model on CPU can take a couple of minutes on a long document.
          signal: AbortSignal.timeout(600_000),
        });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
        setResult(data);
        setRows(
          data.leads.map((l) => ({
            ...l,
            include: true,
            contacts: String(l.contacts || ""),
          }))
        );
      } catch (e) {
        setError(e.message || String(e));
      } finally {
        setBusy(false);
      }
    },
    [provider]
  );

  const setRow = (i, patch) =>
    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const confirm = () => {
    const leads = [];
    const problems = [];
    rows
      .filter((r) => r.include)
      .forEach((r) => {
        const name = String(r.name || "").trim();
        const n = parseInt(r.contacts, 10);
        if (!name) return;
        if (!Number.isFinite(n) || n < 1) {
          problems.push(`${name} has no valid contact count`);
          return;
        }
        leads.push({
          name,
          type: r.type || "D",
          dimensions: [1, n],
          target: r.target || "",
        });
      });
    if (problems.length) {
      setError(problems.join("; "));
      return;
    }
    if (!leads.length) {
      setError("Nothing selected to import.");
      return;
    }
    onConfirm(leads);
  };

  if (!open) return null;

  const clashes = new Set(
    rows
      .filter((r) => r.include)
      .map((r) => String(r.name).trim().toUpperCase())
      .filter((n) => (existingLeads || []).some((l) => l.name.toUpperCase() === n))
  );
  const selected = rows.filter((r) => r.include).length;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Read implant document</h2>

        {error && <p className="import-error">{error}</p>}

        {!result && (
          <>
            <p className="muted" style={{ marginTop: 0 }}>
              Pick the implant PDF or PowerPoint. The file is read on this
              machine and is not uploaded anywhere.
            </p>
            <div className="field">
              <label>Reading method</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                disabled={busy}
              >
                <option value="none">
                  Channel map only — no model needed, gives no anatomical targets
                </option>
                <option value="ollama" disabled={!status?.providers?.ollama}>
                  Local model{status?.providers?.ollama ? "" : " (Ollama not running)"}
                </option>
              </select>
            </div>
            <div className="modal-actions modal-actions-scan">
              <button className="btn" onClick={onClose} disabled={busy}>
                Cancel
              </button>
              <label className="btn btn-primary" style={{ cursor: busy ? "wait" : "pointer" }}>
                {busy ? "Reading…" : "Choose document…"}
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.pptx"
                  style={{ display: "none" }}
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) upload(f);
                  }}
                />
              </label>
            </div>
          </>
        )}

        {result && (
          <>
            <p className="import-summary">
              <strong>{result.document?.name}</strong> — {result.document?.pages} page
              {result.document?.pages === 1 ? "" : "s"}, {result.leads.length} lead
              {result.leads.length === 1 ? "" : "s"} found
              {result.needs_review > 0 && `, ${result.needs_review} to check`}
            </p>

            {result.warnings?.map((w, i) => (
              <p key={i} className="import-warning">
                {w}
              </p>
            ))}

            <div className="import-table-wrap">
              <table className="import-table">
                <thead>
                  <tr>
                    <th />
                    <th>Lead</th>
                    <th>Contacts</th>
                    <th>Type</th>
                    <th>Target</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const clash = clashes.has(String(r.name).trim().toUpperCase());
                    return (
                      <tr
                        key={i}
                        className={r.confidence === "review" ? "import-row-review" : ""}
                      >
                        <td>
                          <input
                            type="checkbox"
                            checked={r.include}
                            onChange={(e) => setRow(i, { include: e.target.checked })}
                          />
                        </td>
                        <td>
                          <input
                            className="import-cell import-cell-name"
                            value={r.name}
                            onChange={(e) => setRow(i, { name: e.target.value })}
                          />
                          {clash && <span className="import-flag">replaces existing</span>}
                        </td>
                        <td>
                          <input
                            className="import-cell import-cell-num"
                            value={r.contacts}
                            onChange={(e) => setRow(i, { contacts: e.target.value })}
                          />
                        </td>
                        <td>
                          <select
                            className="import-cell"
                            value={r.type}
                            onChange={(e) => setRow(i, { type: e.target.value })}
                          >
                            <option value="D">D</option>
                            <option value="G">G</option>
                            <option value="S">S</option>
                          </select>
                        </td>
                        <td>
                          <input
                            className="import-cell"
                            value={r.target}
                            placeholder="—"
                            onChange={(e) => setRow(i, { target: e.target.value })}
                          />
                          {r.notes?.length > 0 && (
                            <span className="import-note">{r.notes.join(" ")}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="modal-actions modal-actions-scan">
              <button className="btn" onClick={() => setResult(null)}>
                Back
              </button>
              <button className="btn" onClick={onClose}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={confirm}>
                Add {selected} lead{selected === 1 ? "" : "s"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
