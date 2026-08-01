import { useState, useEffect, useRef } from "react";

const PRESETS = [
  { id: "bone", label: "Bone", min: 300, max: 1500 },
  // Wider than a pure-metal window so skull context stays visible while
  // electrodes still pop. Extreme 1500–3500 made the slices look empty.
  { id: "electrodes", label: "Electrodes", min: 800, max: 3000 },
  { id: "soft", label: "Soft", min: -100, max: 200 },
];

const LAYOUTS = [
  { id: "multi", label: "4-up", hint: "Axial + Coronal + Sagittal + 3D (0)" },
  { id: "axial", label: "A", hint: "Axial only (1)" },
  { id: "coronal", label: "C", hint: "Coronal only (2)" },
  { id: "sagittal", label: "S", hint: "Sagittal only (3)" },
  { id: "render", label: "3D", hint: "3D render only (4)" },
];

export default function Toolbar({
  scanFilename,
  calMin,
  calMax,
  onWindowChange,
  viewerLayout,
  onViewerLayoutChange,
  sidebarCollapsed,
  onToggleSidebar,
  dragMode = "contrast",
  onDragModeChange,
}) {
  const [autoLoading, setAutoLoading] = useState(false);
  const [localMin, setLocalMin] = useState(calMin);
  const [localMax, setLocalMax] = useState(calMax);
  const debounceRef = useRef(null);

  useEffect(() => {
    setLocalMin(calMin);
    setLocalMax(calMax);
  }, [calMin, calMax]);

  const nvDisabled = !scanFilename;

  const pushWindow = (min, max) => {
    if (!onWindowChange) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onWindowChange(min, max);
    }, 100);
  };

  const applyPreset = (preset) => {
    setLocalMin(preset.min);
    setLocalMax(preset.max);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    onWindowChange?.(preset.min, preset.max);
  };

  const applyAuto = async () => {
    if (!scanFilename) return;
    const API = process.env.REACT_APP_API_URL || "";
    setAutoLoading(true);
    try {
      const res = await fetch(`${API}/api/scans/${scanFilename}/range`);
      const data = await res.json();
      const min = Math.round(data.p1);
      const max = Math.round(data.p99);
      setLocalMin(min);
      setLocalMax(max);
      onWindowChange?.(min, max);
    } catch (err) {
      console.error("applyAuto:", err);
      alert("Auto windowing failed.");
    }
    setAutoLoading(false);
  };

  return (
    <div className="toolbar toolbar-viewer">
      <button
        type="button"
        className="btn btn-compact"
        onClick={onToggleSidebar}
        title={
          sidebarCollapsed
            ? "Show sidebar (F)"
            : "Hide sidebar for more viewer space (F)"
        }
      >
        {sidebarCollapsed ? "›" : "‹"}
      </button>

      <div className="layout-group" title="Viewer layout (keys 0–4)">
        {LAYOUTS.map((l) => (
          <button
            key={l.id}
            type="button"
            className={`btn ${viewerLayout === l.id ? "btn-primary" : ""}`}
            onClick={() => onViewerLayoutChange(l.id)}
            title={l.hint}
            disabled={nvDisabled}
          >
            {l.label}
          </button>
        ))}
      </div>

      <div className="toolbar-divider" />

      <div className="layout-group" title="What dragging the image does">
        {[
          ["contrast", "Contrast", "Drag adjusts brightness/contrast. Wheel steps slices."],
          ["pan", "Pan", "Drag moves the image; wheel zooms. Use the slice slider to change slices."],
        ].map(([id, label, hint]) => (
          <button
            key={id}
            type="button"
            className={`btn btn-compact ${dragMode === id ? "btn-primary" : ""}`}
            onClick={() => onDragModeChange?.(id)}
            title={hint}
            disabled={nvDisabled}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="toolbar-divider" />

      <div className="toolbar-presets" title="CT intensity window (Hounsfield units)">
        {PRESETS.map((p) => {
          const active = p.min === calMin && p.max === calMax;
          return (
            <button
              key={p.id}
              type="button"
              className={`btn btn-compact ${active ? "btn-primary" : ""}`}
              onClick={() => applyPreset(p)}
              disabled={nvDisabled}
              title={`${p.label} window: ${p.min} → ${p.max} HU`}
            >
              {p.label}
            </button>
          );
        })}
        <button
          type="button"
          className="btn btn-compact"
          onClick={applyAuto}
          disabled={nvDisabled || autoLoading}
          title="Auto window: 1st–99th percentile of this scan"
        >
          {autoLoading ? "…" : "Auto"}
        </button>
      </div>

      <label className="toolbar-slider" title="Display intensities below this as black">
        Min
        <input
          type="range"
          min={-1200}
          max={4000}
          value={localMin}
          onChange={(e) => {
            const v = Number(e.target.value);
            setLocalMin(v);
            pushWindow(v, localMax);
          }}
          disabled={nvDisabled}
        />
        <span className="threshold-value">{localMin}</span>
      </label>

      <label className="toolbar-slider" title="Display intensities above this as white">
        Max
        <input
          type="range"
          min={-200}
          max={5000}
          value={localMax}
          onChange={(e) => {
            const v = Number(e.target.value);
            setLocalMax(v);
            pushWindow(localMin, v);
          }}
          disabled={nvDisabled}
        />
        <span className="threshold-value">{localMax}</span>
      </label>
    </div>
  );
}
