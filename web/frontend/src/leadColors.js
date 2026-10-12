/**
 * Shared lead colors for Electrode View (Three.js) and Slices (NiiVue).
 * Keep these in lockstep so a contact looks the same in both tabs.
 */

export const LEAD_PALETTE_HEX = [
  0x1fb84c, // green
  0x00a896, // teal
  0x0e9bd6, // cyan
  0x3b72e0, // blue
  0x7a5ae0, // indigo
  0xa347d6, // purple
  0xd63b2f, // red
  0xe07b1e, // orange
  0xc9a21a, // gold
  0x8faf1b, // olive
];

/**
 * Palette slot for a new lead: the lowest one no existing lead has claimed.
 * Stored on the lead as `colorIndex` so colours are a property of the lead, not
 * of its position in the array — deleting a lead used to renumber every lead
 * after it and silently repaint their contacts.
 */
export function nextColorIndex(leads) {
  const used = new Set(
    (leads || []).map((l) => l.colorIndex).filter((n) => Number.isInteger(n))
  );
  for (let i = 0; i < LEAD_PALETTE_HEX.length; i++) {
    if (!used.has(i)) return i;
  }
  return used.size % LEAD_PALETTE_HEX.length;
}

export function leadIndex(leadName, leads) {
  const i = (leads || []).findIndex((l) => l.name === leadName);
  if (i < 0) return 0;
  const stored = leads[i].colorIndex;
  return Number.isInteger(stored) ? stored : i;
}

export function leadColorHex(leadName, leads) {
  const idx = leadIndex(leadName, leads) % LEAD_PALETTE_HEX.length;
  return LEAD_PALETTE_HEX[idx];
}

/**
 * NiiVue samples connectome colors from a 256-entry LUT:
 *   lutIndex = round(((colorValue - min) / (max - min)) * 255)
 * So colorValue must be the LUT index itself with min=0, max=255 — NOT the
 * raw lead ordinal. Using ordinals with max=9 made lead 1 land ~28/255 of the
 * way through the palette (yellowish) instead of teal.
 */
export function leadLutIndex(leadIdx) {
  const n = LEAD_PALETTE_HEX.length;
  const i = ((leadIdx % n) + n) % n;
  return Math.round((i / Math.max(1, n - 1)) * 255);
}

/**
 * Flat-banded colormap: each lead owns a solid plateau in the 256 LUT so
 * nearby samples still match Electrode View exactly.
 */
export function leadColormap() {
  const n = LEAD_PALETTE_HEX.length;
  const R = [];
  const G = [];
  const B = [];
  const A = [];
  const I = [];

  for (let i = 0; i < n; i++) {
    const hex = LEAD_PALETTE_HEX[i];
    const r = (hex >> 16) & 0xff;
    const g = (hex >> 8) & 0xff;
    const b = hex & 0xff;
    const start = Math.round((i / Math.max(1, n - 1)) * 255);
    const end =
      i === n - 1
        ? 255
        : Math.max(start, Math.round(((i + 1) / Math.max(1, n - 1)) * 255) - 1);

    // Two identical stops → flat band between start and end.
    R.push(r, r);
    G.push(g, g);
    B.push(b, b);
    A.push(255, 255);
    I.push(start, end);
  }

  // makeLut requires first I === 0 and last I === 255.
  I[0] = 0;
  I[I.length - 1] = 255;
  return { R, G, B, A, I };
}
