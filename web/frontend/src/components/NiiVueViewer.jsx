import { useEffect, useRef } from "react";
import { Niivue } from "@niivue/niivue";
import { LEAD_PALETTE_HEX, leadColormap } from "../leadColors";

const API = process.env.REACT_APP_API_URL || "";

/** Numeric order for labels like LA1 (first integer in string). */
function contactLabelSortKey(label) {
  if (label == null) return NaN;
  const m = String(label).match(/\d+/);
  return m ? parseInt(m[0], 10) : NaN;
}

function buildContactsConnectome(contacts, leads) {
  const leadIdx = (name) => {
    const i = leads.findIndex((l) => l.name === name);
    return Math.max(0, i);
  };
  const nodes = contacts
    .filter((c) => c.coord)
    .map((c) => ({
      name: `${c.lead}${c.label}`,
      x: c.coord.R,
      y: c.coord.A,
      z: c.coord.S,
      colorValue: leadIdx(c.lead),
      sizeValue: 1,
    }));

  // Rebuild index map after filter so edge indices stay valid.
  const indexByKey = new Map();
  contacts.forEach((c, i) => {
    if (c.coord) indexByKey.set(i, indexByKey.size);
  });

  const edges = [];
  const byLead = new Map();
  contacts.forEach((c, i) => {
    if (!c.coord) return;
    const n = contactLabelSortKey(c.label);
    if (!Number.isFinite(n)) return;
    if (!byLead.has(c.lead)) byLead.set(c.lead, []);
    byLead.get(c.lead).push({ i: indexByKey.get(i), n });
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

  const maxLeadIdx = Math.max(LEAD_PALETTE_HEX.length - 1, 1);
  return {
    name: "contacts",
    nodes,
    edges,
    nodeColormap: "voxtool-leads",
    nodeColormapNegative: "voxtool-leads",
    nodeMinColor: 0,
    nodeMaxColor: maxLeadIdx,
    // Larger than before so Soft/Bone windows still show markers clearly.
    nodeScale: 3.2,
    edgeColormap: "voxtool-leads",
    edgeColormapNegative: "voxtool-leads",
    edgeMin: 0,
    edgeMax: maxLeadIdx,
    edgeScale: 1.5,
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
        colorValue: 7, // orange-ish in the shared palette
        sizeValue: 1.5,
      },
    ],
    edges: [],
    nodeColormap: "voxtool-leads",
    nodeColormapNegative: "voxtool-leads",
    nodeMinColor: 0,
    nodeMaxColor: Math.max(LEAD_PALETTE_HEX.length - 1, 1),
    nodeScale: 3.6,
    edgeColormap: "voxtool-leads",
    edgeColormapNegative: "voxtool-leads",
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
  active = true,
}) {
  const canvasRef = useRef(null);
  const nvRef = useRef(null);
  const markerMeshRef = useRef(null);
  const previewMeshRef = useRef(null);
  const snapTimerRef = useRef(null);
  const snapAbortRef = useRef(null);
  const volumeReadyRef = useRef(false);
  const contactsRef = useRef(contacts);
  const leadsRef = useRef(leads);
  const pendingRef = useRef(pendingContact);

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

  useEffect(() => {
    contactsRef.current = contacts;
  }, [contacts]);
  useEffect(() => {
    leadsRef.current = leads;
  }, [leads]);
  useEffect(() => {
    pendingRef.current = pendingContact;
  }, [pendingContact]);

  const rebuildMarkers = () => {
    const nv = nvRef.current;
    if (!nv || !volumeReadyRef.current || !nv.volumes?.length) return;

    if (markerMeshRef.current) {
      try {
        nv.removeMesh(markerMeshRef.current);
      } catch (e) {}
      markerMeshRef.current = null;
    }
    if (previewMeshRef.current) {
      try {
        nv.removeMesh(previewMeshRef.current);
      } catch (e) {}
      previewMeshRef.current = null;
    }

    const cts = contactsRef.current || [];
    const lds = leadsRef.current || [];
    if (cts.length) {
      try {
        const mesh = nv.loadConnectomeAsMesh(buildContactsConnectome(cts, lds));
        mesh.colorbarVisible = false;
        nv.addMesh(mesh);
        markerMeshRef.current = mesh;
      } catch (err) {
        console.warn("contact mesh build failed", err);
      }
    }

    const pending = pendingRef.current;
    if (pending?.coord) {
      try {
        const mesh = nv.loadConnectomeAsMesh(
          buildPreviewConnectome(pending.coord, pending.label)
        );
        mesh.colorbarVisible = false;
        nv.addMesh(mesh);
        previewMeshRef.current = mesh;
      } catch (err) {
        console.warn("preview mesh build failed", err);
      }
    }
    nv.drawScene?.();
  };

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
      // Connectome node names otherwise become a fixed right-side legend.
      showLegend: false,
    });
    nv.addColormap("voxtool-leads", leadColormap());
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
    volumeReadyRef.current = false;
    const url = `${API}/api/scans/${scanFilename}`;
    nv.loadVolumes([
      {
        url,
        colormap: "gray",
        cal_min: calMin,
        cal_max: calMax,
      },
    ]).then(() => {
      nv.setVolumeRenderIllumination(0);
      nv.setRenderAzimuthElevation(120, 10);
      nv.volScaleMultiplier = 1.0;
      nv.setSliceMM(true);
      // Finite thickness so markers only appear near their slice (not hovering).
      nv.setMeshThicknessOn2D(6);
      nv.setClipPlaneThick(0.7);
      if (nv.volumes?.[0]) {
        nv.volumes[0].cal_min = calMin;
        nv.volumes[0].cal_max = calMax;
        nv.updateGLVolume();
      } else {
        nv.drawScene?.();
      }
      volumeReadyRef.current = true;
      // Remount/switch race: contacts may already exist before the volume was ready.
      rebuildMarkers();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanFilename]);

  useEffect(() => {
    const nv = nvRef.current;
    if (!nv) return;
    const sliceType = LAYOUT_TO_SLICETYPE[layout] ?? 3;
    nv.setSliceType(sliceType);
    nv.opts.multiplanarShowRender = layout === "multi" ? 1 : 0;
    nv.drawScene?.();
  }, [layout]);

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
    if (typeof nv.setIsOrientationTextVisible === "function") {
      nv.setIsOrientationTextVisible(!!showRasTags);
    }
    if (typeof nv.setShowAllOrientationMarkers === "function") {
      nv.setShowAllOrientationMarkers(!!showRasTags);
    }
    nv.drawScene?.();
  }, [showRasTags]);

  useEffect(() => {
    rebuildMarkers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contacts, leads, pendingContact]);

  // Pane was hidden with visibility:hidden — force a redraw when shown again.
  useEffect(() => {
    if (!active) return;
    const nv = nvRef.current;
    if (!nv) return;
    requestAnimationFrame(() => {
      nv.resizeListener?.();
      nv.drawScene?.();
    });
  }, [active]);

  return (
    <div className="viewer-container">
      <canvas ref={canvasRef} />
    </div>
  );
}
