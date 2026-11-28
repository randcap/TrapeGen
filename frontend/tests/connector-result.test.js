import assert from 'node:assert/strict'
import test from 'node:test'
import { Raycaster, Vector3 } from 'three'
import { createConnectorResult } from '../src/connector-preview.js'
import { placeConnector } from '../src/connector.js'

const surface = {
  blue_y_mm: 10, center_xz_mm: [0, 0], regions: [{
    outline_xz_mm: [[-20, -20], [20, -20], [20, 20], [-20, 20]],
    holes_xz_mm: [[[8, -4], [13, -4], [13, 4], [8, 4]]]
  }]
}
const options = { size_mm: 4, depth_mm: 6, angle_deg: 23, offset_xz_mm: [0, 0] }

function hit(group, origin, direction) {
  group.updateMatrixWorld(true)
  return new Raycaster(new Vector3(...origin), new Vector3(...direction)).intersectObject(group)[0]
}

const fromAbove = (group, x, z) => hit(group, [x, 30, z], [0, -1, 0])

test('blind hole opens the top and has an inward wall and a floor, alongside original holes', () => {
  const result = createConnectorResult(0xffffff)
  const hole = placeConnector({ ...options, preset: 'hexagonal_hole' }, surface)
  assert.equal(result.update(surface, hole, 1, true), true)
  assert.equal(fromAbove(result.main, 0.1, 0.2).point.y, 4)
  assert.equal(fromAbove(result.main, 15, 0).point.y, 10)
  assert.equal(fromAbove(result.main, 10, 0), undefined)
  const wall = hit(result.main, [0, 7, 0], [1, 0, 0])
  assert.ok(wall.point.x > 0 && wall.face.normal.x < 0)
  assert.equal(fromAbove(result.inset, 0.1, 0.2).point.y, 4)
})

test('post exposes its tip and outer wall, and both views reuse the same meshes', () => {
  const result = createConnectorResult(0xffffff)
  const post = placeConnector({ ...options, preset: 'circular_post' }, surface)
  result.update(surface, post, 10, false)
  assert.equal(result.main.visible, false)
  assert.equal(result.inset.visible, true)
  assert.equal(result.inset.scale.y, 0.1)
  const geometry = result.inset.children[0].geometry

  result.update(surface, { ...post, end: 18 }, 1, true)
  assert.equal(result.main.visible, true)
  assert.equal(fromAbove(result.main, 0.1, 0.2).point.y, 18)
  const wall = hit(result.main, [5, 14, 0], [-1, 0, 0])
  assert.ok(wall.point.x > 0 && wall.face.normal.x > 0)
  assert.equal(result.main.children[0].geometry, geometry)
  assert.deepEqual(result.main.children.map(mesh => mesh.geometry), result.inset.children.map(mesh => mesh.geometry))

  assert.equal(result.update(null, null, 1, true), false)
  assert.equal(result.main.visible, false)
  assert.equal(result.inset.visible, false)
  assert.equal(result.update(surface, { ...post, fits: false }, 1, true), false)
})

test('opens a concave profile in the material region that contains it', () => {
  const stock = { ...surface, regions: [...surface.regions, {
    outline_xz_mm: [[28, -12], [46, -12], [46, 12], [28, 12]], holes_xz_mm: []
  }] }
  const custom = { normalized: [[0, 0], [0.25, 0], [0.25, 0.25], [1, 0.25], [1, 1], [0, 1]] }
  const hole = placeConnector({ ...options, preset: 'custom_hole', size_mm: 8,
    angle_deg: 0, offset_xz_mm: [32, -4] }, stock, custom)
  const result = createConnectorResult(0xffffff)
  assert.equal(result.update(stock, hole, 1, true), true)
  assert.equal(fromAbove(result.main, 32.9, 1.2).point.y, 4)
  assert.equal(fromAbove(result.main, 38, -3).point.y, 10)
  assert.equal(fromAbove(result.main, 0, 0).point.y, 10)
})
