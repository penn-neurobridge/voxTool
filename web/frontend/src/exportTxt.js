/**
 * Legacy voxel_coordinates.txt / the lab's electrodes.txt: tab-separated, no
 * header, one contact per line — name, x, y, z (CT voxels), type, "dx dy".
 * Leads sort case-insensitively, contacts by number, as model/scan.py
 * to_vox_mom writes them.
 *
 * This app stores a depth lead as [1, N]; the lab's files write it "N 1".
 * Both say N contacts, but downstream readers see the file, so it follows the
 * lab. parseTxtCoordinates reads either order back.
 */
export function buildExportTxt(doc) {
  const lines = [];
  const leadEntries = Object.entries(doc.leads || {}).sort(([a], [b]) =>
    a.toUpperCase().localeCompare(b.toUpperCase())
  );
  for (const [, lead] of leadEntries) {
    const dims = lead.dimensions || [1, 8];
    const [dx, dy] = dims[0] === 1 && dims[1] > 1 ? [dims[1], 1] : dims;
    const type = lead.type || "D";
    const sorted = [...(lead.contacts || [])].sort((a, b) => {
      const na = parseInt(String(a.name).replace(/\D+/g, ""), 10) || 0;
      const nb = parseInt(String(b.name).replace(/\D+/g, ""), 10) || 0;
      return na - nb;
    });
    for (const c of sorted) {
      const v = c.coordinate_spaces?.ct_voxel?.raw || [0, 0, 0];
      lines.push(`${c.name}\t${v[0]}\t${v[1]}\t${v[2]}\t${type}\t${dx} ${dy}\n`);
    }
  }
  return lines.join("");
}
