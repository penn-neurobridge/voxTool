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

export function leadColorHex(leadName, leads) {
  const i = leads.findIndex((l) => l.name === leadName);
  const idx = i >= 0 ? i : 0;
  return LEAD_PALETTE_HEX[idx % LEAD_PALETTE_HEX.length];
}

/** NiiVue ColorMap: discrete step per lead index (I = 0..N-1). */
export function leadColormap() {
  const R = [];
  const G = [];
  const B = [];
  const A = [];
  const I = [];
  LEAD_PALETTE_HEX.forEach((hex, i) => {
    R.push((hex >> 16) & 0xff);
    G.push((hex >> 8) & 0xff);
    B.push(hex & 0xff);
    A.push(255);
    I.push(i);
  });
  return { R, G, B, A, I };
}
