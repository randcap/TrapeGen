import assert from 'node:assert/strict'
import test from 'node:test'
import { BoxGeometry } from 'three'
import { buildProfile, checkProfile } from '../src/profile.js'
import { prepareSectionMesh, sliceSection } from '../src/section.js'

function box(width, height, depth, x = 0) {
  return new BoxGeometry(width, height, depth).toNonIndexed().translate(x, 0, 0)
    .attributes.position.array
}

function slice(positions, height = 0, scale = 1) {
  return sliceSection(prepareSectionMesh(positions), height, scale)
}

test('maps raw STL units to the same millimeter section', () => {
  assert.deepEqual(slice(box(6, 10, 8), 10, 10), { left: -30, right: 30 })
})

test('a nested hole does not introduce a second exterior contour', () => {
  assert.deepEqual(slice(Float32Array.of(...box(20, 10, 20), ...box(4, 6, 4))),
    { left: -10, right: 10 })
})

test('withholds boundaries for multiple islands, intersections and open sections', () => {
  assert.match(slice(Float32Array.of(...box(20, 20, 20), ...box(20, 20, 20, 30))).message, /2 个独立轮廓/)
  assert.match(slice(Float32Array.of(...box(20, 20, 20), ...box(20, 20, 10, 9))).message, /相交|重叠/)
  assert.match(slice(box(20, 20, 20).subarray(9)).message, /开口/)
  assert.match(slice(box(20, 20, 20), 10).message, /超出/)
})

test('follows the positive-side convention for a plane through triangle edges', () => {
  const geometry = new BoxGeometry(20, 20, 20, 1, 2, 1).toNonIndexed()
  assert.deepEqual(slice(geometry.attributes.position.array), { left: -10, right: 10 })
})

test('uses the red section, symmetric inset and positive upper width', () => {
  const params = { yellow: 69, blue: 87, offset: 7.5, angle: 53, unit: 'cm' }
  assert.equal(checkProfile(params), null)
  const profile = buildProfile(params, { left: -30, right: 30 })
  assert.equal(profile.red, 76.5)
  assert.equal(profile.topLeft + profile.topRight, 0)
  assert.ok(Math.abs(profile.topLeft + 30 - 10.5 / Math.tan(53 * Math.PI / 180)) < 1e-10)
  assert.equal(buildProfile(params, { left: -1, right: 1 }), null)
  assert.match(checkProfile({ ...params, blue: 76 }), /蓝线必须高于/)
})
