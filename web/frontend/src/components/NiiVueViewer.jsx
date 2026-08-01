import { useEffect, useRef, useState } from "react";
import { Niivue } from "@niivue/niivue";
import { leadColormap, leadIndex, leadLutIndex } from "../leadColors";

const API = process.env.REACT_APP_API_URL || "";

function buildContactsConnectome(contacts, leads) {
  const nodes = contacts
    .filter((c) => c.coord)
    .map((c) => ({
      name: `${c.lead}${c.label}`,
      x: c.coord.R,
      y: c.coord.A,
      z: c.coord.S,
      colorValue: leadLutIndex(leadIndex(c.lead, leads)),
      sizeValue: 1,
    }));

  // Nodes only — connectome edge cylinders clip into 2D slices as ugly teal
  // slabs/dashes. Lead connectivity is already clear in Electrode View.
  return {
    name: "contacts",
    nodes,
    edges: [],
    nodeColormap: "voxtool-leads",
    nodeColormapNegative: "voxtool-leads",
    nodeMinColor: 0,
    nodeMaxColor: 255,
    // Modest spheres; large scale + edges caused the "crappy" slab look.
    nodeScale: 1.8,
    edgeColormap: "voxtool-leads",
    edgeColormapNegative: "voxtool-leads",
    edgeMin: 0,
    edgeMax: 255,
    edgeScale: 0,
    legendLineThickness: 0,
  };
}

function buildPreviewConnectome(coord, label) {
  // Orange band in the shared palette (index 7).
  const previewCv = leadLutIndex(7);
  return {
    name: "preview",
    nodes: [
      {
        name: label || "?",
        x: coord.R,
        y: coord.A,
        z: coord.S,
        colorValue: previewCv,
        sizeValue: 1.5,
      },
    ],
    edges: [],
    nodeColormap: "voxtool-leads",
    nodeColormapNegative: "voxtool-leads",
    nodeMinColor: 0,
    nodeMaxColor: 255,
    nodeScale: 2.0,
    edgeColormap: "voxtool-leads",
    edgeColormapNegative: "voxtool-leads",
    edgeMin: 0,
    edgeMax: 255,
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

// Voxel axis stepped through when a single plane fills the viewer.
// Matches NiiVue's own scroll math (axis = 2 - axCorSag).
const SINGLE_PLANE_AXIS = { axial: 2, coronal: 1, sagittal: 0 };
const PLANE_LABEL = { axial: "Axial", coronal: "Coronal", sagittal: "Sagittal" };

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
  dragMode = "contrast",
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

  // Single-plane slice position, mirrored into React so the strip below the
  // canvas can show and drive it. {index, max} are voxel indices on the plane's
  // through-axis; max 0 means "nothing to step through yet".
  const [slice, setSlice] = useState({ index: 0, max: 0 });
  const layoutRef = useRef(layout);
  useEffect(() => {
    layoutRef.current = layout;
  }, [layout]);

  /** Pull the current through-plane voxel index out of NiiVue's crosshair. */
  const readSlice = () => {
    const nv = nvRef.current;
    const axis = SINGLE_PLANE_AXIS[layoutRef.current];
    if (axis === undefined || !nv || !volumeReadyRef.current || !nv.volumes?.length) {
      setSlice((prev) => (prev.max === 0 && prev.index === 0 ? prev : { index: 0, max: 0 }));
      return;
    }
    try {
      const vox = nv.frac2vox(nv.scene.crosshairPos);
      const max = Math.max(0, (nv.volumes[0].dimsRAS?.[axis + 1] ?? 1) - 1);
      const index = Math.min(Math.max(Math.round(vox[axis]), 0), max);
      setSlice((prev) =>
        prev.index === index && prev.max === max ? prev : { index, max }
      );
    } catch (err) {
      /* crosshair not ready yet */
    }
  };

  /** Move `delta` slices along the visible plane. NiiVue clamps at the ends. */
  const stepSlice = (delta) => {
    const nv = nvRef.current;
    const axis = SINGLE_PLANE_AXIS[layoutRef.current];
    if (axis === undefined || !nv || !nv.volumes?.length || !delta) return;
    const xyz = [0, 0, 0];
    xyz[axis] = delta;
    nv.moveCrosshairInVox(xyz[0], xyz[1], xyz[2]);
    readSlice();
  };

  const goToSlice = (target) => {
    const nv = nvRef.current;
    const axis = SINGLE_PLANE_AXIS[layoutRef.current];
    if (axis === undefined || !nv || !nv.volumes?.length) return;
    const current = Math.round(nv.frac2vox(nv.scene.crosshairPos)[axis]);
    stepSlice(Math.round(target) - current);
  };

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
      // Render at the display's true pixel density. Left off, a Retina Mac
      // draws at 1x and upscales, which is what made the slices look soft.
      isHighResolutionCapable: true,
      isAntiAlias: true,
      isOrientCube: true,
      // Breathing room between the 4-up tiles instead of butted edges.
      multiplanarPadPixels: 4,
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
      // Keep the slice strip in step with wheel scrolls and in-plane clicks.
      readSlice();

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
      // Thin slice clipping so markers read as dots, not thick mesh chunks.
      nv.setMeshThicknessOn2D(2.5);
      nv.setClipPlaneThick(0.7);
      // Contacts sit inside the head, so the volume render hides them: draw3D
      // paints meshes once depth-tested, then again unoccluded at this alpha.
      // Without it the 3D tile shows the skull but none of the annotations.
      nv.opts.meshXRay = 0.55;
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
      readSlice();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanFilename]);

  useEffect(() => {
    const nv = nvRef.current;
    if (!nv) return;
    const sliceType = LAYOUT_TO_SLICETYPE[layout] ?? 3;
    nv.setSliceType(sliceType);
    // Prefer setter if present — direct opts writes are unreliable across versions.
    if (typeof nv.setMultiplanarShowRender === "function") {
      nv.setMultiplanarShowRender(layout === "multi" ? 1 : 0);
    } else {
      nv.opts.multiplanarShowRender = layout === "multi" ? 1 : 0;
    }
    // 4-up → single pane changes the tile layout; without a resize the backbuffer
    // / mouse coords stay tied to the old grid and scrolling feels "stuck".
    requestAnimationFrame(() => {
      nv.resizeListener?.();
      nv.drawScene?.();
      readSlice();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout]);

  // Single-pane A/C/S can only be scrolled with the wheel: clicking sets the
  // in-plane crosshair, and NiiVue's arrow keys step 4D frames, not slices.
  // Up/Down and PageUp/PageDown give it a keyboard that matches the strip.
  useEffect(() => {
    if (!active || SINGLE_PLANE_AXIS[layout] === undefined) return undefined;
    const onKey = (e) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      let delta = 0;
      if (e.key === "ArrowUp" || e.key === "PageUp") delta = 1;
      else if (e.key === "ArrowDown" || e.key === "PageDown") delta = -1;
      else return;
      e.preventDefault();
      stepSlice(delta);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, layout]);

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

  // NiiVue DRAG_MODE: 1 = contrast (default), 3 = pan/zoom. In pan mode the
  // wheel zooms instead of stepping slices, which is why the slice strip stays
  // the reliable way to move through the stack.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv) return;
    nv.opts.dragMode = dragMode === "pan" ? 3 : 1;
    nv.drawScene?.();
  }, [dragMode]);

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

  const planeLabel = PLANE_LABEL[layout];

  return (
    <>
      {planeLabel && slice.max > 0 && (
        <div className="slice-strip">
          <button
            type="button"
            className="btn btn-compact slice-step"
            onClick={() => stepSlice(-1)}
            title="Previous slice (Down arrow)"
          >
            ‹
          </button>
          <input
            type="range"
            className="slice-range"
            min={0}
            max={slice.max}
            step={1}
            value={slice.index}
            aria-label={`${planeLabel} slice`}
            onChange={(e) => goToSlice(parseInt(e.target.value, 10))}
          />
          <button
            type="button"
            className="btn btn-compact slice-step"
            onClick={() => stepSlice(1)}
            title="Next slice (Up arrow)"
          >
            ›
          </button>
          <span className="slice-readout">
            {planeLabel} slice {slice.index + 1} / {slice.max + 1}
          </span>
          <span className="slice-hint">scroll · ↑/↓ · drag slider</span>
        </div>
      )}
      <div className="viewer-container">
        <canvas ref={canvasRef} />
      </div>
    </>
  );
}
