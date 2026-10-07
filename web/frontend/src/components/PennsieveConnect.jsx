import { useCallback, useEffect, useState } from "react";

const API = process.env.REACT_APP_API_URL || "";
const PENNSIEVE_APP = "https://app.pennsieve.io";
const AGENT_DOCS = "https://docs.pennsieve.io/docs/the-pennsieve-agent";

async function postJson(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(120_000),
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok && data.success, status: res.status, data };
}

/**
 * Sign in to Pennsieve, switch workspace, and set which datasets this computer
 * may use, all without a terminal.
 *
 * The API key and secret live in this component's state only until the
 * Connect request returns; they are cleared whatever the outcome. The backend
 * checks them with Pennsieve before saving them anywhere.
 */
export default function PennsieveConnect({ open, onClose }) {
  const [status, setStatus] = useState(null);
  const [allowed, setAllowed] = useState([]);
  const [overridden, setOverridden] = useState(false);
  const [profile, setProfile] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [busy, setBusy] = useState("");
  const [needsForce, setNeedsForce] = useState(null);
  const [message, setMessage] = useState(null);
  const [changed, setChanged] = useState(false);

  const load = useCallback(() => {
    setStatus(null);
    fetch(`${API}/api/pennsieve/status?auto_start=1&all=1`)
      .then((r) => r.json())
      .then((d) => {
        setStatus(d);
        setProfile(d.profile || "");
      })
      .catch((e) => setMessage({ error: `Could not reach Pennsieve: ${e.message || e}` }));
    fetch(`${API}/api/pennsieve/settings`)
      .then((r) => r.json())
      .then((d) => {
        setAllowed(d.allowed_datasets || []);
        setOverridden(!!d.overridden);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!open) return;
    setMessage(null);
    setNeedsForce(null);
    setChanged(false);
    load();
  }, [open, load]);

  const connect = useCallback(
    async (force = false) => {
      setBusy("Checking the key with Pennsieve…");
      setMessage(null);
      setNeedsForce(null);
      // Kept only when the attempt was held back for a running upload, so
      // "Connect anyway" can retry without pasting again.
      let keep = false;
      try {
        const { ok, status: code, data } = await postJson("/api/pennsieve/connect", {
          api_key: apiKey,
          api_secret: apiSecret,
          force,
        });
        if (code === 409 && data.busy) {
          keep = true;
          setNeedsForce("connect");
          setMessage({ error: data.error });
          return;
        }
        if (!ok) throw new Error(data.error || `HTTP ${code}`);
        setMessage({
          ok: `Connected to ${data.workspace} as ${data.user}${
            data.new ? `, saved as profile "${data.profile}"` : ` (profile "${data.profile}")`
          }.`,
        });
        setChanged(true);
        load();
      } catch (e) {
        setMessage({ error: e.message || String(e) });
      } finally {
        // Never keep a key around longer than one attempt.
        if (!keep) {
          setApiKey("");
          setApiSecret("");
        }
        setBusy("");
      }
    },
    [apiKey, apiSecret, load]
  );

  const switchTo = useCallback(
    async (force = false) => {
      setBusy(`Switching to ${profile}…`);
      setMessage(null);
      setNeedsForce(null);
      try {
        const { ok, status: code, data } = await postJson("/api/pennsieve/switch", {
          profile,
          force,
        });
        if (code === 409 && data.busy) {
          setNeedsForce("switch");
          setMessage({ error: data.error });
          return;
        }
        if (!ok) throw new Error(data.error || `HTTP ${code}`);
        setMessage({ ok: `Now using ${data.workspace} (profile "${data.profile}").` });
        setChanged(true);
        load();
      } catch (e) {
        setMessage({ error: e.message || String(e) });
      } finally {
        setBusy("");
      }
    },
    [profile, load]
  );

  const saveLimit = useCallback(async () => {
    setBusy("Saving…");
    setMessage(null);
    try {
      const { ok, data } = await postJson("/api/pennsieve/settings", { allowed_datasets: allowed });
      if (!ok) throw new Error(data.error);
      setMessage({
        ok: allowed.length
          ? `This computer now uses only the ${allowed.length} checked dataset${
              allowed.length === 1 ? "" : "s"
            }.`
          : "No limit: every dataset you can edit is offered for uploads.",
      });
      setChanged(true);
    } catch (e) {
      setMessage({ error: e.message || String(e) });
    } finally {
      setBusy("");
    }
  }, [allowed]);

  if (!open) return null;

  const connected = status?.agent_running;
  const toggle = (id) =>
    setAllowed((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        // Opened over another dialog: a click here must not close that one too.
        e.stopPropagation();
        if (!busy) onClose(changed);
      }}
    >
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Pennsieve connection</h2>

        {message?.error && <p className="import-error">{message.error}</p>}
        {message?.ok && <p className="pennsieve-ok">{message.ok}</p>}
        {busy && <p className="import-progress">{busy}</p>}

        {!status && <p className="muted">Checking Pennsieve on this computer…</p>}

        {status && !status.installed && (
          <p className="import-warning">
            VoxTool talks to Pennsieve through the Pennsieve agent, which is not installed on
            this computer.{" "}
            <a href={AGENT_DOCS} target="_blank" rel="noreferrer">
              Install it
            </a>
            , then reopen this window.
          </p>
        )}

        {status?.installed && (
          <>
            <div className="pennsieve-dest">
              {connected ? (
                <>
                  <div>
                    <span className="muted">Signed in as</span> <strong>{status.user}</strong>
                  </div>
                  <div>
                    <span className="muted">Workspace</span> <strong>{status.workspace}</strong>
                    {status.profile && <span className="muted"> · profile {status.profile}</span>}
                  </div>
                </>
              ) : (
                <div>{status.error || "Not signed in to Pennsieve."}</div>
              )}
            </div>

            {status.profiles?.length > 1 && (
              <div className="field">
                <label>Switch workspace (saved profiles)</label>
                <div style={{ display: "flex", gap: 8 }}>
                  <select
                    style={{ flex: 1 }}
                    value={profile}
                    onChange={(e) => setProfile(e.target.value)}
                    disabled={!!busy}
                  >
                    {!status.profile && <option value="">— choose —</option>}
                    {status.profiles.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    disabled={!!busy || !profile || profile === status.profile}
                    onClick={() => switchTo(false)}
                  >
                    Switch
                  </button>
                </div>
              </div>
            )}

            <form
              className="field"
              autoComplete="off"
              onSubmit={(e) => {
                e.preventDefault();
                connect(false);
              }}
            >
              <label>Connect a workspace</label>
              <p className="muted" style={{ marginTop: 0 }}>
                On{" "}
                <a href={PENNSIEVE_APP} target="_blank" rel="noreferrer">
                  Pennsieve
                </a>
                , open <strong>Account Settings → API Keys</strong>, choose the workspace, and
                press <strong>Create API Key</strong>. Paste the key and secret here. They are
                checked with Pennsieve, then saved only in Pennsieve's own settings on this
                computer.
              </p>
              <input
                type="text"
                placeholder="API key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={!!busy}
                spellCheck={false}
              />
              <input
                type="password"
                placeholder="API secret"
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                disabled={!!busy}
                style={{ marginTop: 8 }}
              />
              <div className="modal-actions" style={{ marginTop: 8 }}>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={!!busy || !apiKey.trim() || !apiSecret.trim()}
                >
                  Connect
                </button>
              </div>
            </form>

            {needsForce && (
              <div className="modal-actions">
                <button
                  type="button"
                  className="btn"
                  disabled={!!busy}
                  onClick={() => (needsForce === "switch" ? switchTo(true) : connect(true))}
                >
                  {needsForce === "switch" ? "Switch anyway" : "Connect anyway"}
                </button>
              </div>
            )}

            {connected && (
              <div className="field">
                <label>Datasets this computer may use</label>
                <p className="muted" style={{ marginTop: 0 }}>
                  Tick datasets to limit uploads, browsing and downloads to them. With none
                  ticked, every dataset you can edit is offered for uploads.
                  {overridden &&
                    " This is overridden on this computer by VOXTOOL_PENNSIEVE_DATASETS."}
                </p>
                <div className="pennsieve-list">
                  {(status.datasets || []).map((d) => (
                    <label key={d.id} className="pennsieve-row" style={{ cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={allowed.includes(d.id)}
                        onChange={() => toggle(d.id)}
                        disabled={!!busy || overridden}
                      />
                      <span className="pennsieve-row-name">{d.name}</span>
                      <span className="pennsieve-row-size">{d.role || ""}</span>
                    </label>
                  ))}
                </div>
                <div className="modal-actions">
                  <button
                    type="button"
                    className="btn"
                    disabled={!!busy || overridden}
                    onClick={saveLimit}
                  >
                    Save limit
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        <div className="modal-actions modal-actions-scan">
          <button className="btn btn-primary" onClick={() => onClose(changed)} disabled={!!busy}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
