import { prepareSectionMesh, sliceSection } from './section.js'

let mesh
self.onmessage = ({ data }) => {
  if (data.positions) {
    mesh = prepareSectionMesh(data.positions)
    return
  }
  const { key, red, scale } = data
  self.postMessage({ key, ...sliceSection(mesh, red, scale) })
}
