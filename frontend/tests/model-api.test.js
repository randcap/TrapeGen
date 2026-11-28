import assert from 'node:assert/strict'
import test from 'node:test'
import { requestClippedModel, requestConnectorSurface } from '../src/model-api.js'

const responseJson = data => new Response(JSON.stringify(data))

test('an expired export retries with the captured entry blob and settings', async t => {
  const original = new Blob(['first STL'])
  const other = new Blob(['second STL'])
  const first = { id: 'model-2', name: 'same.stl', blob: original, uploadId: 'expired' }
  const second = { id: 'model-3', name: 'same.stl', blob: other, uploadId: 'second' }
  const settings = { blue: 87, offset: 8, connector: { preset: 'circular_post' } }
  const calls = []
  t.mock.method(globalThis, 'fetch', async (path, { body }) => {
    calls.push(path === '/api/upload' ? body : JSON.parse(body))
    if (path === '/api/upload') return responseJson({ model: 'fresh' })
    if (JSON.parse(body).model === 'expired') return new Response('模型已过期，请重新上传', { status: 422 })
    return new Response('clipped')
  })
  assert.equal(await (await requestClippedModel(first, settings)).text(), 'clipped')
  assert.deepEqual(calls, [{ model: 'expired', ...settings }, original, { model: 'fresh', ...settings }])
  assert.equal(first.uploadId, 'fresh')
  assert.equal(second.uploadId, 'second')
})

test('a concurrent surface request and export share the pending upload for one entry', async t => {
  const model = { id: 'model-2', blob: new Blob(['model']) }
  const calls = []
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push(path)
    if (path === '/api/upload') return responseJson({ model: 'shared' })
    assert.equal(JSON.parse(options.body).model, 'shared')
    if (path === '/api/clip') return new Response('clipped')
    return responseJson({ blue_y_mm: 10, center_xz_mm: [1, 1], regions: [{
      outline_xz_mm: [[0, 0], [4, 0], [0, 4]], holes_xz_mm: []
    }] })
  })
  await Promise.all([requestConnectorSurface(model, {}), requestClippedModel(model, {})])
  assert.equal(calls.filter(path => path === '/api/upload').length, 1)
  assert.equal(calls.length, 3)
})
