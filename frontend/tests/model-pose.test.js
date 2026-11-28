import assert from 'node:assert/strict'
import test from 'node:test'
import { BoxGeometry, Matrix4, Vector3 } from 'three'
import { createModelPose } from '../src/model-pose.js'

function stock() {
  const geometry = new BoxGeometry(8, 5, 4).translate(11, 3, 5)
  geometry.computeBoundingBox()
  return geometry
}

test('Z quarter turn moves the working bounds and sends the pivot translation in mm', () => {
  const original = stock()
  const pose = createModelPose(original.boundingBox)
  pose.rotate('z', 90)
  const rows = pose.toRows(10)
  assert.deepEqual(rows, [[0, -1, 0, 140], [1, 0, 0, -80], [0, 0, 1, 0], [0, 0, 0, 1]])
  const work = original.clone().applyMatrix4(pose.matrix)
  assert.deepEqual(work.boundingBox.min.toArray(), [8.5, -1, 3])
  assert.deepEqual(work.boundingBox.max.toArray(), [13.5, 7, 7])
  assert.deepEqual(original.boundingBox.min.toArray(), [7, 0.5, 3])
  assert.deepEqual(original.boundingBox.max.toArray(), [15, 5.5, 7])

  const vertex = new Vector3().fromBufferAttribute(original.attributes.position, 0)
  const workMm = vertex.clone().applyMatrix4(pose.matrix).multiplyScalar(10)
  const apiMm = vertex.multiplyScalar(10).applyMatrix4(new Matrix4().set(...rows.flat()))
  assert.deepEqual(workMm.toArray(), apiMm.toArray())
  pose.reset()
  assert.equal(pose.isOriginal, true)
  assert.deepEqual(pose.toRows(10), [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
})

test('signed rotations compose about the fixed processing axes', () => {
  const pose = createModelPose(stock().boundingBox)
  const point = new Vector3(12, 5, 8)
  pose.rotate('x', 90)
  assert.deepEqual(point.clone().applyMatrix4(pose.matrix).toArray(), [12, 0, 7])
  pose.rotate('y', 90)
  assert.deepEqual(point.clone().applyMatrix4(pose.matrix).toArray(), [13, 0, 4])
  pose.rotate('y', -90)
  pose.rotate('x', -90)
  assert.equal(pose.isOriginal, true)
})
