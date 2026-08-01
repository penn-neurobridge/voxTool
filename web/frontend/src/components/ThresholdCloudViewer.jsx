import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { TrackballControls } from "three/examples/jsm/controls/TrackballControls.js";
import { leadColorHex } from "../leadColors";

const API = process.env.REACT_APP_API_URL || "";

const IS_DESKTOP =
  typeof window !== "undefined" && !!window.voxtoolDesktop?.isDesktop;

/** Both offline routes serve the UI from the backend itself, so relative URLs are
 *  correct and no API URL is needed. Local mode binds loopback only, so a loopback
 *  hostname is a reliable signal — the cloud build is served from CloudFront, where
 *  an empty API URL really would be a misconfiguration worth reporting. */
const SAME_ORIGIN_API =
  typeof window !== "undefined" &&
  ["localhost", "127.0.0.1", "::1", "[::1]"].includes(window.location.hostname);

const LOCAL_UI = IS_DESKTOP || SAME_ORIGIN_API;
const API_READY = !!API || LOCAL_UI;

/**
 * Pick radius (mm). Slightly under legacy lead radius (3) so tip blobs match
 * legacy size a bit better while still filling a round contact highlight.
 */
const PICK_BALL_MM = 2.0;

/**
 * Contact pick from the displayed cloud:
 * - Dense tip (one metal island in the ball): round / half-circle proximity blob.
 * - Close beads with a visible gap: keep the island under the click; only keep
 *   both when the click sits near the mid-gap between islands.
 */
function selectDisplayedContact(pickMap, seedIndex, spacing, radiusMm = PICK_BALL_MM, iterations = 2) {
  if (!pickMap?.length || seedIndex < 0 || seedIndex >= pickMap.length) return null;
  const sx = spacing[0] || 1;
  const sy = spacing[1] || 1;
  const sz = spacing[2] || 1;
  const step = Math.max(sx, sy, sz);
  const r2 = radiusMm * radiusMm;
  const seedV = pickMap[seedIndex];
  let center = seedV.slice();
  let selectedIdx = [seedIndex];

  // Must be < typical bead gap. 2×spacing was bridging the dual-bead gaps.
  const linkMm = step * 1.08;
  const link2 = linkMm * linkMm;

  const indicesInBall = (cx, cy, cz) => {
    const out = [];
    for (let i = 0; i < pickMap.length; i++) {
      const v = pickMap[i];
      const dx = v[0] * sx - cx;
      const dy = v[1] * sy - cy;
      const dz = v[2] * sz - cz;
      if (dx * dx + dy * dy + dz * dz <= r2) out.push(i);
    }
    return out;
  };

  const mmOf = (i) => {
    const v = pickMap[i];
    return [v[0] * sx, v[1] * sy, v[2] * sz];
  };

  const connectedComponents = (indices) => {
    if (!indices.length) return [];
    const set = new Set(indices);
    const mm = new Map();
    for (const i of indices) mm.set(i, mmOf(i));
    const comps = [];
    const seen = new Set();
    for (const start of indices) {
      if (seen.has(start)) continue;
      const comp = [];
      const q = [start];
      seen.add(start);
      while (q.length) {
        const i = q.pop();
        comp.push(i);
        const [ix, iy, iz] = mm.get(i);
        for (const j of indices) {
          if (seen.has(j) || !set.has(j)) continue;
          const [jx, jy, jz] = mm.get(j);
          const dx = ix - jx;
          const dy = iy - jy;
          const dz = iz - jz;
          if (dx * dx + dy * dy + dz * dz <= link2) {
            seen.add(j);
            q.push(j);
          }
        }
      }
      comps.push(comp);
    }
    return comps;
  };

  const compCentroidMm = (comp) => {
    let x = 0;
    let y = 0;
    let z = 0;
    for (const i of comp) {
      const [mx, my, mz] = mmOf(i);
      x += mx;
      y += my;
      z += mz;
    }
    const n = comp.length || 1;
    return [x / n, y / n, z / n];
  };

  const dist2Mm = (a, b) => {
    const dx = a[0] - b[0];
    const dy = a[1] - b[1];
    const dz = a[2] - b[2];
    return dx * dx + dy * dy + dz * dz;
  };

  /**
   * Split dual/multi islands inside the ball.
   * Larger beads: left / mid / right via axis projection + mid-gap.
   * Tiny fragmented contacts: the empty gap can't be clicked, so treat the
   * whole local cluster as one contact unless the click is off past an end.
   */
  const resolveCloseIslands = (indices, preferredSeed) => {
    const comps = connectedComponents(indices);
    if (comps.length <= 1) return indices;

    const clickMm = preferredSeed != null ? mmOf(preferredSeed) : mmOf(indices[0]);
    const ranked = comps
      .map((comp) => ({
        comp,
        cMm: compCentroidMm(comp),
        d2: (() => {
          let best = Infinity;
          for (const i of comp) best = Math.min(best, dist2Mm(mmOf(i), clickMm));
          return best;
        })(),
      }))
      .sort((a, b) => a.d2 - b.d2);

    // Order the two nearest islands left→right along their own axis for t.
    let a = ranked[0];
    let b = ranked[1];
    // Stable axis: sort by centroid x then y then z so t meaning is consistent.
    if (
      b.cMm[0] < a.cMm[0] - 1e-6 ||
      (Math.abs(b.cMm[0] - a.cMm[0]) < 1e-6 && b.cMm[1] < a.cMm[1] - 1e-6) ||
      (Math.abs(b.cMm[0] - a.cMm[0]) < 1e-6 &&
        Math.abs(b.cMm[1] - a.cMm[1]) < 1e-6 &&
        b.cMm[2] < a.cMm[2])
    ) {
      const tmp = a;
      a = b;
      b = tmp;
    }

    const ab = Math.sqrt(dist2Mm(a.cMm, b.cMm)) || 1e-6;
    const axis = [
      (b.cMm[0] - a.cMm[0]) / ab,
      (b.cMm[1] - a.cMm[1]) / ab,
      (b.cMm[2] - a.cMm[2]) / ab,
    ];
    const t =
      ((clickMm[0] - a.cMm[0]) * axis[0] +
        (clickMm[1] - a.cMm[1]) * axis[1] +
        (clickMm[2] - a.cMm[2]) * axis[2]) /
      ab;

    const totalPts = comps.reduce((n, c) => n + c.length, 0);
    const maxIsland = Math.max(...comps.map((c) => c.length));
    // Weird/separated tiny contact: fragments live inside one contact-sized span.
    const smallFragmented =
      ab <= 2.6 && maxIsland <= 14 && totalPts <= 28 && comps.length <= 4;

    if (smallFragmented) {
      // Off past an end → that side only; otherwise take the whole local section.
      if (t < -0.12) return a.comp;
      if (t > 1.12) return b.comp;
      if (t < 0.1) return a.comp;
      if (t > 0.9) return b.comp;
      // Include every nearby island in the ball (not only the nearest two).
      return indices;
    }

    const mid = [
      (a.cMm[0] + b.cMm[0]) * 0.5,
      (a.cMm[1] + b.cMm[1]) * 0.5,
      (a.cMm[2] + b.cMm[2]) * 0.5,
    ];
    const dA = Math.sqrt(dist2Mm(clickMm, a.cMm));
    const dB = Math.sqrt(dist2Mm(clickMm, b.cMm));
    const dMid = Math.sqrt(dist2Mm(clickMm, mid));

    // Larger dual beads: middle zone → both; outer thirds → one side.
    if (t >= 0.32 && t <= 0.68) return indices;
    const nearMid = dMid <= Math.max(step * 0.9, ab * 0.22);
    const balanced = Math.abs(dA - dB) <= step * 0.85;
    if (nearMid && balanced) return indices;

    if (preferredSeed != null) {
      const seedComp = comps.find((c) => c.includes(preferredSeed));
      if (seedComp) return seedComp;
    }

    return dA <= dB ? a.comp : b.comp;
  };

  for (let iter = 0; iter < iterations; iter++) {
    const cx = center[0] * sx;
    const cy = center[1] * sy;
    const cz = center[2] * sz;
    let inBall = indicesInBall(cx, cy, cz);
    if (!inBall.length) {
      selectedIdx = [seedIndex];
      break;
    }
    selectedIdx = resolveCloseIslands(inBall, seedIndex);
    if (!selectedIdx.length) {
      selectedIdx = [seedIndex];
      break;
    }
    let sxSum = 0;
    let sySum = 0;
    let szSum = 0;
    for (const i of selectedIdx) {
      sxSum += pickMap[i][0];
      sySum += pickMap[i][1];
      szSum += pickMap[i][2];
    }
    const n = selectedIdx.length;
    const mean = [sxSum / n, sySum / n, szSum / n];
    const bias = 0.45;
    center = [
      mean[0] * (1 - bias) + seedV[0] * bias,
      mean[1] * (1 - bias) + seedV[1] * bias,
      mean[2] * (1 - bias) + seedV[2] * bias,
    ];
  }

  let inBall = indicesInBall(center[0] * sx, center[1] * sy, center[2] * sz);
  if (!inBall.length) inBall = [seedIndex];
  selectedIdx = resolveCloseIslands(inBall, seedIndex);
  if (!selectedIdx.length) selectedIdx = [seedIndex];

  const voxels = selectedIdx.map((i) => [
    Math.round(pickMap[i][0]),
    Math.round(pickMap[i][1]),
    Math.round(pickMap[i][2]),
  ]);
  const centroid_voxel = [
    Math.round(center[0]),
    Math.round(center[1]),
    Math.round(center[2]),
  ];
  return { voxels, centroid_voxel, count: voxels.length };
}

/** Live pick highlight color — saturated magenta, matching the legacy `spring` tint. */
const PICK_COLOR = 0xff1f7a;

/** Anatomical label colors matching the desktop tool (R/L red, A/P green, S/I blue). */
const ORIENT_RED = 0xff4d4d;
const ORIENT_GREEN = 0x4dd44d;
const ORIENT_BLUE = 0x4d9bff;

/** Colored anatomical label (R/A/S/L/P/I) rendered as a camera-facing sprite. */
function makeTextSprite(text, colorHex) {
  const px = 128;
  const canvas = document.createElement("canvas");
  canvas.width = px;
  canvas.height = px;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, px, px);
  ctx.font = "bold 96px Arial, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#" + colorHex.toString(16).padStart(6, "0");
  ctx.fillText(text, px / 2, px / 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(mat);
  sprite.renderOrder = 999;
  return sprite;
}

export default function ThresholdCloudViewer({
  scanFilename,
  cloudThresholdPct,
  onCloudVoxelPick,
  contacts,
  leads,
  pendingContact,
  selectedLead,
  active = true,
}) {
  const wrapRef = useRef(null);
  const rendererRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const pointsRef = useRef(null);
  const pickIndexToVoxelRef = useRef(null);
  const animationRef = useRef(null);
  const requestRenderRef = useRef(null);
  const activeRef = useRef(active);
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
  const [orientation, setOrientation] = useState(null);

  const pickBusyRef = useRef(false);

  useEffect(() => {
    pickBusyRef.current = pickBusy;
  }, [pickBusy]);

  useEffect(() => {
    if (meta?.thr != null) cloudThrRef.current = meta.thr;
  }, [meta?.thr]);

  const fetchCloud = useCallback(async () => {
    if (!scanFilename) return;
    if (!API_READY) {
      setError(
        "API URL not configured. Rebuild the frontend with REACT_APP_API_URL set to the API CloudFront URL."
      );
      return;
    }
    setComponentVoxels(null);
    setLoading(true);
    setError(null);
    try {
      // Kick volume warm early (fire-and-forget) so rebuilds are fast in RAM.
      fetch(`${API}/api/scans/${scanFilename}/warm_volume`, {
        method: "POST",
        signal: AbortSignal.timeout(10_000),
      }).catch(() => {});

      // Start / fetch cloud cache for this threshold (async on server).
      setError("Preparing cloud preview…");
      await fetch(`${API}/api/scans/${scanFilename}/warm_cloud`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold_pct: cloudThresholdPct }),
        signal: AbortSignal.timeout(30_000),
      }).catch(() => {});

      let cacheReady = false;
      for (let attempt = 0; attempt < 90; attempt++) {
        const readyRes = await fetch(
          `${API}/api/scans/${scanFilename}/cloud_ready?threshold_pct=${cloudThresholdPct}`,
          { signal: AbortSignal.timeout(15_000) }
        ).catch(() => null);
        if (readyRes?.status === 404) {
          throw new Error(
            LOCAL_UI
              ? `${scanFilename} could not be read — it may have been moved or renamed. Open the scan again.`
              : `${scanFilename} was not found on the server. Try Load scan again (S3 should restore it after a redeploy).`
          );
        }
        if (readyRes?.ok) {
          const readyData = await readyRes.json().catch(() => ({}));
          if (readyData.ready) {
            cacheReady = true;
            break;
          }
          setError(
            `Building cloud at ${cloudThresholdPct}%ile… please wait (${attempt + 1})`
          );
        }
        // Also kick threshold_cloud once — if cache missing it returns 202 and starts build.
        if (attempt === 0 || attempt % 5 === 0) {
          fetch(`${API}/api/scans/${scanFilename}/threshold_cloud`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              threshold_pct: cloudThresholdPct,
              max_points: 120000,
              seed: 0,
            }),
            signal: AbortSignal.timeout(20_000),
          }).catch(() => {});
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      if (!cacheReady) {
        throw new Error(
          `Still building the ${cloudThresholdPct}%ile cloud. Wait ~30s and click Refresh cloud — no need to re-upload.`
        );
      }
      setError(null);

      const res = await fetch(`${API}/api/scans/${scanFilename}/threshold_cloud`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          threshold_pct: cloudThresholdPct,
          max_points: 120000,
          seed: 0,
        }),
        signal: AbortSignal.timeout(90_000),
      });
      if (res.status === 202) {
        throw new Error(
          `Cloud at ${cloudThresholdPct}%ile is still building. Click Refresh cloud in a moment.`
        );
      }
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        const msg = errBody.error || errBody.message;
        if (res.status === 404) {
          throw new Error(
            msg ||
              `${scanFilename} not found — open Load scan and select it again.`
          );
        }
        if (res.status === 502 || res.status === 503) {
          throw new Error(
            "API is busy or still deploying — wait a minute, then Refresh cloud."
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
          "Cloud is still building or the request timed out. " +
            "Wait ~30s and click Refresh cloud — you do not need to re-upload."
        );
      } else {
        setError(msg);
      }
      // Keep any existing points on screen instead of wiping to empty on timeout.
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

    // Dimmer than near-white so the cloud reads as background rather than
    // competing with contact markers (which draw in the transparent pass).
    const mat = new THREE.PointsMaterial({
      color: 0x8e9aa8,
      size: Math.max(sx, sy, sz) * 1.5,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.8,
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
      cameraRef.current.position.set(
        center.x + dist * 0.5,
        center.y + dist * 0.4,
        center.z + dist
      );
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
    // A 2x buffer means 4x the fragments for a cloud that can run to six
    // figures of points. 1.5 keeps the edges clean on a Retina panel and cut
    // rotation from a slideshow to usable on an older laptop.
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.setSize(wrap.clientWidth, wrap.clientHeight);
    wrap.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Trackball (not Orbit): free tumble without a locked world-up axis, so
    // electrodes can be spun into whatever view is easiest to annotate.
    const controls = new TrackballControls(camera, renderer.domElement);
    controls.rotateSpeed = 4.0;
    controls.zoomSpeed = 1.2;
    controls.panSpeed = 0.8;
    controls.dynamicDampingFactor = 0.15;
    // keys is [rotate, zoom, pan]. Default 'KeyA'/'KeyS'/'KeyD' collides with
    // the S submit hotkey, and nobody guesses D. Shift-drag pans instead, which
    // is the reflex people bring from the legacy viewer. Right-drag pans too.
    controls.keys = ["", "", "ShiftLeft"];
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

      const spacing = spacingRef.current || [1, 1, 1];
      const local = selectDisplayedContact(pickMap, ix, spacing, PICK_BALL_MM, 2);
      if (!local?.voxels?.length) {
        setError("Could not snap to contact — click directly on a bright voxel.");
        return;
      }

      // Immediate visual parity with legacy: only the connected local cluster.
      setComponentVoxels(local.voxels);
      setError(null);

      if (pickAbortRef.current) pickAbortRef.current.abort();
      const ac = new AbortController();
      pickAbortRef.current = ac;
      const gen = ++pickGenerationRef.current;
      setPickBusy(true);

      (async () => {
        const timeoutId = setTimeout(() => ac.abort(), 30_000);
        try {
          const res = await fetch(`${API}/api/scans/${fname}/voxel_to_mm`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ voxel: local.centroid_voxel }),
            signal: ac.signal,
          });
          const data = await res.json().catch(() => ({}));
          if (gen !== pickGenerationRef.current) return;
          if (!res.ok || !data.mm) {
            throw new Error(data.error || `voxel_to_mm HTTP ${res.status}`);
          }
          onCloudPickRef.current({
            centroid_voxel: local.centroid_voxel,
            centroid_mm: data.mm,
            count: local.count,
            capped: false,
            seed_voxel: pickMap[ix],
          });
        } catch (err) {
          if (err?.name === "AbortError") return;
          console.error("pick voxel_to_mm:", err);
          if (gen !== pickGenerationRef.current) return;
          setError(`Pick failed: ${err.message || err}`);
        } finally {
          clearTimeout(timeoutId);
          if (gen === pickGenerationRef.current) setPickBusy(false);
        }
      })();
    };

    renderer.domElement.addEventListener("click", onCanvasClick);

    // Render on demand. The loop used to repaint the whole cloud 60x a second
    // forever, so the GPU never went idle even with nobody touching the view.
    // controls.update() is cheap and fires "change" whenever the camera moves,
    // which covers rotation and the damping tail.
    let needsRender = true;
    const requestRender = () => {
      needsRender = true;
    };
    requestRenderRef.current = requestRender;
    controls.addEventListener("change", requestRender);

    const loop = () => {
      animationRef.current = requestAnimationFrame(loop);
      // Pause when the pane is hidden so we don't steal input or burn GPU
      // while the user is in Slices mode.
      if (!activeRef.current) return;
      controls.update();
      if (!needsRender) return;
      needsRender = false;
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
      controlsRef.current?.handleResize?.();
      requestRenderRef.current?.();
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
      controls.removeEventListener("change", requestRender);
      requestRenderRef.current = null;
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
      const labels = scene.getObjectByName("orientation-labels");
      if (labels) {
        labels.children.forEach((ch) => {
          if (ch.material?.map) ch.material.map.dispose();
          if (ch.material) ch.material.dispose();
        });
        scene.remove(labels);
      }
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

  // Hidden pane has zero client size for WebGL; refresh when shown again.
  // Also disable TrackballControls so it can't steal window key events.
  useEffect(() => {
    activeRef.current = active;
    const controls = controlsRef.current;
    if (controls) controls.enabled = !!active;
    if (!active) return;
    const wrap = wrapRef.current;
    const renderer = rendererRef.current;
    const camera = cameraRef.current;
    if (!wrap || !renderer || !camera) return;
    requestAnimationFrame(() => {
      const w = wrap.clientWidth;
      const h = Math.max(wrap.clientHeight, 1);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      controlsRef.current?.handleResize?.();
    });
  }, [active]);

  // Anatomical axis directions (R/A/S/L/P/I) for orientation labels.
  useEffect(() => {
    if (!scanFilename || !API_READY) {
      setOrientation(null);
      return;
    }
    let cancelled = false;
    fetch(`${API}/api/scans/${scanFilename}/orientation`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled && d && Array.isArray(d.R)) setOrientation(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [scanFilename]);

  useEffect(() => {
    if (!pendingContact) setComponentVoxels(null);
  }, [pendingContact]);

  // Orientation labels: colored R/A/S/L/P/I sprites at the cloud's extremes.
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const disposeLabels = () => {
      const g = scene.getObjectByName("orientation-labels");
      if (!g) return;
      g.children.forEach((ch) => {
        if (ch.material?.map) ch.material.map.dispose();
        if (ch.material) ch.material.dispose();
      });
      scene.remove(g);
    };
    disposeLabels();

    const pts = pointsRef.current;
    if (!orientation || !pts) return;

    const box = new THREE.Box3().setFromBufferAttribute(pts.geometry.attributes.position);
    const center = new THREE.Vector3();
    box.getCenter(center);
    const radius = box.getSize(new THREE.Vector3()).length() * 0.5;
    if (!Number.isFinite(radius) || radius <= 0) return;
    const off = radius * 1.18;
    const labelScale = Math.max(radius * 0.16, 6);

    const group = new THREE.Group();
    group.name = "orientation-labels";
    const defs = [
      ["R", orientation.R, ORIENT_RED],
      ["L", orientation.L, ORIENT_RED],
      ["A", orientation.A, ORIENT_GREEN],
      ["P", orientation.P, ORIENT_GREEN],
      ["S", orientation.S, ORIENT_BLUE],
      ["I", orientation.I, ORIENT_BLUE],
    ];
    for (const [txt, dir, col] of defs) {
      if (!Array.isArray(dir) || dir.length !== 3) continue;
      const sp = makeTextSprite(txt, col);
      sp.position.set(
        center.x + dir[0] * off,
        center.y + dir[1] * off,
        center.z + dir[2] * off
      );
      sp.scale.set(labelScale, labelScale, 1);
      group.add(sp);
    }
    scene.add(group);

    return disposeLabels;
  }, [orientation, meta]);

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
      color: PICK_COLOR,
      size: Math.max(sx, sy, sz) * 1.35,
      sizeAttenuation: true,
      // See the contact markers below: transparent so it draws after the cloud.
      transparent: true,
      opacity: 1,
    });

    const hi = new THREE.Points(geom, mat);
    hi.renderOrder = 3;
    hi.name = "component-highlight";
    scene.add(hi);
  }, [componentVoxels, meta]);

  // Contact markers: color the bright blob around each submitted contact in its
  // lead color (legacy style). The live pick's blob stays orange via the
  // component-highlight effect. No connecting polyline.
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

    const spacing = meta?.spacing || spacingRef.current || [1, 1, 1];
    const sx = spacing[0] || 1;
    const sy = spacing[1] || 1;
    const sz = spacing[2] || 1;
    const group = new THREE.Group();
    group.name = "contact-markers";

    // Radius (mm) matches legacy lead radius (config.yml D/G = 3).
    const radiusMm = PICK_BALL_MM;

    // Cloud voxel coordinates (i,j,k) available for blob coloring.
    const pickMap = pickIndexToVoxelRef.current;

    // Color only the local connected contact cluster (same logic as live pick).
    const colorBlobFromCloud = (voxel, colorHex, positions, colors) => {
      if (!pickMap || !voxel || voxel.length !== 3) return 0;
      let seedIndex = 0;
      let bestD = Infinity;
      for (let i = 0; i < pickMap.length; i++) {
        const v = pickMap[i];
        const d =
          (v[0] - voxel[0]) ** 2 +
          (v[1] - voxel[1]) ** 2 +
          (v[2] - voxel[2]) ** 2;
        if (d < bestD) {
          bestD = d;
          seedIndex = i;
        }
      }
      const local = selectDisplayedContact(
        pickMap,
        seedIndex,
        [sx, sy, sz],
        radiusMm,
        2
      );
      if (!local?.voxels?.length) return 0;
      const col = new THREE.Color(colorHex);
      for (const v of local.voxels) {
        positions.push(v[0] * sx, v[1] * sy, v[2] * sz);
        colors.push(col.r, col.g, col.b);
      }
      return local.voxels.length;
    };

    // Fallback solid marker when a contact has no nearby cloud voxels (e.g. an
    // interpolated point landing in a sparse region) so it's still visible.
    const addFallbackBlock = (voxel, colorHex) => {
      if (!voxel || voxel.length !== 3) return;
      const geom = new THREE.BoxGeometry(sx * 1.8, sy * 1.8, sz * 1.8);
      const mat = new THREE.MeshBasicMaterial({
        color: colorHex,
        depthTest: true,
        transparent: true,
        opacity: 1,
      });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.position.set(voxel[0] * sx, voxel[1] * sy, voxel[2] * sz);
      mesh.renderOrder = 2;
      group.add(mesh);
    };

    const positions = [];
    const colors = [];
    contacts.forEach((c) => {
      if (!c.voxel) return;
      const hex = leadColorHex(c.lead, leads || []);
      const n = colorBlobFromCloud(c.voxel, hex, positions, colors);
      if (n === 0) addFallbackBlock(c.voxel, hex);
    });

    if (positions.length) {
      const geom = new THREE.BufferGeometry();
      geom.setAttribute(
        "position",
        new THREE.BufferAttribute(new Float32Array(positions), 3)
      );
      geom.setAttribute(
        "color",
        new THREE.BufferAttribute(new Float32Array(colors), 3)
      );
      const mat = new THREE.PointsMaterial({
        // Lowering the percentile can quadruple the grey cloud around a
        // contact, which swamps a marker drawn at cloud size. Slightly larger
        // keeps labelled contacts legible at any threshold.
        size: Math.max(sx, sy, sz) * 1.9,
        sizeAttenuation: true,
        vertexColors: true,
        // Must join the transparent pass to sit above the cloud. Opaque objects
        // all draw before any transparent one, and renderOrder only sorts within
        // a pass — so an opaque contact gets painted over by the 80% grey cloud
        // and keeps a fifth of its colour. Fully opaque, just later in the queue.
        transparent: true,
        opacity: 1,
      });
      const pts = new THREE.Points(geom, mat);
      pts.renderOrder = 2;
      group.add(pts);
    }

    // Live pending pick is drawn by component-highlight (same density as cloud).
    scene.add(group);
  }, [contacts, pendingContact, selectedLead, leads, meta]);

  // Declared last, and deliberately without a dependency array: every effect
  // above that rebuilds scene contents has already run by this point, so one
  // frame is guaranteed after any change. On-demand rendering is only safe
  // while this stays the final effect in the component.
  useEffect(() => {
    requestRenderRef.current?.();
  });

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
          ? "Click a contact → orange, Submit → lead color. Re-submit same # to replace. Drag to rotate · Shift-drag (or right-drag) to pan · scroll to zoom. First click may take ~30s."
          : "Select a lead in the sidebar, then click the cloud. Drag to rotate · Shift-drag to pan · scroll to zoom."}
      </div>
      <div ref={wrapRef} className="cloud-canvas-wrap" />
    </div>
  );
}
