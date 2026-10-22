import { sceneDirection, sceneScale } from "./cloudScene";

const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

test("scales by voxel spacing and mirrors x only when asked", () => {
  expect(sceneScale([0.5, 0.5, 1], false)).toEqual([0.5, 0.5, 1]);
  expect(sceneScale([0.5, 0.5, 1], true)).toEqual([-0.5, 0.5, 1]);
  expect(sceneScale(undefined, false)).toEqual([1, 1, 1]);
  expect(sceneScale([0, 0, 0], true)).toEqual([-1, 1, 1]);
});

test("a mirror-stored scan's labels come out right-handed after the flip", () => {
  // /orientation for an LAS scan with 1 mm voxels: R points down -x.
  const R = [-1, 0, 0];
  const A = [0, 1, 0];
  const S = [0, 0, 1];
  // Unflipped, R × A points away from S: a mirror image of the head.
  expect(dot(cross(R, A), S)).toBeLessThan(0);
  const [r, a, s] = [R, A, S].map((d) => sceneDirection(d, true));
  expect(dot(cross(r, a), s)).toBeGreaterThan(0);
});
