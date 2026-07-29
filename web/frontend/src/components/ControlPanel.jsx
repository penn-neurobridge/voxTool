import { useState } from "react";
import ContactList from "./ContactList";

const LEAD_TYPES = [
  { code: "D", name: "Depth" },
  { code: "G", name: "Grid" },
  { code: "S", name: "Strip" },
];

export default function ControlPanel({
  scanLoaded,
  scanFilename,
  leads,
  setLeads,
  selectedLead,
  setSelectedLead,
  contacts,
  nextLabel,
  contactIndexInput,
  setContactIndexInput,
  pendingContact,
  onCommitPending,
  onCancelPending,
  onDeleteContact,
  onInterpolate,
  interpolating,
  interpStatus,
  onClearInterpStatus,
  currentCoord,
  showRasTags,
  setShowRasTags,
  includeBipolarPairs,
  setIncludeBipolarPairs,
  onLoadScan,
  onLoadCoordinates,
  onSave,
  saving,
  onCleanScan,
  loadFileInputRef,
  onAnnotationFileSelected,
}) {
  const [newLeadName, setNewLeadName] = useState("");
  const [newLeadType, setNewLeadType] = useState("D");
  const [newLeadDimX, setNewLeadDimX] = useState(1);
  const [newLeadDimY, setNewLeadDimY] = useState(8);
  const [defineLeadsOpen, setDefineLeadsOpen] = useState(false);

  const addLead = () => {
    const name = newLeadName.trim();
    if (!name) return;
    if (leads.find((l) => l.name === name)) return;
    setLeads([
      ...leads,
      {
        name,
        type: newLeadType,
        dimensions: [parseInt(newLeadDimX) || 1, parseInt(newLeadDimY) || 1],
      },
    ]);
    setNewLeadName("");
    if (!selectedLead) setSelectedLead(name);
  };

  const removeLead = (name) => {
    setLeads(leads.filter((l) => l.name !== name));
    if (selectedLead === name) {
      const remaining = leads.filter((l) => l.name !== name);
      setSelectedLead(remaining.length > 0 ? remaining[0].name : "");
    }
  };

  const activeLead = leads.find((l) => l.name === selectedLead);
  const leadContactCount = contacts.filter((c) => c.lead === selectedLead).length;
  const totalOnLead = activeLead
    ? activeLead.dimensions[0] * activeLead.dimensions[1]
    : 0;
  const dimX = activeLead?.dimensions[0] ?? 1;
  const dimY = activeLead?.dimensions[1] ?? 1;
  const canInterpolate = !!activeLead && leadContactCount >= 2;
  const idxForGrid = (() => {
    const n = parseInt(contactIndexInput, 10);
    if (!Number.isNaN(n) && n >= 1) return n;
    const m = parseInt(nextLabel, 10);
    return !Number.isNaN(m) && m >= 1 ? m : 1;
  })();
  const zero = Math.min(Math.max(idxForGrid - 1, 0), dimX * dimY - 1);
  const gridX = (zero % dimX) + 1;
  const gridY = Math.floor(zero / dimX) + 1;

  const formatRas = (v) => {
    if (v === undefined || v === null || v === "—") return "—";
    const n = typeof v === "number" ? v : parseFloat(v);
    if (Number.isNaN(n)) return String(v);
    const s = n.toFixed(1);
    return s.replace(/^(-?)0\./, "$1.");
  };

  return (
    <div className="sidebar">
      <div className="panel-section panel-labeling">
        <h3 className="panel-heading">Labeling</h3>
        <div className="label-row">
          <div className="field field-grow">
            <label>Label</label>
            <select
              value={selectedLead}
              onChange={(e) => setSelectedLead(e.target.value)}
              disabled={leads.length === 0}
            >
              <option value="">— select lead —</option>
              {leads.map((l) => (
                <option key={l.name} value={l.name}>
                  {l.name} ({l.dimensions[0]}×{l.dimensions[1]})
                </option>
              ))}
            </select>
          </div>
          <div className="field field-index">
            <label>#</label>
            <input
              type="number"
              min={1}
              value={contactIndexInput}
              onChange={(e) => setContactIndexInput(e.target.value)}
              disabled={!activeLead}
              title="Contact index on this lead (e.g. 1…N)"
            />
          </div>
        </div>
        {activeLead && (
          <div className="next-hint muted">
            Suggested next free index: <strong>{nextLabel}</strong>
          </div>
        )}

        {activeLead && (
          <div className="lead-meta-line">
            Lead x: {gridX}/{dimX} y: {gridY}/{dimY} · group: 0 · marked{" "}
            {leadContactCount}/{totalOnLead}
          </div>
        )}

        <div className="ras-inline">
          <span>
            R: <strong>{formatRas(currentCoord?.R)}</strong>
          </span>
          <span>
            A: <strong>{formatRas(currentCoord?.A)}</strong>
          </span>
          <span>
            S: <strong>{formatRas(currentCoord?.S)}</strong>
          </span>
        </div>

        {currentCoord && (
          <div
            className={`snap-status ${
              currentCoord.snapped ? "snap-status-ok" : "snap-status-wait"
            }`}
          >
            {currentCoord.snapped
              ? `Snapped · ${currentCoord.voxelCount ?? "?"} voxels`
              : "Raw crosshair — snapping…"}
          </div>
        )}

        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={showRasTags}
            onChange={(e) => setShowRasTags(e.target.checked)}
          />
          Show RAS / orientation tags in viewer
        </label>

        <div className="submit-row">
          <button
            type="button"
            className="btn btn-primary btn-submit-wide"
            onClick={onCommitPending}
            disabled={!pendingContact || !scanLoaded}
            title="Keyboard: S (when focus is not in a field)"
          >
            {pendingContact
              ? `Submit ${pendingContact.lead}${pendingContact.label}`
              : "Submit"}
          </button>
          {pendingContact && (
            <button
              type="button"
              className="btn"
              onClick={onCancelPending}
              title="Keyboard: Esc"
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      <div className="panel-section panel-contacts flex-grow">
        <h3 className="panel-heading">Contacts</h3>
        <ContactList
          contacts={contacts}
          leads={leads}
          onDelete={onDeleteContact}
        />
      </div>

      <div className="panel-section panel-workflow">
        <button
          type="button"
          className="btn btn-wide"
          onClick={onInterpolate}
          disabled={!scanLoaded || !canInterpolate || interpolating}
          title={
            canInterpolate
              ? "Between two endpoint labels (e.g. 1 & 12), places missing contacts evenly along the straight line between them, then snaps each to nearby bright voxels (legacy voxTool math). Consecutive 1 & 2 still extends by spacing to 3…N."
              : "Mark at least two contacts on this lead."
          }
        >
          {interpolating ? "Interpolating…" : "Interpolate"}
        </button>
        {interpStatus && (
          <div className={`interp-status interp-status-${interpStatus.tone}`}>
            <span>{interpStatus.text}</span>
            <button
              type="button"
              className="btn-icon interp-status-close"
              onClick={onClearInterpStatus}
              title="Dismiss"
            >
              ×
            </button>
          </div>
        )}
        <button
          type="button"
          className="btn btn-wide"
          disabled
          title="Not available in the web viewer yet."
        >
          Seeding
        </button>
        <button
          type="button"
          className="btn btn-wide"
          disabled
          title="Not available in the web viewer yet."
        >
          Add micro-contacts
        </button>
      </div>

      <div
        className={`panel-section panel-define-leads ${
          defineLeadsOpen ? "is-open" : ""
        }`}
      >
        <button
          type="button"
          className="btn btn-wide btn-ghost"
          onClick={() => setDefineLeadsOpen((o) => !o)}
        >
          {defineLeadsOpen ? "▼ Hide define leads" : "▶ Define leads"}
        </button>
        {defineLeadsOpen && (
          <div className="define-leads-body">
            <div className="field">
              <label>Lead name</label>
              <input
                type="text"
                value={newLeadName}
                onChange={(e) => setNewLeadName(e.target.value)}
                placeholder="e.g. LA, RA, RB"
                onKeyDown={(e) => e.key === "Enter" && addLead()}
              />
            </div>
            <div className="define-leads-dims">
              <div className="field">
                <label>Type</label>
                <select
                  value={newLeadType}
                  onChange={(e) => setNewLeadType(e.target.value)}
                >
                  {LEAD_TYPES.map((t) => (
                    <option key={t.code} value={t.code}>
                      {t.code}: {t.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field field-tight">
                <label>X</label>
                <input
                  type="number"
                  min={1}
                  value={newLeadDimX}
                  onChange={(e) => setNewLeadDimX(e.target.value)}
                />
              </div>
              <div className="field field-tight">
                <label>Y</label>
                <input
                  type="number"
                  min={1}
                  value={newLeadDimY}
                  onChange={(e) => setNewLeadDimY(e.target.value)}
                />
              </div>
            </div>
            <button
              type="button"
              className="btn"
              onClick={addLead}
              disabled={!newLeadName.trim()}
            >
              Add lead
            </button>
            {leads.length > 0 && (
              <ul className="lead-chip-list">
                {leads.map((lead) => {
                  const count = contacts.filter((c) => c.lead === lead.name)
                    .length;
                  const tot = lead.dimensions[0] * lead.dimensions[1];
                  return (
                    <li key={lead.name}>
                      <span>
                        <strong>{lead.name}</strong>{" "}
                        <span className="muted">
                          ({lead.type}, {count}/{tot})
                        </span>
                      </span>
                      <button
                        type="button"
                        className="btn-icon"
                        onClick={() => removeLead(lead.name)}
                        title="Remove lead"
                      >
                        ×
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="sidebar-footer">
        <input
          ref={loadFileInputRef}
          type="file"
          accept=".json,.txt,application/json,text/plain"
          style={{ display: "none" }}
          onChange={onAnnotationFileSelected}
        />
        <div className="footer-row">
          <button type="button" className="btn" onClick={onLoadScan}>
            Load scan
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => setDefineLeadsOpen(true)}
          >
            Define leads
          </button>
          <button
            type="button"
            className="btn"
            onClick={onLoadCoordinates}
            disabled={!scanLoaded}
            title="Open voxel_coordinates.json or .txt from your computer"
          >
            Load coordinates
          </button>
        </div>
        <div className="footer-row">
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSave}
            disabled={!scanLoaded || saving}
            title="Save leads & contacts as JSON or TXT"
          >
            {saving ? "Saving…" : "Save as…"}
          </button>
          <label className="checkbox-inline footer-checkbox">
            <input
              type="checkbox"
              checked={includeBipolarPairs}
              onChange={(e) => setIncludeBipolarPairs(e.target.checked)}
            />
            Bipolar pairs
          </label>
          <button
            type="button"
            className="btn"
            onClick={onCleanScan}
            disabled={contacts.length === 0 && !pendingContact}
          >
            Clean scan
          </button>
        </div>
        {scanFilename && (
          <div className="footer-scan-name muted" title={scanFilename}>
            {scanFilename}
          </div>
        )}
      </div>
    </div>
  );
}
