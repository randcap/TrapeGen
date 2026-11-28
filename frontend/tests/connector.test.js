import assert from 'node:assert/strict'
import test from 'node:test'
import { setTimeout as delay } from 'node:timers/promises'
import { parseConnectorSurface, placeConnector, readCustomProfile } from '../src/connector.js'
import { createConnectorSurfaceSession } from '../src/connector-surface.js'

const surface = parseConnectorSurface({
  blue_y_mm: 87, center_xz_mm: [5, -4], regions: [{
    outline_xz_mm: [[-20, -20], [20, -20], [20, 20], [-20, 20]],
    holes_xz_mm: [[[0, 0], [3, 0], [3, 3], [0, 3]]]
  }]
})
const base = { size_mm: 8, depth_mm: 6, angle_deg: 0, offset_xz_mm: [0, 0] }
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} ≠ ${expected}`)

test('uses the same preset dimensions, right-handed rotation and extrusion direction as the API', () => {
  const circle = placeConnector({ ...base, preset: 'circular_post', offset_xz_mm: [2, -1] }, surface)
  assert.deepEqual(circle.center, [7, -5])
  assert.equal(circle.outline.length, 64)
  assert.deepEqual(circle.outline[0], [11, -5])
  assert.equal(circle.end, 93)
  for (const [shape, sides] of [['triangular', 3], ['hexagonal', 6]]) {
    const hole = placeConnector({ ...base, preset: `${shape}_hole`, angle_deg: 90 }, surface)
    assert.equal(hole.outline.length, sides)
    near(hole.outline[0][0], 5)
    assert.ok(hole.outline[0][1] < -4)
    near(Math.hypot(hole.outline[1][0] - hole.outline[0][0], hole.outline[1][1] - hole.outline[0][1]), 8)
    assert.equal(hole.end, 81)
  }
})

test('normalizes concave custom outlines using the area centroid and widest pre-rotation dimension', () => {
  const outline = [[10, 20], [14, 20], [14, 21], [11, 21], [11, 23], [10, 23], [10, 20]]
  const profile = readCustomProfile(JSON.stringify({ profile_xz: outline }))
  assert.deepEqual(profile.points, outline)
  const feature = placeConnector({ ...base, preset: 'custom_hole', angle_deg: 90 }, surface, profile)
  const extent = axis => Math.max(...feature.outline.map(p => p[axis])) - Math.min(...feature.outline.map(p => p[axis]))
  near(extent(0), 6)
  near(extent(1), 8)
  near(feature.outline[0][0], 5 - 8 * (1 / 4) * (6 / 6))
  near(feature.outline[0][1], -4 + 8 * (1 / 4) * (9 / 6))
  assert.throws(() => readCustomProfile('[[0,0],[2,2],[0,2],[2,0]]'), /自交/)
  assert.throws(() => readCustomProfile('[[0,0],[1,0],[1,0]]'), /重复/)
})

test('detects overlap with a real cut-surface hole even when all footprint vertices are in material', () => {
  const centeredOnHole = placeConnector({ ...base, preset: 'circular_post', offset_xz_mm: [-3.5, 5.5] }, surface)
  assert.equal(centeredOnHole.fits, false)
  const away = placeConnector({ ...base, preset: 'circular_post', offset_xz_mm: [0, -5] }, surface)
  assert.equal(away.fits, true)
})

test('ignores an old model response and coalesces rapid cut parameter changes', async () => {
  const calls = []
  const model = {}
  const next = {}
  let notified = 0
  const session = createConnectorSurfaceSession((model, settings) => new Promise(resolve =>
    calls.push({ model, settings, resolve })), () => notified++, 0)
  session.update(model, { blue: 87 })
  await delay(5)
  assert.equal(calls.length, 1)
  session.update(next, { blue: 88 })
  session.update(next, { blue: 89 })
  calls[0].resolve({ center: 'old' })
  await delay(5)
  assert.equal(notified, 0)
  assert.equal(calls.length, 2)
  assert.equal(calls[1].model, next)
  assert.deepEqual(calls[1].settings, { blue: 89 })
  assert.deepEqual(session.update(next, { blue: 89 }), { pending: true })
  calls[1].resolve({ center: 'current' })
  await delay(5)
  assert.equal(notified, 1)
  assert.deepEqual(session.update(next, { blue: 89 }), { surface: { center: 'current' } })
  assert.deepEqual(session.update(null), {})
})
