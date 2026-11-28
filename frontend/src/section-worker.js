import { prepareSectionMesh, sliceSection } from './section.js'

let mesh
self.onmessage = ({ data }) => {
  if (data.positions) {
    mesh = prepareSectionMesh(data.positions)
    return
  }
  const { key, red, scale } = data
  const section = sliceSection(mesh, red, scale)
  self.postMessage({ key, ...section }, section.outline ? [section.outline.buffer] : [])
}
