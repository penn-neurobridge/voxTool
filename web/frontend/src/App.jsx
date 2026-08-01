import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import "./App.css";
import Toolbar from "./components/Toolbar";
import ControlPanel from "./components/ControlPanel";
import NiiVueViewer from "./components/NiiVueViewer";
import ThresholdCloudViewer from "./components/ThresholdCloudViewer";

const API = process.env.REACT_APP_API_URL || "";

/** Electron preload bridge — absent in the browser/cloud build. */
const DESKTOP = typeof window !== "undefined" ? window.voxtoolDesktop : undefined;
const IS_DESKTOP = !!DESKTOP?.isDesktop;

/** Euclidean distance in mm (RAS). */
function distMm(p, q) {
  const dR = p.R - q.R;
  const dA = p.A - q.A;
  const dS = p.S - q.S;
  return Math.sqrt(dR * dR + dA * dA + dS * dS);
}

/** 1-based contact label → legacy lead_loc [row, col]. */
function labelToLeadLoc(label, dimensions) {
  const n = Math.max(1, parseInt(label, 10) || 1) - 1;
  const dx = Math.max(1, dimensions?.[0] || 1);
  const dy = Math.max(1, dimensions?.[1] || 1);
  if (dx === 1) return [Math.min(n, dy - 1), 0];
  if (dy === 1) return [0, Math.min(n, dx - 1)];
  return [Math.floor(n / dx) % dy, n % dx];
}

/**
 * Parse legacy voxel_coordinates.txt (tab-separated name x y z type "dx dy")
 * into the same document shape buildExportDocument emits.
 */
function parseTxtCoordinates(text, scanFilename = "") {
  const leadsOut = {};
  const lines = String(text)
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"));
  if (!lines.length) {
    throw new Error("TXT file is empty.");
  }
  for (const line of lines) {
    const parts = line.split(/\t+/);
    if (parts.length < 4) {
      throw new Error(
        `Bad TXT line (need name + x y z): ${line.slice(0, 80)}`
      );
    }
    const [name, xs, ys, zs, type = "D", dimsStr = "1 8"] = parts;
    const m = String(name).match(/^([A-Za-z]+)(.+)$/);
    if (!m) {
      throw new Error(`Cannot split contact name into lead+label: ${name}`);
    }
    const leadName = m[1];
    const label = m[2];
    // Skip bipolar midpoints like LA1-LA2 for reload (annotation continuity).
    if (String(label).includes("-")) continue;
    const dimsParts = String(dimsStr).trim().split(/\s+/);
    const dimensions = [
      parseInt(dimsParts[0], 10) || 1,
      parseInt(dimsParts[1], 10) || 8,
    ];
    if (!leadsOut[leadName]) {
      leadsOut[leadName] = {
        contacts: [],
        pairs: [],
        n_groups: 1,
        dimensions,
        type: type || "D",
      };
    }
    leadsOut[leadName].contacts.push({
      name: `${leadName}${label}`,
      lead_group: 0,
      lead_loc: labelToLeadLoc(label, dimensions),
      coordinate_spaces: {
        ct_voxel: {
          raw: [
            Math.round(Number(xs)),
            Math.round(Number(ys)),
            Math.round(Number(zs)),
          ],
        },
      },
    });
  }
  if (!Object.keys(leadsOut).length) {
    throw new Error("No contacts found in TXT file.");
  }
  return {
    leads: leadsOut,
    origin_ct: scanFilename || "",
    include_bipolar_pairs: false,
    schema_version: 2,
  };
}

function nextLabelForLead(leadName, contacts) {
  if (!leadName) return "1";
  const used = new Set(
    contacts
      .filter((c) => c.lead === leadName)
      .map((c) => parseInt(c.label, 10))
      .filter((n) => !Number.isNaN(n))
  );
  let n = 1;
  while (used.has(n)) n++;
  return String(n);
}

export default function App() {
  const [scanFilename, setScanFilename] = useState(null);
  const [calMin, setCalMin] = useState(300);
  const [calMax, setCalMax] = useState(1500);
  const [leads, setLeads] = useState([]);
  const [selectedLead, setSelectedLead] = useState("");
  const [contacts, setContacts] = useState([]);
  const [currentCoord, setCurrentCoord] = useState(null);
  const [pendingContact, setPendingContact] = useState(null);
  const [interpolating, setInterpolating] = useState(false);
  const [contactIndexInput, setContactIndexInput] = useState("1");
  const [thresholdPct, setThresholdPct] = useState(99.96);
  const [thresholdInput, setThresholdInput] = useState("99.96");
  const [showRasTags, setShowRasTags] = useState(true);
  const [includeBipolarPairs, setIncludeBipolarPairs] = useState(false);
  const [viewerLayout, setViewerLayout] = useState("multi");
  const [selectedContact, setSelectedContact] = useState(null);
  // NiiVue drag: "contrast" (default) or "pan" to shove the image around.
  const [sliceDrag, setSliceDrag] = useState("contrast");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [showPicker, setShowPicker] = useState(false);
  const [scanList, setScanList] = useState([]);
  const [pickerSelected, setPickerSelected] = useState("");
  const [uploadingScan, setUploadingScan] = useState(false);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerError, setPickerError] = useState("");
  const [thresholdStatus, setThresholdStatus] = useState(null);
  const [saving, setSaving] = useState(false);
  // {tone: 'ok'|'warn'|'err', text: string} — shows under the Interpolate button.
  const [interpStatus, setInterpStatus] = useState(null);
  const [viewerTab, setViewerTab] = useState("slices");
  // True when the backend runs on this machine (desktop app, or the clone-and-run
  // launcher in a browser). Reported by /api/health so the two stay in step.
  const [backendLocal, setBackendLocal] = useState(false);
  const [pathInput, setPathInput] = useState("");

  // Open-in-place needs a backend that can read the disk. Electron adds a native
  // file dialog on top; a plain browser cannot see paths, so it asks for one.
  const localFiles = IS_DESKTOP || backendLocal;

  const nextLabel = useMemo(
    () => nextLabelForLead(selectedLead, contacts),
    [selectedLead, contacts]
  );

  useEffect(() => {
    setContactIndexInput(nextLabel);
  }, [selectedLead, nextLabel]);

  useEffect(() => {
    if (IS_DESKTOP) {
      setBackendLocal(true);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/health`, {
          signal: AbortSignal.timeout(10_000),
        });
        const data = await res.json();
        if (!cancelled) setBackendLocal(!!data.local);
      } catch {
        // Cloud behaviour is the safe default if the probe fails.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);


  const openScanPicker = useCallback(async () => {
    // Open immediately so "Load scan" always shows a reaction (don't wait on network).
    setPickerError("");
    setPickerLoading(true);
    setShowPicker(true);
    try {
      const res = await fetch(`${API}/api/scans/`, {
        signal: AbortSignal.timeout(20_000),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(
          (data && data.error) || `Could not list scans (HTTP ${res.status})`
        );
      }
      const list = Array.isArray(data) ? data : [];
      setScanList(list);
      setPickerSelected((prev) =>
        prev && list.includes(prev) ? prev : list[0] || ""
      );
    } catch (err) {
      console.error("openScanPicker:", err);
      // Keep any previously known list; upload still works even if listing fails.
      setPickerError(
        `Could not refresh the scan list (${err.message || err}). You can still upload below.`
      );
    } finally {
      setPickerLoading(false);
    }
  }, []);

  const confirmScanPick = useCallback(() => {
    if (pickerSelected) {
      setScanFilename(pickerSelected);
    }
    setShowPicker(false);
  }, [pickerSelected]);

  const handleScanDelete = useCallback(
    async (filename) => {
      if (!filename) return;
      const prompt = localFiles
        ? `Close "${filename}"? Your file on disk is not deleted.`
        : `Remove "${filename}" from the server?`;
      if (!window.confirm(prompt)) return;
      try {
        const res = await fetch(
          `${API}/api/scans/${encodeURIComponent(filename)}`,
          { method: "DELETE", signal: AbortSignal.timeout(30_000) }
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
          throw new Error(data.error || `Delete failed (${res.status})`);
        }
        setScanList((prev) => prev.filter((s) => s !== filename));
        if (pickerSelected === filename) setPickerSelected("");
        if (scanFilename === filename) setScanFilename("");
      } catch (err) {
        console.error("handleScanDelete:", err);
        setPickerError(`Could not delete scan: ${err.message || err}`);
      }
    },
    [pickerSelected, scanFilename, localFiles]
  );

  /** Desktop: register a scan by absolute path and read it where it already lives. */
  const openScanAtPath = useCallback(async (absPath) => {
    if (!absPath) return;
    setPickerError("");
    setUploadingScan(true);
    try {
      const res = await fetch(`${API}/api/scans/open_local`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: absPath }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        throw new Error(data.error || `Could not open scan (${res.status})`);
      }
      setScanList((prev) =>
        prev.includes(data.filename) ? prev : [data.filename, ...prev]
      );
      setPickerSelected(data.filename);
      setScanFilename(data.filename);
      setShowPicker(false);
      setThresholdStatus({
        tone: "ok",
        text: `Opened ${data.filename} (${data.size_mb} MB) from ${data.path}`,
      });
    } catch (err) {
      console.error("openScanAtPath:", err);
      setPickerError(`Could not open scan: ${err.message || err}`);
      setShowPicker(true);
    } finally {
      setUploadingScan(false);
    }
  }, []);

  const pickScanFromDisk = useCallback(async () => {
    if (!IS_DESKTOP) return;
    const p = await DESKTOP.pickScan();
    if (p) await openScanAtPath(p);
  }, [openScanAtPath]);

  const handleScanUpload = useCallback(
    async (file) => {
      if (!file) return;
      const lower = file.name.toLowerCase();
      if (!lower.endsWith(".nii") && !lower.endsWith(".nii.gz")) {
        setPickerError("Please choose a .nii or .nii.gz file.");
        return;
      }
      setUploadingScan(true);
      setPickerError("");
      setPickerLoading(false);
      try {
        // Brief health ping only — do not block a multi-minute upload on this.
        await fetch(`${API}/api/health`, {
          signal: AbortSignal.timeout(8_000),
        }).catch(() => {});

        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`${API}/api/scans/upload`, {
          method: "POST",
          body: form,
          signal: AbortSignal.timeout(600_000), // large NIfTI over CloudFront
        });
        let data = {};
        try {
          data = await res.json();
        } catch {
          throw new Error(
            `Upload failed (HTTP ${res.status}). Connection may have dropped — try again.`
          );
        }
        if (!res.ok || !data.success) {
          throw new Error(data.error || `Upload failed (${res.status})`);
        }

        const listRes = await fetch(`${API}/api/scans/`, {
          signal: AbortSignal.timeout(30_000),
        });
        const listRaw = await listRes.json().catch(() => []);
        const list = Array.isArray(listRaw) ? listRaw : [];
        if (!list.includes(data.filename)) {
          list.push(data.filename);
        }
        setScanList(list);
        setPickerSelected(data.filename);
        setScanFilename(data.filename);
        setShowPicker(false);
        setThresholdStatus({
          tone: "ok",
          text: `Uploaded ${data.filename} (${data.size_mb} MB). Open Electrode View when ready.`,
        });
      } catch (err) {
        console.error("handleScanUpload:", err);
        const msg = err?.message || String(err);
        const hint =
          msg.includes("timed out") || err?.name === "TimeoutError"
            ? " Upload timed out — try again (large files can take a few minutes)."
            : " Large files (~80 MB) can take a minute or two.";
        setPickerError(`Upload failed: ${msg}.${hint}`);
      } finally {
        setUploadingScan(false);
      }
    },
    []
  );

  const applyThreshold = useCallback(() => {
    const v = parseFloat(String(thresholdInput).replace(",", "."));
    if (Number.isFinite(v) && v > 0 && v <= 100) {
      setThresholdPct(v);
      setThresholdInput(String(v));
      setThresholdStatus({
        tone: "ok",
        text: scanFilename
          ? `CT threshold set to ${v}. Rebuilding applies on Electrode View.`
          : `CT threshold set to ${v}. Load a scan to use it.`,
      });
    } else {
      setThresholdStatus({
        tone: "err",
        text: "CT threshold must be a percentile between 0 and 100 (e.g. 99.96).",
      });
    }
  }, [thresholdInput, scanFilename]);

  const handleCloudVoxelPick = useCallback(
    async (pick) => {
      if (!scanFilename || !selectedLead || !pick?.centroid_mm || !pick?.centroid_voxel)
        return;
      try {
        const mm = pick.centroid_mm;
        const coord = {
          R: parseFloat(Number(mm[0]).toFixed(1)),
          A: parseFloat(Number(mm[1]).toFixed(1)),
          S: parseFloat(Number(mm[2]).toFixed(1)),
        };
        const n = parseInt(contactIndexInput, 10);
        const label =
          !Number.isNaN(n) && n >= 1 ? String(n) : nextLabelForLead(selectedLead, contacts);
        setCurrentCoord({
          ...coord,
          snapped: true,
          voxelCount: pick.count ?? 1,
        });
        setPendingContact({
          lead: selectedLead,
          label,
          coord,
          voxel: [
            pick.centroid_voxel[0],
            pick.centroid_voxel[1],
            pick.centroid_voxel[2],
          ],
        });
        if (pick.fallback && pick.fallbackReason) {
          console.warn("Cloud pick fallback:", pick.fallbackReason);
        }
        if (pick.capped) {
          console.warn(
            "Bright blob hit max_voxels cap — centroid may be biased; try a higher CT threshold %ile."
          );
        }
      } catch (e) {
        console.error("handleCloudVoxelPick:", e);
      }
    },
    [scanFilename, selectedLead, contactIndexInput, contacts]
  );

  const handleLocationChange = useCallback(
    (coord) => {
      setCurrentCoord(coord);
      if (coord?.snapped && selectedLead) {
        const n = parseInt(contactIndexInput, 10);
        const label =
          !Number.isNaN(n) && n >= 1
            ? String(n)
            : nextLabelForLead(selectedLead, contacts);
        setPendingContact({
          lead: selectedLead,
          label,
          coord: { R: coord.R, A: coord.A, S: coord.S },
          voxel:
            coord.centerVoxel && coord.centerVoxel.length === 3
              ? [...coord.centerVoxel]
              : null,
        });
      }
    },
    [selectedLead, contacts, contactIndexInput]
  );

  const activeLead = useMemo(
    () => leads.find((l) => l.name === selectedLead),
    [leads, selectedLead]
  );

  const commitPending = useCallback(async () => {
    if (!pendingContact || !selectedLead || !scanFilename) return;
    const total =
      (activeLead?.dimensions[0] || 1) * (activeLead?.dimensions[1] || 1);
    const n = parseInt(contactIndexInput, 10);
    const label =
      !Number.isNaN(n) && n >= 1 ? String(n) : pendingContact.label;
    if (Number.isNaN(parseInt(label, 10)) || parseInt(label, 10) < 1) {
      alert("Enter a valid contact index (1 or greater).");
      return;
    }
    const labelNum = parseInt(label, 10);
    if (labelNum > total) {
      alert(
        `Contact index ${labelNum} is beyond this lead (${total} contacts).`
      );
      return;
    }
    const dupIdx = contacts.findIndex(
      (c) => c.lead === selectedLead && c.label === label
    );
    let voxel = pendingContact.voxel;
    if (!voxel || voxel.length !== 3) {
      try {
        const res = await fetch(`${API}/api/scans/${scanFilename}/mm_to_voxel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            point_mm: [
              pendingContact.coord.R,
              pendingContact.coord.A,
              pendingContact.coord.S,
            ],
          }),
        });
        const d = await res.json();
        if (d.voxel) voxel = d.voxel;
      } catch (e) {
        console.error("mm_to_voxel:", e);
      }
    }
    const newContact = {
      lead: selectedLead,
      label,
      coord: { ...pendingContact.coord },
      voxel: voxel && voxel.length === 3 ? [...voxel] : null,
    };
    const updated =
      dupIdx >= 0
        ? contacts.map((c, i) => (i === dupIdx ? newContact : c))
        : [...contacts, newContact];
    setContacts(updated);
    setPendingContact(null);
    setContactIndexInput(
      dupIdx >= 0 ? label : nextLabelForLead(selectedLead, updated)
    );
  }, [
    pendingContact,
    selectedLead,
    contactIndexInput,
    contacts,
    activeLead,
    scanFilename,
  ]);

  const handleDeleteContact = useCallback((idx) => {
    setContacts((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  /**
   * Deleting a lead takes its contacts with it. Leaving them behind orphaned
   * them: their lead was gone, so they fell back to the first palette colour
   * and turned bright green on the scan while still being saved to file.
   */
  const handleDeleteLead = useCallback(
    (name) => {
      const owned = contacts.filter((c) => c.lead === name).length;
      if (
        owned > 0 &&
        !window.confirm(
          `Delete lead ${name} and its ${owned} marked contact${
            owned === 1 ? "" : "s"
          }?\n\nThe markers disappear from both viewers. Other leads keep their colours.`
        )
      ) {
        return;
      }
      const remaining = leads.filter((l) => l.name !== name);
      setLeads(remaining);
      setContacts((prev) => prev.filter((c) => c.lead !== name));
      setSelectedContact((cur) => (cur?.lead === name ? null : cur));
      if (selectedLead === name) {
        setSelectedLead(remaining.length ? remaining[0].name : "");
      }
    },
    [contacts, leads, selectedLead]
  );

  /** Clicking a row in the contact list drives both viewers to that point. */
  const handleSelectContact = useCallback((contact) => {
    if (!contact?.coord) return;
    setSelectedContact(contact);
    setCurrentCoord({ ...contact.coord, snapped: true });
  }, []);

  const cleanScan = useCallback(() => {
    if (contacts.length === 0 && !pendingContact) return;
    if (!window.confirm("Remove all contacts and clear the pending marker?")) {
      return;
    }
    setContacts([]);
    setPendingContact(null);
  }, [contacts.length, pendingContact]);

  const loadFileInputRef = useRef(null);

  /** Build legacy-compatible voxel_coordinates.json document. */
  const buildExportDocument = useCallback(async () => {
    if (!scanFilename) return null;
    const leadsOut = {};
    for (const lead of leads) {
      const dims = lead.dimensions || [1, 8];
      const leadContacts = contacts.filter((c) => c.lead === lead.name);
      const contactEntries = [];
      for (const c of leadContacts) {
        let voxel = c.voxel && c.voxel.length === 3 ? [...c.voxel] : null;
        if (!voxel && c.coord) {
          try {
            const res = await fetch(`${API}/api/scans/${scanFilename}/mm_to_voxel`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                point_mm: [c.coord.R, c.coord.A, c.coord.S],
              }),
            });
            const d = await res.json();
            if (d.voxel) voxel = d.voxel;
          } catch (e) {
            console.error("mm_to_voxel export:", e);
          }
        }
        const entry = {
          name: `${lead.name}${c.label}`,
          lead_group: 0,
          lead_loc: labelToLeadLoc(c.label, dims),
          coordinate_spaces: {
            ct_voxel: {
              raw: voxel
                ? [
                    Math.round(Number(voxel[0])),
                    Math.round(Number(voxel[1])),
                    Math.round(Number(voxel[2])),
                  ]
                : [0, 0, 0],
            },
          },
        };
        if (c.coord) {
          entry.coordinate_spaces.mm = {
            R: c.coord.R,
            A: c.coord.A,
            S: c.coord.S,
          };
        }
        contactEntries.push(entry);
      }
      leadsOut[lead.name] = {
        contacts: contactEntries,
        pairs: [],
        n_groups: 1,
        dimensions: dims,
        type: lead.type || "D",
      };
    }
    return {
      leads: leadsOut,
      origin_ct: scanFilename,
      include_bipolar_pairs: includeBipolarPairs,
      exported_at: new Date().toISOString(),
      schema_version: 2,
    };
  }, [scanFilename, leads, contacts, includeBipolarPairs]);

  /**
   * Legacy voxel_coordinates.txt (tab-separated), matching model/scan.py
   * to_vox_mom: name, x, y, z, type, "dx dy"
   */
  const buildExportTxt = useCallback(
    async (doc) => {
      const lines = [];
      const leadEntries = Object.entries(doc.leads || {}).sort(([a], [b]) =>
        a.toUpperCase().localeCompare(b.toUpperCase())
      );
      for (const [, lead] of leadEntries) {
        const dims = lead.dimensions || [1, 8];
        const type = lead.type || "D";
        const sorted = [...(lead.contacts || [])].sort((a, b) => {
          const na = parseInt(String(a.name).replace(/\D+/g, ""), 10) || 0;
          const nb = parseInt(String(b.name).replace(/\D+/g, ""), 10) || 0;
          return na - nb;
        });
        for (const c of sorted) {
          const v = c.coordinate_spaces?.ct_voxel?.raw || [0, 0, 0];
          lines.push(
            `${c.name}\t${v[0]}\t${v[1]}\t${v[2]}\t${type}\t${dims[0]} ${dims[1]}\n`
          );
        }
      }
      return lines.join("");
    },
    []
  );

  /**
   * Write annotations. When the File System Access API is available the native
   * save dialog lists both JSON and TXT; otherwise we ask once and download.
   */
  const writeAnnotationFile = useCallback(
    async (doc) => {
      const jsonText = JSON.stringify(doc, null, 2);
      const txtText = await buildExportTxt(doc);

      const payloadFor = (format) =>
        format === "txt"
          ? {
              text: txtText,
              mime: "text/plain",
              name: "voxel_coordinates.txt",
              format,
            }
          : {
              text: jsonText,
              mime: "application/json",
              name: "voxel_coordinates.json",
              format,
            };

      const download = (payload) => {
        if (!payload.text || !String(payload.text).trim()) {
          throw new Error("Nothing to write — export produced an empty file.");
        }
        const blob = new Blob([payload.text], { type: payload.mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = payload.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        return payload.format;
      };

      if (typeof window.showSaveFilePicker === "function") {
        try {
          const handle = await window.showSaveFilePicker({
            suggestedName: "voxel_coordinates.json",
            types: [
              {
                description: "JSON (full metadata)",
                accept: { "application/json": [".json"] },
              },
              {
                description: "TXT (legacy tab-separated)",
                accept: { "text/plain": [".txt"] },
              },
            ],
          });
          const fname = (handle.name || "").toLowerCase();
          const format = fname.endsWith(".txt") ? "txt" : "json";
          const payload = payloadFor(format);
          if (!payload.text || !String(payload.text).trim()) {
            throw new Error("Nothing to write — export produced an empty file.");
          }
          const writable = await handle.createWritable();
          // Blob write is more reliable than a raw string across Chromium/Electron.
          await writable.write(new Blob([payload.text], { type: payload.mime }));
          await writable.close();
          return format;
        } catch (err) {
          if (err?.name === "AbortError") return null;
          console.warn("showSaveFilePicker failed, falling back:", err);
        }
      }

      const answer = window.prompt("Save coordinates as json or txt?", "json");
      if (answer == null) return null;
      const v = answer.trim().toLowerCase();
      const format =
        v === "txt" || v === ".txt" || v === "text" || v === "t" ? "txt" : "json";
      return download(payloadFor(format));
    },
    [buildExportTxt]
  );

  /** Save as… — JSON or legacy TXT. */
  const saveAnnotations = useCallback(async () => {
    if (!scanFilename) return;
    if (!leads.length && !contacts.length) {
      alert("Nothing to save yet — add leads/contacts first.");
      return;
    }
    setSaving(true);
    try {
      const doc = await buildExportDocument();
      if (!doc) return;
      const format = await writeAnnotationFile(doc);
      if (format) {
        const nC = contacts.length;
        const nL = leads.length;
        alert(
          `Saved ${nC} contact(s) across ${nL} lead(s) as .${format}.`
        );
      }
    } catch (err) {
      console.error("saveAnnotations:", err);
      alert(`Failed to save: ${err.message || err}`);
    }
    setSaving(false);
  }, [scanFilename, leads, contacts, buildExportDocument, writeAnnotationFile]);

  /** Apply a loaded annotation document (legacy or web formats). */
  const applyAnnotationDocument = useCallback(
    async (raw) => {
      let data = raw;
      if (Array.isArray(data)) {
        if (!data.length) throw new Error("File contains no annotations.");
        data = data[data.length - 1];
      }
      if (!data || typeof data !== "object") {
        throw new Error("Unrecognized annotation file.");
      }

      let newLeads = [];
      let rawContacts = [];

      // Legacy: { leads: { LA: { type, dimensions, contacts: [...] } } }
      if (
        data.leads &&
        !Array.isArray(data.leads) &&
        typeof data.leads === "object"
      ) {
        for (const [name, lead] of Object.entries(data.leads)) {
          newLeads.push({
            name,
            type: lead.type || "D",
            dimensions: lead.dimensions || [1, 8],
          });
          for (const c of lead.contacts || []) {
            let label = c.name || "";
            if (label.startsWith(name)) label = label.slice(name.length);
            if (!label) label = "1";
            const voxelRaw = c.coordinate_spaces?.ct_voxel?.raw;
            const mm = c.coordinate_spaces?.mm;
            rawContacts.push({
              lead: name,
              label: String(label),
              coordinate_spaces: {
                voxel: Array.isArray(voxelRaw) ? voxelRaw : null,
                mm: mm || null,
              },
            });
          }
        }
      } else if (Array.isArray(data.leads) && Array.isArray(data.contacts)) {
        // Web schema
        newLeads = data.leads.map((l) => ({
          name: l.name,
          type: l.type || "D",
          dimensions: l.dimensions || [1, 8],
        }));
        rawContacts = data.contacts;
      } else {
        throw new Error(
          "Unrecognized file. Expected voxel_coordinates.json or .txt."
        );
      }

      const newContacts = [];
      for (const c of rawContacts) {
        const mm = c.coordinate_spaces?.mm;
        let voxel = c.coordinate_spaces?.voxel || c.coordinate_spaces?.ct_voxel?.raw;
        if (Array.isArray(voxel) && voxel.length === 3) {
          voxel = [Number(voxel[0]), Number(voxel[1]), Number(voxel[2])];
        } else {
          voxel = null;
        }
        let coord = null;
        if (mm && mm.R != null && mm.A != null && mm.S != null) {
          coord = { R: mm.R, A: mm.A, S: mm.S };
        }
        if (!voxel && mm && scanFilename) {
          try {
            const res = await fetch(`${API}/api/scans/${scanFilename}/mm_to_voxel`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ point_mm: [mm.R, mm.A, mm.S] }),
            });
            const d = await res.json();
            if (d.voxel) voxel = d.voxel;
          } catch (e) {
            console.error("mm_to_voxel load:", e);
          }
        }
        if (!coord && voxel && scanFilename) {
          try {
            const res = await fetch(`${API}/api/scans/${scanFilename}/voxel_to_mm`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ voxel }),
            });
            const d = await res.json();
            if (d.mm)
              coord = {
                R: parseFloat(d.mm[0].toFixed(1)),
                A: parseFloat(d.mm[1].toFixed(1)),
                S: parseFloat(d.mm[2].toFixed(1)),
              };
          } catch (e) {
            console.error("voxel_to_mm load:", e);
          }
        }
        if (!coord) continue;
        newContacts.push({
          lead: c.lead,
          label: String(c.label),
          coord,
          voxel,
        });
      }

      // Files carry no palette slot, so pin one per lead in file order. Without
      // this, colours would be positional again the moment a lead is deleted.
      newLeads = newLeads.map((l, i) => ({
        ...l,
        colorIndex: Number.isInteger(l.colorIndex) ? l.colorIndex : i,
      }));

      setLeads(newLeads);
      setContacts(newContacts);
      setSelectedContact(null);
      setIncludeBipolarPairs(!!data.include_bipolar_pairs);
      setPendingContact(null);
      if (newLeads.length) {
        setSelectedLead(newLeads[0].name);
      }
      return { nContacts: newContacts.length, nLeads: newLeads.length };
    },
    [scanFilename]
  );

  /** Load coordinates — pick a local JSON or TXT file. */
  const loadAnnotations = useCallback(() => {
    if (!scanFilename) {
      alert("Load a scan first, then open a coordinates JSON or TXT.");
      return;
    }
    if (contacts.length > 0 || leads.length > 0) {
      const ok = window.confirm(
        `This will replace your current ${leads.length} lead(s) and ${contacts.length} contact(s) ` +
          `with the selected file. Continue?`
      );
      if (!ok) return;
    }
    loadFileInputRef.current?.click();
  }, [scanFilename, contacts.length, leads.length]);

  // Native File menu (desktop only) drives the same handlers as the in-app buttons.
  useEffect(() => {
    if (!IS_DESKTOP) return undefined;
    const unsubscribe = [
      DESKTOP.onOpenScan((absPath) => openScanAtPath(absPath)),
      DESKTOP.onSaveCoordinates(() => saveAnnotations()),
      DESKTOP.onLoadCoordinates(() => loadAnnotations()),
    ];
    return () => unsubscribe.forEach((off) => off && off());
  }, [openScanAtPath, saveAnnotations, loadAnnotations]);

  const onAnnotationFileSelected = useCallback(
    async (e) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      try {
        const text = await file.text();
        if (!text || !text.trim()) {
          throw new Error(
            "File is empty. Re-save with Save as… (json or txt) and try again."
          );
        }
        const name = (file.name || "").toLowerCase();
        const looksTxt =
          name.endsWith(".txt") ||
          (!name.endsWith(".json") && /^\S+\t/.test(text.trim()));
        let raw;
        if (looksTxt) {
          raw = parseTxtCoordinates(text, scanFilename);
        } else {
          try {
            raw = JSON.parse(text);
          } catch (parseErr) {
            throw new Error(
              `Invalid JSON (${parseErr.message}). If this was meant to be a ` +
                `legacy .txt, rename it with a .txt extension and try again.`
            );
          }
        }
        const { nContacts, nLeads } = await applyAnnotationDocument(raw);
        if (nContacts === 0) {
          throw new Error(
            "File parsed but no contacts had usable coordinates for this scan."
          );
        }
        alert(
          `Loaded ${nContacts} contact(s) across ${nLeads} lead(s) from ${file.name}.`
        );
      } catch (err) {
        console.error("loadAnnotations failed:", err);
        alert(`Failed to load annotations: ${err.message || err}`);
      }
    },
    [applyAnnotationDocument, scanFilename]
  );


  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case "s":
        case "S":
          e.preventDefault();
          commitPending();
          break;
        case "Escape":
          setPendingContact(null);
          break;
        case "1":
          setViewerLayout("axial");
          break;
        case "2":
          setViewerLayout("coronal");
          break;
        case "3":
          setViewerLayout("sagittal");
          break;
        case "4":
          setViewerLayout("render");
          break;
        case "0":
          setViewerLayout("multi");
          break;
        case "f":
        case "F":
          setSidebarCollapsed((c) => !c);
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [commitPending]);

  useEffect(() => {
    setPendingContact(null);
  }, [selectedLead]);

  const handleInterpolate = useCallback(async () => {
    if (!selectedLead || !scanFilename) return;
    setInterpStatus(null);
    const lead = leads.find((l) => l.name === selectedLead);
    if (!lead) return;
    const total = (lead.dimensions[0] || 1) * (lead.dimensions[1] || 1);

    const leadContacts = contacts
      .filter((c) => c.lead === selectedLead)
      .map((c) => ({ ...c, n: parseInt(c.label, 10) }))
      .filter((c) => !Number.isNaN(c.n))
      .sort((a, b) => a.n - b.n);

    if (leadContacts.length < 2) {
      alert(
        `Mark at least two contacts on ${selectedLead} (the two ends of the span you want filled), then interpolate.`
      );
      return;
    }

    const low = leadContacts[0];
    const high = leadContacts[leadContacts.length - 1];
    const span = high.n - low.n;
    if (span <= 0) {
      alert("Marked contacts need two different label numbers on this lead.");
      return;
    }

    // Common user workflow: click two far-apart physical endpoints but accept auto labels 1 and 2.
    // In that case, extrapolating from a huge 1→2 step will fly off-screen. Detect and offer a fix.
    if (leadContacts.length === 2 && span === 1 && total >= 3) {
      const anchorDist = distMm(low.coord, high.coord);
      if (anchorDist > 12) {
        const ok = window.confirm(
          `These two points are ~${anchorDist.toFixed(
            1
          )} mm apart, which is too far for adjacent contacts (1 & 2).\n\n` +
            `Did you mean them to be contact 1 and contact ${total}?\n` +
            `If you click OK, I'll relabel the second point to ${total} and fill ${2}–${
              total - 1
            } between them.`
        );
        if (ok) {
          // Relabel the "high" contact (currently 2) to N for this lead.
          setContacts((prev) =>
            prev.map((c) => {
              if (c.lead !== selectedLead) return c;
              if (String(c.label) !== String(high.n)) return c;
              return { ...c, label: String(total) };
            })
          );
          alert(
            `Relabeled ${selectedLead}${high.n} → ${selectedLead}${total}. Now click Interpolate again to fill the middle.`
          );
          return;
        }
      }
    }

    const existing = new Set(leadContacts.map((c) => c.n));
    const targets = [];

    // Room *between* label numbers (e.g. 1 and 8 → fill 2–7): uses endpoints only.
    if (span >= 2) {
      const step = {
        R: (high.coord.R - low.coord.R) / span,
        A: (high.coord.A - low.coord.A) / span,
        S: (high.coord.S - low.coord.S) / span,
      };
      for (let n = low.n + 1; n < high.n; n++) {
        if (existing.has(n)) continue;
        const dn = n - low.n;
        targets.push({
          n,
          guess: {
            R: low.coord.R + step.R * dn,
            A: low.coord.A + step.A * dn,
            S: low.coord.S + step.S * dn,
          },
        });
      }
    }

    // Two *consecutive* labels (usually 1 & 2 from back-to-back submits): there is no integer
    // between them, but anatomically the lead continues. Re-use the 1→2 step to place 3…N
    // (and 1…low−1 if needed) along the same line — same idea as calibrating spacing from two contacts.
    if (targets.length === 0 && leadContacts.length === 2 && span === 1) {
      const a = low;
      const b = high;
      const step = {
        R: b.coord.R - a.coord.R,
        A: b.coord.A - a.coord.A,
        S: b.coord.S - a.coord.S,
      };
      for (let n = 1; n < a.n; n++) {
        if (existing.has(n)) continue;
        const dn = n - a.n;
        targets.push({
          n,
          guess: {
            R: a.coord.R + step.R * dn,
            A: a.coord.A + step.A * dn,
            S: a.coord.S + step.S * dn,
          },
        });
      }
      for (let n = b.n + 1; n <= total; n++) {
        if (existing.has(n)) continue;
        const dn = n - a.n;
        targets.push({
          n,
          guess: {
            R: a.coord.R + step.R * dn,
            A: a.coord.A + step.A * dn,
            S: a.coord.S + step.S * dn,
          },
        });
      }
    }

    if (targets.length === 0) {
      if (span >= 2) {
        alert(
          `Every index between ${low.n} and ${high.n} is already marked on ${selectedLead}.`
        );
      } else {
        alert(
          `Nothing to add on ${selectedLead} (${total} contacts). ` +
            `If you meant to bridge two far-apart contacts, set the # field to the real indices ` +
            `(e.g. 1 and 8) before Submit — the app fills *numbers* between labels, not voxel space between 1 and 2.`
        );
      }
      return;
    }

    targets.sort((x, y) => x.n - y.n);

    const leadRadiusMm = { D: 3, G: 3, S: 5 }[lead?.type] ?? 3;
    const existingVoxels = leadContacts
      .map((c) => c.voxel)
      .filter((v) => Array.isArray(v) && v.length === 3);

    setInterpolating(true);
    const newOnes = [];
    let snappedCount = 0;
    let interpFailMsg = null;
    try {
      if (span >= 2) {
        const body = {
          low_label: low.n,
          high_label: high.n,
          labels: targets.map((t) => t.n),
          threshold_pct: thresholdPct,
          lead_type: lead.type,
          existing_voxels: existingVoxels,
        };
        if (low.voxel?.length === 3 && high.voxel?.length === 3) {
          body.start_voxel = low.voxel;
          body.end_voxel = high.voxel;
        } else {
          body.start_mm = [low.coord.R, low.coord.A, low.coord.S];
          body.end_mm = [high.coord.R, high.coord.A, high.coord.S];
        }

        const res = await fetch(`${API}/api/scans/${scanFilename}/interpolate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.success && Array.isArray(data.interior)) {
          for (const item of data.interior) {
            if (!item.mm || item.mm.length !== 3) continue;
            if (item.snapped) snappedCount++;
            newOnes.push({
              lead: selectedLead,
              label: String(item.label),
              coord: {
                R: parseFloat(item.mm[0].toFixed(1)),
                A: parseFloat(item.mm[1].toFixed(1)),
                S: parseFloat(item.mm[2].toFixed(1)),
              },
              voxel: item.voxel?.length === 3 ? [...item.voxel] : null,
            });
          }
        } else {
          interpFailMsg = data.error || data.message || "interpolate failed";
          console.warn("interpolate:", data);
        }
      } else {
        // Consecutive labels (e.g. 1 & 2): extrapolate spacing with legacy snap radius.
        for (const t of targets) {
          const { n, guess } = t;
          let out = { ...guess };
          let voxelOut = null;
          try {
            const res = await fetch(`${API}/api/scans/${scanFilename}/snap`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                point_mm: [guess.R, guess.A, guess.S],
                radius_mm: leadRadiusMm,
                threshold_pct: thresholdPct,
                iterations: 4,
              }),
            });
            const snap = await res.json();
            if (snap.success && (snap.voxel_count ?? 0) > 0) {
              out = {
                R: parseFloat(snap.center_mm[0].toFixed(1)),
                A: parseFloat(snap.center_mm[1].toFixed(1)),
                S: parseFloat(snap.center_mm[2].toFixed(1)),
              };
              snappedCount++;
              if (snap.center_voxel?.length === 3) {
                voxelOut = [...snap.center_voxel];
              }
            }
          } catch {
            /* keep linear guess */
          }
          if (!voxelOut) {
            try {
              const res = await fetch(`${API}/api/scans/${scanFilename}/mm_to_voxel`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ point_mm: [out.R, out.A, out.S] }),
              });
              const d = await res.json();
              if (d.voxel) voxelOut = d.voxel;
            } catch {
              /* optional */
            }
          }
          newOnes.push({
            lead: selectedLead,
            label: String(n),
            coord: out,
            voxel: voxelOut,
          });
        }
      }

      if (newOnes.length > 0) {
        setContacts((prev) => [...prev, ...newOnes]);
        setInterpStatus({
          tone: "ok",
          text:
            `Filled ${newOnes.length} contact${newOnes.length === 1 ? "" : "s"} ` +
            `along straight line (legacy snap, ${leadRadiusMm} mm radius, ` +
            `${snappedCount} snapped to bright voxels).`,
        });
      } else if (interpFailMsg) {
        setInterpStatus({ tone: "err", text: interpFailMsg });
      }
    } finally {
      setInterpolating(false);
    }
  }, [selectedLead, scanFilename, contacts, leads, thresholdPct]);

  return (
    <div className={`app${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      {!sidebarCollapsed && (
        <ControlPanel
          scanLoaded={!!scanFilename}
          scanFilename={scanFilename}
          leads={leads}
          setLeads={setLeads}
          selectedLead={selectedLead}
          setSelectedLead={setSelectedLead}
          contacts={contacts}
          nextLabel={nextLabel}
          contactIndexInput={contactIndexInput}
          setContactIndexInput={setContactIndexInput}
          pendingContact={pendingContact}
          onCommitPending={commitPending}
          onCancelPending={() => setPendingContact(null)}
          onDeleteContact={handleDeleteContact}
          onDeleteLead={handleDeleteLead}
          selectedContact={selectedContact}
          onSelectContact={handleSelectContact}
          onInterpolate={handleInterpolate}
          interpolating={interpolating}
          interpStatus={interpStatus}
          onClearInterpStatus={() => setInterpStatus(null)}
          currentCoord={currentCoord}
          showRasTags={showRasTags}
          setShowRasTags={setShowRasTags}
          includeBipolarPairs={includeBipolarPairs}
          setIncludeBipolarPairs={setIncludeBipolarPairs}
          onLoadScan={openScanPicker}
          onLoadCoordinates={loadAnnotations}
          onSave={saveAnnotations}
          saving={saving}
          onCleanScan={cleanScan}
          loadFileInputRef={loadFileInputRef}
          onAnnotationFileSelected={onAnnotationFileSelected}
        />
      )}

      <div className="viewer-area">
        <div className="viewer-top-bar">
          <div className="viewer-tabs">
            <button
              type="button"
              className={`btn btn-compact ${viewerTab === "slices" ? "btn-primary" : ""}`}
              onClick={() => setViewerTab("slices")}
            >
              Slices (NiiVue)
            </button>
            <button
              type="button"
              className={`btn btn-compact ${viewerTab === "cloud" ? "btn-primary" : ""}`}
              onClick={() => setViewerTab("cloud")}
              disabled={!scanFilename}
              title="3D electrode cloud — easiest mode for annotating contacts"
            >
              Electrode View
            </button>
          </div>
          <div className="ct-threshold-row">
            <span className="ct-threshold-label">CT threshold (%ile)</span>
            <input
              type="text"
              className="ct-threshold-input"
              value={thresholdInput}
              onChange={(e) => setThresholdInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && applyThreshold()}
              title="Percentile for bright-voxel display, snap, cloud pick, and interpolation (default 99.96)"
            />
            <button type="button" className="btn btn-compact" onClick={applyThreshold}>
              Update
            </button>
            {thresholdStatus && (
              <span
                className={`ct-threshold-status ct-threshold-status-${thresholdStatus.tone}`}
                title={thresholdStatus.text}
              >
                {thresholdStatus.text}
              </span>
            )}
          </div>
        </div>

        {viewerTab === "slices" && (
          <Toolbar
            scanFilename={scanFilename}
            calMin={calMin}
            calMax={calMax}
            onWindowChange={(min, max) => {
              setCalMin(min);
              setCalMax(max);
            }}
            viewerLayout={viewerLayout}
            onViewerLayoutChange={setViewerLayout}
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed((c) => !c)}
            dragMode={sliceDrag}
            onDragModeChange={setSliceDrag}
          />
        )}

        {scanFilename ? (
          <div className="viewer-stack">
            <div
              className={`viewer-pane${
                viewerTab === "slices" ? "" : " viewer-pane-hidden"
              }`}
            >
              <NiiVueViewer
                scanFilename={scanFilename}
                calMin={calMin}
                calMax={calMax}
                onLocationChange={handleLocationChange}
                contacts={contacts}
                leads={leads}
                pendingContact={pendingContact}
                layout={viewerLayout}
                snapRadius={3}
                snapThresholdPct={thresholdPct}
                showRasTags={showRasTags}
                active={viewerTab === "slices"}
                dragMode={sliceDrag}
              />
            </div>
            <div
              className={`viewer-pane${
                viewerTab === "cloud" ? "" : " viewer-pane-hidden"
              }`}
            >
              <ThresholdCloudViewer
                scanFilename={scanFilename}
                cloudThresholdPct={thresholdPct}
                onCloudVoxelPick={handleCloudVoxelPick}
                contacts={contacts}
                leads={leads}
                pendingContact={pendingContact}
                selectedLead={selectedLead}
                active={viewerTab === "cloud"}
              />
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <div>
              <p style={{ fontSize: 18, marginBottom: 8 }}>No scan loaded</p>
              <p style={{ marginBottom: 16 }}>
                Upload a NIfTI CT (.nii / .nii.gz) to get started.
              </p>
              <button
                type="button"
                className="btn btn-primary"
                onClick={openScanPicker}
              >
                {localFiles ? "Open scan" : "Load / upload scan"}
              </button>
            </div>
          </div>
        )}

        <div className="status-bar">
          <span>
            {scanFilename ? `Scan: ${scanFilename}` : "No scan loaded"}
          </span>
          <span className="status-bar-right">
            <span className="ras-legend">
              <span className="ras-legend-r">R</span>=Right
              <span className="ras-legend-a">A</span>=Anterior
              <span className="ras-legend-s">S</span>=Superior
            </span>
            <span className="status-hint">
              <kbd>S</kbd> submit · <kbd>Esc</kbd> cancel · <kbd>F</kbd> sidebar
            </span>
            <span>
              {contacts.length} contact{contacts.length !== 1 ? "s" : ""} ·{" "}
              {leads.length} lead{leads.length !== 1 ? "s" : ""}
            </span>
          </span>
        </div>
      </div>

      {showPicker && (
        <div className="modal-overlay" onClick={() => setShowPicker(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Load a CT Scan</h2>
            <p style={{ color: "var(--text-secondary)", marginTop: 0 }}>
              {localFiles
                ? "Choose the NIfTI (.nii / .nii.gz) you want to work on. It is read " +
                  "directly from where it sits on your disk — nothing is copied or uploaded."
                : "Upload the NIfTI (.nii / .nii.gz) you want to work on. AWS accepts " +
                  "files up to ~150 MB."}
            </p>
            {!IS_DESKTOP && backendLocal && (
              // A browser cannot reveal a file's path, so the local server takes one
              // directly. Same endpoint the desktop file dialog calls.
              <form
                style={{ display: "flex", gap: 8, marginBottom: "1rem" }}
                onSubmit={(e) => {
                  e.preventDefault();
                  const p = pathInput.trim();
                  if (p) openScanAtPath(p);
                }}
              >
                <input
                  type="text"
                  style={{ flex: 1 }}
                  placeholder="/full/path/to/scan.nii.gz"
                  value={pathInput}
                  disabled={uploadingScan}
                  onChange={(e) => setPathInput(e.target.value)}
                />
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={uploadingScan || !pathInput.trim()}
                >
                  {uploadingScan ? "Opening…" : "Open"}
                </button>
              </form>
            )}
            <div
              className="modal-actions modal-actions-scan"
              style={{ marginBottom: "1rem" }}
            >
              {IS_DESKTOP ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={uploadingScan}
                  onClick={pickScanFromDisk}
                >
                  {uploadingScan ? "Opening…" : "Open scan from disk…"}
                </button>
              ) : (
                <label
                  className="btn btn-primary"
                  style={{ cursor: uploadingScan ? "wait" : "pointer" }}
                >
                  {uploadingScan
                    ? backendLocal
                      ? "Copying…"
                      : "Uploading…"
                    : backendLocal
                    ? "Or copy a file in…"
                    : "Upload .nii / .nii.gz"}
                  <input
                    type="file"
                    accept=".nii,.gz,application/gzip"
                    style={{ display: "none" }}
                    disabled={uploadingScan}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) handleScanUpload(f);
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
            </div>
            {pickerError && (
              <p style={{ color: "#f07178", fontSize: "0.9rem" }}>{pickerError}</p>
            )}
            {pickerLoading ? (
              <p style={{ color: "var(--text-secondary)" }}>Loading scan list…</p>
            ) : scanList.length === 0 ? (
              <p style={{ color: "var(--text-secondary)" }}>
                {localFiles
                  ? "No scans opened yet."
                  : "No scans uploaded on this server yet."}
              </p>
            ) : (
              <>
                <p
                  style={{
                    color: "var(--text-secondary)",
                    fontSize: "0.9rem",
                    marginBottom: "0.5rem",
                  }}
                >
                  {localFiles
                    ? "Recently opened (click to select, × to close):"
                    : "Already on this server (click to select, × to remove):"}
                </p>
                <ul className="scan-list">
                  {scanList.map((s) => (
                    <li
                      key={s}
                      className={s === pickerSelected ? "selected" : ""}
                      onClick={() => setPickerSelected(s)}
                      onDoubleClick={() => {
                        setPickerSelected(s);
                        setScanFilename(s);
                        setShowPicker(false);
                      }}
                    >
                      <span style={{ flex: 1 }}>{s}</span>
                      <button
                        type="button"
                        className="btn"
                        title={`Remove ${s}`}
                        style={{
                          padding: "0.15rem 0.45rem",
                          marginLeft: "0.5rem",
                          lineHeight: 1,
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleScanDelete(s);
                        }}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <div className="modal-actions modal-actions-scan">
              <button className="btn" onClick={() => setShowPicker(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={confirmScanPick}
                disabled={!pickerSelected || uploadingScan}
              >
                Load selected
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
