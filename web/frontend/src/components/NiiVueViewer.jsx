import { useEffect, useRef } from "react";
import { Niivue } from "@niivue/niivue";

const API = process.env.REACT_APP_API_URL || "";

/** Numeric order for labels like LA1 (first integer in string). */
function contactLabelSortKey(label) {
  if (label == null) return NaN;
  const m = String(label).match(/\d+/);
  return m ? parseInt(m[0], 10) : NaN;
}

function buildContactsConnectome(contacts, leads) {
  const leadIdx = (name) =>
    Math.max(0, leads.findIndex((l) => l.name === name));
  const nodes = contacts.map((c) => ({
    name: `${c.lead}${c.label}`,
    x: c.coord?.R ?? 0,
    y: c.coord?.A ?? 0,
    z: c.coord?.S ?? 0,
    colorValue: leadIdx(c.lead),
    sizeValue: 1,
  }));

  const edges = [];
  const byLead = new Map();
  contacts.forEach((c, i) => {
    if (!c.coord) return;
    const n = contactLabelSortKey(c.label);
    if (!Number.isFinite(n)) return;
    if (!byLead.has(c.lead)) byLead.set(c.lead, []);
    byLead.get(c.lead).push({ i, n });
  });
  for (const [leadName, arr] of byLead) {
    arr.sort((a, b) => a.n - b.n);
    const cv = leadIdx(leadName);
    for (let k = 0; k < arr.length - 1; k++) {
      edges.push({
        first: arr[k].i,
        second: arr[k + 1].i,
        colorValue: cv,
      });
    }
  }

  const maxLeadIdx = Math.max(1, leads.length - 1);
  return {
    name: "contacts",
    nodes,
    edges,
    nodeColormap: "warm",
    nodeColormapNegative: "winter",
    nodeMinColor: 0,
    nodeMaxColor: maxLeadIdx,
    nodeScale: 2.0,
    edgeColormap: "warm",
    edgeColormapNegative: "winter",
    edgeMin: 0,
    edgeMax: maxLeadIdx,
    edgeScale: 1.25,
    legendLineThickness: 0,
  };
}

function buildPreviewConnectome(coord, label) {
  return {
    name: "preview",
    nodes: [
      {
        name: label || "?",
        x: coord.R,
        y: coord.A,
        z: coord.S,
        colorValue: 1,
        sizeValue: 1.4,
      },
    ],
    edges: [],
    // Yellow-ish: use 'warm' min/max so colorValue 1 maps to bright yellow
    nodeColormap: "warm",
    nodeColormapNegative: "winter",
    nodeMinColor: 0,
    nodeMaxColor: 1,
    nodeScale: 2.5,
    edgeColormap: "warm",
    edgeColormapNegative: "winter",
    edgeMin: 2,
    edgeMax: 6,
    edgeScale: 1,
    legendLineThickness: 0,
  };
}

// NiiVue sliceType: 0=axial, 1=coronal, 2=sagittal, 3=multiplanar, 4=render
const LAYOUT_TO_SLICETYPE = {
  axial: 0,
  coronal: 1,
  sagittal: 2,
  multi: 3,
  render: 4,
};

export default function NiiVueViewer({
  scanFilename,
  calMin,
  calMax,
  onLocationChange,
  contacts,
  leads,
  pendingContact,
  layout = "multi",
  snapRadius = 3,
  snapThresholdPct = 99.96,
  showRasTags = true,
}) {
  const canvasRef = useRef(null);
  const nvRef = useRef(null);
  const markerMeshRef = useRef(null);
  const previewMeshRef = useRef(null);
  const snapTimerRef = useRef(null);
  const snapAbortRef = useRef(null);

  const onLocationChangeRef = useRef(onLocationChange);
  useEffect(() => {
    onLocationChangeRef.current = onLocationChange;
  }, [onLocationChange]);

  const scanFilenameRef = useRef(scanFilename);
  useEffect(() => {
    scanFilenameRef.current = scanFilename;
  }, [scanFilename]);

  const snapRadiusRef = useRef(snapRadius);
  const snapThresholdRef = useRef(snapThresholdPct);
  useEffect(() => {
    snapRadiusRef.current = snapRadius;
  }, [snapRadius]);
  useEffect(() => {
    snapThresholdRef.current = snapThresholdPct;
  }, [snapThresholdPct]);

  // Initialise NiiVue once.
  useEffect(() => {
    if (nvRef.current) return;
    const nv = new Niivue({
      backColor: [0.05, 0.05, 0.08, 1],
      crosshairColor: [1, 0.4, 0.4, 1],
      show3Dcrosshair: false,
      sliceType: 3,
      multiplanarLayout: 2,
      multiplanarShowRender: 1,
      isHighResolutionCapable: false,
      isAntiAlias: false,
      isOrientCube: true,
      // Connectome node names (RA1, …) otherwise become a fixed right-side
      // legend panel that floats over every slice while you scroll.
      showLegend: false,
    });
    nv.attachToCanvas(canvasRef.current);

    let lastLocCall = 0;
    nv.onLocationChange = (data) => {
      const now = performance.now();
      if (now - lastLocCall < 30) return;
      lastLocCall = now;
      if (!data?.mm) return;

      const rawCoord = {
        R: parseFloat(data.mm[0].toFixed(1)),
        A: parseFloat(data.mm[1].toFixed(1)),
        S: parseFloat(data.mm[2].toFixed(1)),
        snapped: false,
      };
      onLocationChangeRef.current?.(rawCoord);

      // Short debounce so a rapid drag doesn't slam the backend, but the
      // snap response feels near-instant after the click settles.
      if (snapTimerRef.current) clearTimeout(snapTimerRef.current);
      if (snapAbortRef.current) snapAbortRef.current.abort();
      snapTimerRef.current = setTimeout(() => {
        runSnap(rawCoord);
      }, 80);
    };

    nvRef.current = nv;

    return () => {
      if (snapTimerRef.current) clearTimeout(snapTimerRef.current);
      if (snapAbortRef.current) snapAbortRef.current.abort();
    };
  }, []);

  const runSnap = (rawCoord) => {
    const fname = scanFilenameRef.current;
    if (!fname) return;
    const controller = new AbortController();
    snapAbortRef.current = controller;
    fetch(`${API}/api/scans/${fname}/snap`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        point_mm: [rawCoord.R, rawCoord.A, rawCoord.S],
        radius_mm: snapRadiusRef.current,
        threshold_pct: snapThresholdRef.current,
        iterations: 2,
      }),
      signal: controller.signal,
    })
      .then((r) => r.json())
      .then((res) => {
        if (!res || !res.success) return;
        onLocationChangeRef.current?.({
          R: parseFloat(res.center_mm[0].toFixed(1)),
          A: parseFloat(res.center_mm[1].toFixed(1)),
          S: parseFloat(res.center_mm[2].toFixed(1)),
          snapped: true,
          voxelCount: res.voxel_count,
          centerVoxel:
            Array.isArray(res.center_voxel) && res.center_voxel.length === 3
              ? res.center_voxel
              : null,
        });
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
      });
  };

  // Load volume when filename changes.
  useEffect(() => {
    if (!scanFilename || !nvRef.current) return;
    const nv = nvRef.current;
    const url = `${API}/api/scans/${scanFilename}`;
    // Use "gray" (not ct_skull): ct_skull bakes fixed HU min/max into the
    // colormap, which made Bone/Soft/Electrodes/sliders look like no-ops.
    nv.loadVolumes([
      {
        url,
        colormap: "gray",
        cal_min: calMin,
        cal_max: calMax,
      },
    ]).then(() => {
      // Matte volume (0): real volume look, cheaper than gradient lighting (0.4).
      // Do NOT use negative values — that switches to the "cube split" slice shader.
      nv.setVolumeRenderIllumination(0);
      nv.setRenderAzimuthElevation(120, 10);
      nv.volScaleMultiplier = 1.0;
      nv.setSliceMM(true);
      // Infinity draws the entire connectome on every 2D slice, so contacts
      // appear to hover in fixed screen positions while you scroll. A few mm
      // keeps a contact visible only near the slice it belongs on.
      nv.setMeshThicknessOn2D(4);
      nv.setClipPlaneThick(0.7);
      if (nv.volumes?.[0]) {
        nv.volumes[0].cal_min = calMin;
        nv.volumes[0].cal_max = calMax;
        nv.updateGLVolume();
      } else {
        nv.drawScene?.();
      }
    });
    // Intentionally omit calMin/calMax from deps — window changes are handled
    // by the intensity effect below so we don't reload the whole volume.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanFilename]);

  // Layout: switch which slice(s) NiiVue draws, and whether the 3D render
  // pane is visible alongside the multiplanar grid.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv) return;
    const sliceType = LAYOUT_TO_SLICETYPE[layout] ?? 3;
    nv.setSliceType(sliceType);
    // Only show the 3D render in the 4th tile when in multiplanar mode.
    nv.opts.multiplanarShowRender = layout === "multi" ? 1 : 0;
    nv.drawScene?.();
  }, [layout]);

  // Intensity window — Bone/Soft/Electrodes/Auto + Min/Max sliders.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv || !nv.volumes || nv.volumes.length === 0) return;
    const t = setTimeout(() => {
      const vol = nv.volumes[0];
      if (!vol) return;
      vol.cal_min = calMin;
      vol.cal_max = calMax;
      if (vol.hdr) {
        vol.hdr.cal_min = calMin;
        vol.hdr.cal_max = calMax;
      }
      nv.updateGLVolume();
    }, 50);
    return () => clearTimeout(t);
  }, [calMin, calMax]);

  useEffect(() => {
    const nv = nvRef.current;
    if (!nv) return;
    // NiiVue exposes `opts` as read-only; use setters only (never assign nv.opts).
    if (typeof nv.setIsOrientationTextVisible === "function") {
      nv.setIsOrientationTextVisible(!!showRasTags);
    }
    if (typeof nv.setShowAllOrientationMarkers === "function") {
      nv.setShowAllOrientationMarkers(!!showRasTags);
    }
    nv.drawScene?.();
  }, [showRasTags]);

  // Committed contact markers.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv || !nv.volumes || nv.volumes.length === 0) return;
    if (markerMeshRef.current) {
      try {
        nv.removeMesh(markerMeshRef.current);
      } catch (e) {}
      markerMeshRef.current = null;
    }
    if (!contacts || contacts.length === 0) {
      nv.drawScene?.();
      return;
    }
    try {
      const mesh = nv.loadConnectomeAsMesh(
        buildContactsConnectome(contacts, leads || [])
      );
      // Hide the colorbar strip (often just a lone "9") that connectome meshes
      // otherwise draw on the right edge of the viewer.
      mesh.colorbarVisible = false;
      nv.addMesh(mesh);
      markerMeshRef.current = mesh;
      nv.drawScene?.();
    } catch (err) {
      console.warn("contact mesh build failed", err);
    }
  }, [contacts, leads]);

  // Pending preview marker.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv || !nv.volumes || nv.volumes.length === 0) return;
    if (previewMeshRef.current) {
      try {
        nv.removeMesh(previewMeshRef.current);
      } catch (e) {}
      previewMeshRef.current = null;
    }
    if (!pendingContact || !pendingContact.coord) {
      nv.drawScene?.();
      return;
    }
    try {
      const mesh = nv.loadConnectomeAsMesh(
        buildPreviewConnectome(pendingContact.coord, pendingContact.label)
      );
      mesh.colorbarVisible = false;
      nv.addMesh(mesh);
      previewMeshRef.current = mesh;
      nv.drawScene?.();
    } catch (err) {
      console.warn("preview mesh build failed", err);
    }
  }, [pendingContact]);

  return (
    <div className="viewer-container">
      <canvas ref={canvasRef} />
    </div>
  );
}
