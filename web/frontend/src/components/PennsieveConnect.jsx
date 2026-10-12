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
 * Sign in to Pennsieve, switch or remove saved workspaces, and set which
 * datasets this computer may use, all without a terminal.
 *
 * The API key and secret live in this component's state only until the
 * Connect request returns, and are cleared after every attempt. The secret box
 * is a masked text field, not type="password", and there is no <form>:
 * browsers offer to save, and then refill, anything that looks like a login,
 * which would put the secret in the browser's password manager.
 */
export default function PennsieveConnect({ open, onClose }) {
  const [status, setStatus] = useState(null);
  const [allowed, setAllowed] = useState([]);
  const [overridden, setOverridden] = useState(false);
  const [profile, setProfile] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
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
        setProfile(d.profile || d.profiles?.[0] || "");
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
    setShowSecret(false);
    load();
  }, [open, load]);

  const connect = useCallback(
    async (force = false) => {
      if (!apiKey.trim() || !apiSecret.trim()) return;
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
        if (!keep) {
          setApiKey("");
          setApiSecret("");
          setShowSecret(false);
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

  const removeProfile = useCallback(async () => {
    if (
      !window.confirm(
        `Remove the saved profile "${profile}" from this computer?\n\n` +
          "Its API key stays valid on Pennsieve until you delete it there."
      )
    )
      return;
    setBusy(`Removing ${profile}…`);
    setMessage(null);
    try {
      const { ok, data } = await postJson("/api/pennsieve/remove-profile", { profile });
      if (!ok) throw new Error(data.error);
      setMessage({ ok: `Removed profile "${profile}".` });
      load();
    } catch (e) {
      setMessage({ error: e.message || String(e) });
    } finally {
      setBusy("");
    }
  }, [profile, load]);

  const saveLimit = useCallback(async () => {
    setBusy("Saving…");
    setMessage(null);
    try {
      const { ok, data } = await postJson("/api/pennsieve/settings", { allowed_datasets: allowed });
      if (!ok) throw new Error(data.error);
      setMessage({
        ok: allowed.length
          ? `This computer now uses only the ${allowed.length} ticked dataset${
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
  const active = status?.profile;
  const toggle = (id) =>
    setAllowed((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  const onEnter = (e) => {
    if (e.key === "Enter") connect(false);
  };

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        // Opened over another dialog: a click here must not close that one too.
        e.stopPropagation();
        if (!busy) onClose(changed);
      }}
    >
      <div className="modal modal-medium" onClick={(e) => e.stopPropagation()}>
        <h2>Pennsieve connection</h2>

        {message?.error && <p className="import-error">{message.error}</p>}
        {message?.ok && <p className="pennsieve-ok">{message.ok}</p>}
        {busy && <p className="import-progress">{busy}</p>}
        {needsForce && (
          <div className="modal-actions" style={{ marginBottom: 12 }}>
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
                    {active && <span className="muted"> · profile {active}</span>}
                  </div>
                </>
              ) : (
                <div>{status.error || "Not signed in to Pennsieve."}</div>
              )}
            </div>

            {status.profiles?.length > 0 && (
              <section className="pennsieve-section">
                <h3>Workspace</h3>
                <p className="pennsieve-help">
                  Each saved profile is one API key for one workspace.
                </p>
                <div className="pennsieve-input-row">
                  <select
                    value={profile}
                    onChange={(e) => setProfile(e.target.value)}
                    disabled={!!busy}
                  >
                    {status.profiles.map((p) => (
                      <option key={p} value={p}>
                        {p}
                        {p === active ? " (in use)" : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    disabled={!!busy || !profile || profile === active}
                    onClick={() => switchTo(false)}
                  >
                    Switch
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={!!busy || !profile || profile === active}
                    title={profile === active ? "Switch to another profile first" : ""}
                    onClick={removeProfile}
                  >
                    Remove
                  </button>
                </div>
              </section>
            )}

            <section className="pennsieve-section">
              <h3>Connect a workspace</h3>
              <ol className="pennsieve-steps">
                <li>
                  On{" "}
                  <a href={PENNSIEVE_APP} target="_blank" rel="noreferrer">
                    Pennsieve
                  </a>
                  , open <strong>Account Settings → API Keys</strong>.
                </li>
                <li>
                  Choose the workspace and press <strong>Create API Key</strong>.
                </li>
                <li>Paste the key and secret below.</li>
              </ol>

              <div className="field">
                <label htmlFor="pennsieve-api-key">API key</label>
                <input
                  id="pennsieve-api-key"
                  type="text"
                  name="voxtool-pennsieve-key"
                  autoComplete="off"
                  data-1p-ignore
                  data-lpignore="true"
                  spellCheck={false}
                  placeholder="1a2b3c4d-…"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  onKeyDown={onEnter}
                  disabled={!!busy}
                />
              </div>
              <div className="field">
                <label htmlFor="pennsieve-api-secret">API secret</label>
                <div className="pennsieve-input-row">
                  <input
                    id="pennsieve-api-secret"
                    type="text"
                    name="voxtool-pennsieve-secret"
                    className={showSecret ? "" : "masked-input"}
                    autoComplete="off"
                    data-1p-ignore
                    data-lpignore="true"
                    spellCheck={false}
                    placeholder="Shown once on Pennsieve, when the key is made"
                    value={apiSecret}
                    onChange={(e) => setApiSecret(e.target.value)}
                    onKeyDown={onEnter}
                    disabled={!!busy}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowSecret((s) => !s)}
                    disabled={!!busy}
                  >
                    {showSecret ? "Hide" : "Show"}
                  </button>
                </div>
              </div>
              <div className="pennsieve-input-row" style={{ alignItems: "flex-start" }}>
                <p className="pennsieve-help" style={{ flex: 1, margin: 0 }}>
                  Checked with Pennsieve first, then saved only in Pennsieve's own settings on
                  this computer.
                </p>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!!busy || !apiKey.trim() || !apiSecret.trim()}
                  onClick={() => connect(false)}
                >
                  Connect
                </button>
              </div>
            </section>

            {connected && (
              <section className="pennsieve-section">
                <h3>Datasets this computer may use</h3>
                <p className="pennsieve-help">
                  Tick datasets to limit uploads, browsing and downloads to them. With none
                  ticked, every dataset you can edit is offered for uploads.
                  {overridden &&
                    " Overridden on this computer by VOXTOOL_PENNSIEVE_DATASETS."}
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
              </section>
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
