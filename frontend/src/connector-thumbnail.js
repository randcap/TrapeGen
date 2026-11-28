import * as THREE from 'three'
import { placeConnector } from './connector.js'
import { createConnectorResult } from './connector-preview.js'
import { renderThumbnail } from './thumbnail-studio.js'

const surface = {
  blue_y_mm: 0,
  center_xz_mm: [0, 0],
  regions: [{ outline_xz_mm: [[-1, -0.82], [1, -0.82], [1, 0.82], [-1, 0.82]], holes_xz_mm: [] }]
}
const sizes = { circular: 1.16, triangular: 1.38, hexagonal: 0.68, custom: 1.22 }

export function renderConnectorThumbnail(preset, custom) {
  const [shape, kind] = preset.split('_')
  const isPost = kind === 'post'
  const placement = placeConnector({ preset, size_mm: sizes[shape], depth_mm: isPost ? 0.84 : 0.47,
    angle_deg: shape === 'triangular' ? 12 : 0, offset_xz_mm: [0, 0] }, surface, custom)
  const result = createConnectorResult(isPost ? 0x50aa93 : 0x83a997)
  if (!result.update(surface, placement, 1, true)) throw Error('Thumbnail profile does not fit its base')

  const body = new THREE.BoxGeometry(2, 0.62, 1.64).translate(0, -0.31, 0)
  const top = body.groups.find(group => group.materialIndex === 2)
  body.setIndex([...body.index.array.slice(0, top.start), ...body.index.array.slice(top.start + top.count)])
  body.clearGroups()
  const stock = new THREE.Mesh(body, new THREE.MeshStandardMaterial({ color: isPost ? 0x82b8a7 : 0x7c9c8b, roughness: 0.8 }))
  try {
    return renderThumbnail([stock, result.main], new THREE.Vector3(0, isPost ? 0.07 : -0.29, 0),
      1.61, new THREE.Vector3(4.6, 5.8, 5.1))
  } finally {
    const materials = new Set([stock.material])
    body.dispose()
    result.main.traverse(object => {
      if (!object.isMesh) return
      materials.add(object.material)
      object.geometry.dispose()
    })
    for (const material of materials) material.dispose()
  }
}
