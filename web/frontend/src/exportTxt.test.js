import { buildExportTxt } from "./exportTxt";

const contact = (name, raw) => ({ name, coordinate_spaces: { ct_voxel: { raw } } });

test("matches the lab's electrodes.txt line for a depth lead", () => {
  // Lines copied from a real derivatives/voxtool_ct/electrodes.txt.
  const doc = {
    leads: {
      LA: {
        type: "D",
        dimensions: [1, 10],
        contacts: [contact("LA2", [306, 210, 137]), contact("LA1", [297, 207, 135])],
      },
    },
  };
  expect(buildExportTxt(doc)).toBe("LA1\t297\t207\t135\tD\t10 1\nLA2\t306\t210\t137\tD\t10 1\n");
});

test("keeps a grid's rows and columns as stored", () => {
  const doc = { leads: { G: { type: "G", dimensions: [8, 4], contacts: [contact("G1", [1, 2, 3])] } } };
  expect(buildExportTxt(doc)).toBe("G1\t1\t2\t3\tG\t8 4\n");
});

test("sorts leads case-insensitively and contacts by number", () => {
  const doc = {
    leads: {
      rb: { dimensions: [1, 12], contacts: [contact("rb10", [0, 0, 0]), contact("rb2", [0, 0, 0])] },
      LA: { dimensions: [1, 8], contacts: [contact("LA1", [0, 0, 0])] },
    },
  };
  const names = buildExportTxt(doc).trim().split("\n").map((l) => l.split("\t")[0]);
  expect(names).toEqual(["LA1", "rb2", "rb10"]);
});
