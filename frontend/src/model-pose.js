import { Matrix4, Quaternion, Vector3, MathUtils } from 'three'

const axes = { x: new Vector3(1, 0, 0), y: new Vector3(0, 1, 0), z: new Vector3(0, 0, 1) }
const identity = new Matrix4()

export function createModelPose(bounds) {
  const pivot = bounds.getCenter(new Vector3())
  const rotation = new Quaternion()
  const matrix = new Matrix4()

  return {
    get matrix() { return matrix },
    get isOriginal() { return matrix.equals(identity) },

    rotate(axis, degrees) {
      const turn = new Quaternion().setFromAxisAngle(axes[axis], MathUtils.degToRad(degrees % 360))
      rotation.premultiply(turn).normalize()
      matrix.makeRotationFromQuaternion(rotation)
      // Keep principal-axis quarter turns exact on the STL vertices.
      for (let i = 0; i < 12; i++) {
        const value = matrix.elements[i]
        const nearest = Math.round(value)
        if (Math.abs(value - nearest) < 1e-15) matrix.elements[i] = nearest || 0
      }
      matrix.setPosition(pivot.clone().sub(pivot.clone().applyMatrix4(matrix)))
    },

    reset() {
      rotation.identity()
      matrix.identity()
    },

    toRows(scale) {
      // The working mesh uses STL units, while the API applies the pose after scaling to mm.
      const e = matrix.elements
      return [
        [e[0], e[4], e[8], e[12] * scale],
        [e[1], e[5], e[9], e[13] * scale],
        [e[2], e[6], e[10], e[14] * scale],
        [0, 0, 0, 1]
      ]
    }
  }
}
