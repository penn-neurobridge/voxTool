import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";

const API = process.env.REACT_APP_API_URL || "";

/** Saturated palette aligned with NiiVue LEAD_COLORS (RGB → hex). */
const LEAD_PALETTE_HEX = [
  0xff6363, 0x63c7ff, 0xffc763, 0x95ff63, 0xc763ff, 0x63ffc7, 0xff63c7, 0xffff63,
  0x6363ff, 0xff953f,
];

function leadColorHex(leadName, leads) {
  const i = Math.max(0, leads.findIndex((l) => l.name === leadName));
  return LEAD_PALETTE_HEX[i % LEAD_PALETTE_HEX.length];
}

function leadExpectedContactCount(leadName, leadsList) {
  const L = leadsList.find((l) => l.name === leadName);
  if (!L?.dimensions?.length) return 0;
  const dx = L.dimensions[0] || 1;
  const dy = L.dimensions[1] || 1;
  return Math.max(1, dx * dy);
}

/** Numeric order for labels like LA1, LA12 (first integer in string). */
function contactLabelSortKey(label) {
  if (label == null) return NaN;
  const m = String(label).match(/\d+/);
  return m ? parseInt(m[0], 10) : NaN;
}

/** Pick radius (mm) — matches legacy depth lead radius in config.yml. */
const PICK_BALL_MM = 3;

export default function ThresholdCloudViewer({
  scanFilename,
  cloudThresholdPct,
  onCloudVoxelPick,
  contacts,
  leads,
  pendingContact,
  selectedLead,
}) {
  const wrapRef = useRef(null);
  const rendererRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const pointsRef = useRef(null);
  const pickIndexToVoxelRef = useRef(null);
  const animationRef = useRef(null);
  const spacingRef = useRef([1, 1, 1]);
  const selectedLeadRef = useRef("");
  const onCloudPickRef = useRef(null);
  const scanFilenameRef = useRef(null);
  const cloudThresholdPctRef = useRef(99.96);
  const cloudThrRef = useRef(null);
  const pickAbortRef = useRef(null);
  const pickGenerationRef = useRef(0);
  /** LineMaterials need `resolution` updates on resize (screen-space linewidth). */
  const fatLineMaterialsRef = useRef([]);

  useEffect(() => {
    scanFilenameRef.current = scanFilename;
  }, [scanFilename]);
  useEffect(() => {
    cloudThresholdPctRef.current = cloudThresholdPct;
  }, [cloudThresholdPct]);
  useEffect(() => {
    selectedLeadRef.current = selectedLead;
  }, [selectedLead]);
  useEffect(() => {
    onCloudPickRef.current = onCloudVoxelPick;
  }, [onCloudVoxelPick]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null);
  const [componentVoxels, setComponentVoxels] = useState(null);
  const [pickBusy, setPickBusy] = useState(false);

  const pickBusyRef = useRef(false);

  useEffect(() => {
    pickBusyRef.current = pickBusy;
  }, [pickBusy]);

  useEffect(() => {
    if (meta?.thr != null) cloudThrRef.current = meta.thr;
  }, [meta?.thr]);

  const fetchCloud = useCallback(async () => {
    if (!scanFilename) return;
    if (!API) {
      setError(
        "API URL not configured. Set REACT_APP_API_URL on Vercel to your Render URL and redeploy."
      );
      return;
    }
    setComponentVoxels(null);
    setLoading(true);
    setError(null);
    try {
      // Wake Render free tier (cold start can take 30–60s).
      await fetch(`${API}/api/health`, { signal: AbortSignal.timeout(90_000) }).catch(
        () => {}
      );

      const listRes = await fetch(`${API}/api/scans/`, {
        signal: AbortSignal.timeout(30_000),
      }).catch(() => null);
      const serverScans = listRes?.ok ? await listRes.json().catch(() => []) : [];
      if (!Array.isArray(serverScans) || !serverScans.includes(scanFilename)) {
        throw new Error(
          `${scanFilename} is not on the Render server. ` +
            "Open Load Scan → Upload again (wait 1–2 min). " +
            "Render wipes files after each redeploy."
        );
      }

      // Install bundled cloud cache if available (instant on Render).
      await fetch(`${API}/api/scans/${scanFilename}/warm_cloud`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold_pct: cloudThresholdPct }),
        signal: AbortSignal.timeout(30_000),
      }).catch(() => {});

      // Preload full CT into RAM on AWS (no-op on Render).
      fetch(`${API}/api/scans/${scanFilename}/warm_volume`, {
        method: "POST",
        signal: AbortSignal.timeout(30_000),
      }).catch(() => {});

      let cacheReady = false;
      for (let attempt = 0; attempt < 12; attempt++) {
        const readyRes = await fetch(
          `${API}/api/scans/${scanFilename}/cloud_ready?threshold_pct=${cloudThresholdPct}`,
          { signal: AbortSignal.timeout(30_000) }
        ).catch(() => null);
        if (readyRes?.ok) {
          const readyData = await readyRes.json().catch(() => ({}));
          if (readyData.error && readyData.error.includes("not found")) {
            throw new Error(
              `${scanFilename} is not on the Render server — re-upload via Load Scan.`
            );
          }
          if (readyData.ready) {
            cacheReady = true;
            break;
          }
        }
        if (attempt === 0) {
          setError("Preparing cloud preview…");
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      setError(null);

      const res = await fetch(`${API}/api/scans/${scanFilename}/threshold_cloud`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          threshold_pct: cloudThresholdPct,
          max_points: 400000,
          seed: 0,
        }),
        signal: AbortSignal.timeout(cacheReady ? 60_000 : 300_000),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        const msg = errBody.error || errBody.message;
        if (res.status === 404) {
          throw new Error(
            msg ||
              `Scan not on server — re-upload ${scanFilename} via Load Scan (Render does not keep files across redeploys).`
          );
        }
        if (res.status === 502 || res.status === 503) {
          throw new Error(
            "API overloaded or still deploying — wait 1–2 minutes, open /api/health, then Refresh cloud. " +
              "First cloud load can take 2–3 minutes on the free tier."
          );
        }
        throw new Error(msg || `threshold_cloud HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data.success && data.error) {
        throw new Error(data.error);
      }
      const sp = data.voxel_spacing_mm || [1, 1, 1];
      spacingRef.current = sp;
      setMeta({
        returned: data.returned ?? 0,
        total: data.total_voxels ?? 0,
        thr: data.intensity_threshold,
        shape: data.shape,
        spacing: sp,
      });
      cloudThrRef.current = data.intensity_threshold;
      rebuildPoints(data.points || [], sp);
      setLoading(false);
    } catch (e) {
      console.error("threshold_cloud:", e);
      const msg = e?.message || String(e);
      if (msg === "Failed to fetch" || e?.name === "TimeoutError") {
        setError(
          "Cloud request timed out or could not reach the API. " +
            "Open https://voxtool-api.onrender.com/api/health in a tab, wait until it responds, " +
            "then click Refresh cloud. Also re-upload the scan if you redeployed Render."
        );
      } else {
        setError(msg);
      }
      rebuildPoints([], spacingRef.current || [1, 1, 1]);
    } finally {
      setLoading(false);
    }
  }, [scanFilename, cloudThresholdPct]);

  const rebuildPoints = (points, spacing) => {
    const scene = sceneRef.current;
    if (!scene) return;
    spacingRef.current = spacing || spacingRef.current;

    if (pointsRef.current) {
      scene.remove(pointsRef.current);
      pointsRef.current.geometry.dispose();
      pointsRef.current.material.dispose();
      pointsRef.current = null;
    }
    pickIndexToVoxelRef.current = null;

    const n = points.length;
    if (n === 0) return;

    const sx = spacing[0] || 1;
    const sy = spacing[1] || 1;
    const sz = spacing[2] || 1;

    const positions = new Float32Array(n * 3);
    const pickMap = new Array(n);
    for (let i = 0; i < n; i++) {
      const [vi, vj, vk] = points[i];
      positions[i * 3] = vi * sx;
      positions[i * 3 + 1] = vj * sy;
      positions[i * 3 + 2] = vk * sz;
      pickMap[i] = [vi, vj, vk];
    }
    pickIndexToVoxelRef.current = pickMap;

    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const mat = new THREE.PointsMaterial({
      color: 0xc8d4e0,
      size: Math.max(sx, sy, sz) * 2.5,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.85,
    });

    const pts = new THREE.Points(geom, mat);
    scene.add(pts);
    pointsRef.current = pts;

    const box = new THREE.Box3().setFromBufferAttribute(geom.attributes.position);
    const center = new THREE.Vector3();
    box.getCenter(center);
    if (cameraRef.current && controlsRef.current) {
      const size = box.getSize(new THREE.Vector3()).length();
      const dist = Math.max(size * 1.2, 50);
      cameraRef.current.position.set(center.x + dist * 0.5, center.y + dist * 0.4, center.z + dist);
      controlsRef.current.target.copy(center);
      controlsRef.current.update();
    }
  };

  // Three.js scene lifecycle
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0a10);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(55, wrap.clientWidth / wrap.clientHeight, 0.1, 100000);
    camera.position.set(200, 150, 250);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(wrap.clientWidth, wrap.clientHeight);
    wrap.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controlsRef.current = controls;

    const ambient = new THREE.AmbientLight(0xffffff, 0.9);
    scene.add(ambient);

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const tmp = new THREE.Vector3();

    const pickBestVoxelIndex = (ptsObj, pickMap) => {
      if (!ptsObj || !pickMap?.length) return null;
      const attr = ptsObj.geometry.attributes.position;
      const spacing = spacingRef.current || [1, 1, 1];
      const sx = spacing[0] || 1;
      const sy = spacing[1] || 1;
      const sz = spacing[2] || 1;
      raycaster.params.Points.threshold = Math.max(sx, sy, sz) * 1.8;
      let hits = raycaster.intersectObject(ptsObj, false);
      if (!hits.length) {
        raycaster.params.Points.threshold = Math.max(sx, sy, sz) * 4;
        hits = raycaster.intersectObject(ptsObj, false);
      }
      if (!hits.length) return null;
      const ray = raycaster.ray;
      let bestIx = hits[0].index;
      let bestD = Infinity;
      const nCheck = Math.min(hits.length, 64);
      const o = ray.origin;
      const dir = ray.direction;
      for (let h = 0; h < nCheck; h++) {
        const ix = hits[h].index;
        if (ix === undefined || ix < 0 || ix >= pickMap.length) continue;
        tmp.fromBufferAttribute(attr, ix);
        let d;
        if (typeof ray.distanceSqToPoint === "function") {
          d = ray.distanceSqToPoint(tmp);
        } else {
          const ox = tmp.x - o.x;
          const oy = tmp.y - o.y;
          const oz = tmp.z - o.z;
          const t = ox * dir.x + oy * dir.y + oz * dir.z;
          const px = o.x + t * dir.x;
          const py = o.y + t * dir.y;
          const pz = o.z + t * dir.z;
          const dx = tmp.x - px;
          const dy = tmp.y - py;
          const dz = tmp.z - pz;
          d = dx * dx + dy * dy + dz * dz;
        }
        if (d < bestD) {
          bestD = d;
          bestIx = ix;
        }
      }
      return bestIx;
    };

    const onCanvasClick = (e) => {
      const ptsObj = pointsRef.current;
      const pickMap = pickIndexToVoxelRef.current;
      if (!ptsObj || !pickMap) return;

      if (!selectedLeadRef.current || !onCloudPickRef.current) return;

      const fname = scanFilenameRef.current;
      if (!fname) return;

      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);

      const ix = pickBestVoxelIndex(ptsObj, pickMap);
      if (ix === null || ix < 0 || ix >= pickMap.length) return;
      const seedVoxel = pickMap[ix];

      if (pickAbortRef.current) pickAbortRef.current.abort();
      const ac = new AbortController();
      pickAbortRef.current = ac;

      const gen = ++pickGenerationRef.current;
      setPickBusy(true);
      setError(null);

      (async () => {
        const timeoutId = setTimeout(() => ac.abort(), 120_000);
        try {
          const body = {
            seed_voxel: seedVoxel,
            threshold_pct: cloudThresholdPctRef.current,
            max_voxels: 12000,
            max_ball_mm: PICK_BALL_MM,
          };
          if (cloudThrRef.current != null) {
            body.intensity_threshold = cloudThrRef.current;
          }

          const res = await fetch(`${API}/api/scans/${fname}/bright_component`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: ac.signal,
          });
          const data = await res.json();
          if (gen !== pickGenerationRef.current) return;

          if (data.success && Array.isArray(data.voxels) && data.centroid_voxel && data.centroid_mm) {
            setComponentVoxels(data.voxels);
            onCloudPickRef.current({
              centroid_voxel: data.centroid_voxel,
              centroid_mm: data.centroid_mm,
              count: data.count ?? data.voxels.length,
              capped: !!data.capped,
              seed_voxel: seedVoxel,
            });
          } else {
            setComponentVoxels(null);
            setError(
              data.error?.includes("not found")
                ? "Scan gone from Render (server restarted). Load Scan → Upload again, then Refresh cloud."
                : data.message ||
                    data.error ||
                    "Could not snap to contact — click directly on a bright voxel."
            );
          }
        } catch (err) {
          if (err?.name === "AbortError") return;
          console.error("bright_component:", err);
          if (gen !== pickGenerationRef.current) return;
          setComponentVoxels(null);
          const msg = err?.message || String(err);
          setError(
            msg === "Failed to fetch"
              ? "Pick could not reach the API (Render may have restarted). Re-upload the scan, Refresh cloud, try again."
              : `Pick failed: ${msg}`
          );
        } finally {
          clearTimeout(timeoutId);
          if (gen === pickGenerationRef.current) setPickBusy(false);
        }
      })();
    };

    renderer.domElement.addEventListener("click", onCanvasClick);

    const loop = () => {
      animationRef.current = requestAnimationFrame(loop);
      controls.update();
      renderer.render(scene, camera);
    };
    loop();

    const ro = new ResizeObserver(() => {
      if (!wrapRef.current || !rendererRef.current || !cameraRef.current) return;
      const w = wrapRef.current.clientWidth;
      const h = wrapRef.current.clientHeight;
      const hh = Math.max(h, 1);
      cameraRef.current.aspect = w / hh;
      cameraRef.current.updateProjectionMatrix();
      rendererRef.current.setSize(w, hh);
      const res = new THREE.Vector2(w, hh);
      fatLineMaterialsRef.current.forEach((m) => {
        if (m?.resolution) {
          m.resolution.copy(res);
          m.needsUpdate = true;
        }
      });
    });
    ro.observe(wrap);

    return () => {
      ro.disconnect();
      if (pickAbortRef.current) pickAbortRef.current.abort();
      renderer.domElement.removeEventListener("click", onCanvasClick);
      cancelAnimationFrame(animationRef.current);
      controls.dispose();
      wrap.removeChild(renderer.domElement);
      renderer.dispose();
      if (pointsRef.current) {
        scene.remove(pointsRef.current);
        pointsRef.current.geometry.dispose();
        pointsRef.current.material.dispose();
        pointsRef.current = null;
      }
      const hi = scene.getObjectByName("component-highlight");
      if (hi) {
        hi.geometry.dispose();
        hi.material.dispose();
        scene.remove(hi);
      }
      const disposeGroupByName = (name) => {
        const g = scene.getObjectByName(name);
        if (!g) return;
        g.children.forEach((ch) => {
          if (ch.geometry) ch.geometry.dispose();
          if (ch.material) ch.material.dispose();
        });
        scene.remove(g);
      };
      disposeGroupByName("contact-markers");
      disposeGroupByName("lead-polylines");
      fatLineMaterialsRef.current = [];
      sceneRef.current = null;
      cameraRef.current = null;
      rendererRef.current = null;
      controlsRef.current = null;
    };
  }, []);

  useEffect(() => {
    fetchCloud();
  }, [fetchCloud]);

  useEffect(() => {
    if (!pendingContact) setComponentVoxels(null);
  }, [pendingContact]);

  // Orange highlight: 26-connected bright blob for current cloud pick
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const old = scene.getObjectByName("component-highlight");
    if (old) {
      old.geometry.dispose();
      old.material.dispose();
      scene.remove(old);
    }

    if (!componentVoxels?.length) return;

    const spacing = meta?.spacing || spacingRef.current || [1, 1, 1];
    const sx = spacing[0] || 1;
    const sy = spacing[1] || 1;
    const sz = spacing[2] || 1;
    const n = componentVoxels.length;
    const positions = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const [vi, vj, vk] = componentVoxels[i];
      positions[i * 3] = vi * sx;
      positions[i * 3 + 1] = vj * sy;
      positions[i * 3 + 2] = vk * sz;
    }

    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const mat = new THREE.PointsMaterial({
      color: 0xff8822,
      size: Math.max(sx, sy, sz) * 2.9,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.92,
    });

    const hi = new THREE.Points(geom, mat);
    hi.name = "component-highlight";
    scene.add(hi);
  }, [componentVoxels, meta]);

  // Contact markers (voxel space) + lead polylines (LA1→LA2→…)
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const disposeGroupByName = (name) => {
      const g = scene.getObjectByName(name);
      if (!g) return;
      g.children.forEach((ch) => {
        if (ch.geometry) ch.geometry.dispose();
        if (ch.material) ch.material.dispose();
      });
      scene.remove(g);
    };
    fatLineMaterialsRef.current = [];
    disposeGroupByName("contact-markers");
    disposeGroupByName("lead-polylines");

    const spacing = meta?.spacing || [1, 1, 1];
    const sx = spacing[0] || 1;
    const sy = spacing[1] || 1;
    const sz = spacing[2] || 1;
    const group = new THREE.Group();
    group.name = "contact-markers";

    const wrapEl = wrapRef.current;
    const resW = wrapEl?.clientWidth || 800;
    const resH = Math.max(wrapEl?.clientHeight || 600, 1);
    const lineResolution = new THREE.Vector2(resW, resH);

    const leadStrength = (leadName) => {
      const expected = leadExpectedContactCount(leadName, leads);
      const marked = contacts.filter((x) => x.lead === leadName).length;
      const complete = expected > 0 && marked >= expected;
      const selected = selectedLead === leadName;
      return { complete, selected, expected, marked };
    };

    const addSphere = (voxel, colorHex, scale = 4, opacity = 1) => {
      if (!voxel || voxel.length !== 3) return;
      const [vi, vj, vk] = voxel;
      const geom = new THREE.SphereGeometry(Math.max(sx, sy, sz) * scale * 0.15, 12, 12);
      const mat = new THREE.MeshBasicMaterial({
        color: colorHex,
        transparent: opacity < 0.999,
        opacity,
        depthTest: true,
      });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.position.set(vi * sx, vj * sy, vk * sz);
      group.add(mesh);
    };

    contacts.forEach((c) => {
      if (!c.voxel) return;
      const hex = leadColorHex(c.lead, leads);
      const { complete, selected } = leadStrength(c.lead);
      const opacity = selected ? 1 : complete ? 0.95 : 0.62;
      const scale = selected ? 3.35 : complete ? 3 : 2.75;
      addSphere(c.voxel, hex, scale, opacity);
    });

    if (pendingContact?.voxel && pendingContact.lead === selectedLead) {
      addSphere(pendingContact.voxel, 0xffdd44, 3.5);
    }

    const lineGroup = new THREE.Group();
    lineGroup.name = "lead-polylines";

    const byLead = new Map();
    contacts.forEach((c) => {
      if (!c.voxel || c.voxel.length !== 3) return;
      const n = contactLabelSortKey(c.label);
      if (!Number.isFinite(n)) return;
      if (!byLead.has(c.lead)) byLead.set(c.lead, []);
      byLead.get(c.lead).push({ c, n });
    });

    const addFatPolyline = (flatXYZ, colorHex, lineWidthPx, opacity) => {
      const lg = new LineGeometry();
      lg.setPositions(flatXYZ);
      const mat = new LineMaterial({
        color: colorHex,
        linewidth: lineWidthPx,
        transparent: true,
        opacity,
        resolution: lineResolution.clone(),
        depthTest: true,
      });
      fatLineMaterialsRef.current.push(mat);
      const line = new Line2(lg, mat);
      line.computeLineDistances();
      lineGroup.add(line);
    };

    for (const [leadName, arr] of byLead) {
      arr.sort((a, b) => a.n - b.n);
      const sorted = arr.map((x) => x.c);
      if (sorted.length < 2) continue;

      const flat = [];
      for (const c of sorted) {
        const [vi, vj, vk] = c.voxel;
        flat.push(vi * sx, vj * sy, vk * sz);
      }

      const { complete, selected } = leadStrength(leadName);
      const hex = leadColorHex(leadName, leads);
      const widthPx = selected ? 5 : complete ? 4 : 3;
      const opacity = selected ? 1 : complete ? 0.94 : 0.72;
      addFatPolyline(flat, hex, widthPx, opacity);

      // Stub from last committed contact on this lead to pending (same lead selected).
      if (
        pendingContact?.voxel?.length === 3 &&
        pendingContact.lead === leadName &&
        selectedLead === leadName
      ) {
        const last = sorted[sorted.length - 1];
        const [vi, vj, vk] = last.voxel;
        const [pi, pj, pk] = pendingContact.voxel;
        addFatPolyline(
          [vi * sx, vj * sy, vk * sz, pi * sx, pj * sy, pk * sz],
          0xffdd44,
          Math.max(3, widthPx - 0.5),
          0.82
        );
      }
    }

    scene.add(lineGroup);
    scene.add(group);
  }, [contacts, pendingContact, selectedLead, leads, meta]);

  return (
    <div className="cloud-viewer-root">
      <div className="cloud-toolbar">
        <span className="cloud-meta">
          {loading
            ? "Loading cloud…"
            : meta
              ? `${meta.returned.toLocaleString()} pts displayed · ${meta.total.toLocaleString()} above threshold · thr=${meta.thr?.toFixed(1) ?? "—"}${pickBusy ? " · snapping…" : ""}`
              : "—"}
        </span>
        <button type="button" className="btn btn-compact" onClick={fetchCloud} disabled={loading}>
          Refresh cloud
        </button>
      </div>
      {error && <div className="cloud-error">{error}</div>}
      <div className="cloud-hint muted">
        {selectedLead
          ? "Click an electrode contact — orange blob + yellow centroid. First click on cloud may take ~30s."
          : "Select a lead in the sidebar, then click the cloud."}
      </div>
      <div ref={wrapRef} className="cloud-canvas-wrap" />
    </div>
  );
}
