/**
 * Electrode View draws voxel (i, j, k) at (i*sx, j*sy, k*sz). For a scan stored
 * mirror-image to RAS (negative-determinant affine, e.g. LAS) that is a mirror
 * image of the head, so the server sends `flip_x` and x is negated — for the
 * points and the orientation labels alike, or the two would disagree.
 */

/** Per-axis factors that turn a voxel index into a scene coordinate. */
export function sceneScale(spacing, flipX) {
  const s = spacing || [1, 1, 1];
  const sx = s[0] || 1;
  const sy = s[1] || 1;
  const sz = s[2] || 1;
  return [flipX ? -sx : sx, sy, sz];
}

/** A label direction (unit vector from /orientation) in the same scene. */
export function sceneDirection(dir, flipX) {
  return [flipX ? -dir[0] : dir[0], dir[1], dir[2]];
}
