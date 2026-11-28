import * as THREE from 'three'
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { validAbRange } from './profile.js'

const accent = 0x00877c

function makeMarker(letter) {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 96
  const context = canvas.getContext('2d')
  context.font = 'bold 39px sans-serif'
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  context.fillStyle = '#006a61'
  context.beginPath()
  context.arc(48, 33, 27, 0, 2 * Math.PI)
  context.fill()
  context.fillStyle = '#fff'
  context.fillText(letter, 48, 35)
  context.fillStyle = '#006a61'
  context.beginPath()
  context.arc(48, 73, 8, 0, 2 * Math.PI)
  context.fill()
  context.strokeStyle = '#fff'
  context.lineWidth = 3
  context.stroke()
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: texture, depthTest: false, depthWrite: false, toneMapped: false
  }))
  sprite.center.set(0.5, 1 - 73 / 96)
  sprite.renderOrder = 10
  return sprite
}

export function createSearchBand() {
  const group = new THREE.Group()
  group.visible = false
  const rectangle = new THREE.Mesh(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({
      color: accent, side: THREE.DoubleSide, transparent: true, opacity: 0.16,
      depthTest: false, depthWrite: false
    }))
  rectangle.renderOrder = 2
  const boundary = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-0.5, 0, -0.5), new THREE.Vector3(0.5, 0, -0.5),
      new THREE.Vector3(0.5, 0, 0.5), new THREE.Vector3(-0.5, 0, 0.5)
    ]),
    new THREE.LineBasicMaterial({ color: accent, depthTest: false, depthWrite: false, transparent: true, opacity: 0.75 })
  )
  boundary.renderOrder = 3
  const outline = new THREE.LineLoop(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({
    color: 0x526c67, depthTest: false, depthWrite: false, transparent: true, opacity: 0.72
  }))
  outline.renderOrder = 4
  const eligible = new LineSegments2(new LineSegmentsGeometry(), new LineMaterial({
    color: accent, linewidth: 2.5, depthTest: false, depthWrite: false, transparent: true
  }))
  eligible.renderOrder = 5
  const a = makeMarker('A')
  const b = makeMarker('B')
  group.add(rectangle, boundary, outline, eligible, a, b)
  let lastOutline
  let lastSelection
  let lastY
  let lastScale

  const replace = (line, geometry) => {
    line.geometry.dispose()
    line.geometry = geometry
  }

  return {
    group,
    update(bounds, radius, scale, red, range, contour, selection, visible) {
      group.visible = visible && !!bounds && Number.isFinite(red) && validAbRange(range)
      if (!group.visible) return
      const y = red / scale
      const z0 = range[0] / scale
      const z1 = range[1] / scale
      for (const strip of [rectangle, boundary]) {
        strip.position.set((bounds.min.x + bounds.max.x) / 2, y, (z0 + z1) / 2)
        strip.scale.set(bounds.max.x - bounds.min.x + radius * 0.1, 1, z1 - z0)
      }

      const changedFrame = y !== lastY || scale !== lastScale
      outline.visible = !!contour
      if (contour && (contour !== lastOutline || changedFrame)) {
        const vertices = []
        for (let i = 0; i < contour.length; i += 2) {
          vertices.push(new THREE.Vector3(contour[i] / scale, y, contour[i + 1] / scale))
        }
        replace(outline, new THREE.BufferGeometry().setFromPoints(vertices))
      }
      eligible.visible = !!selection?.segments?.length
      if (eligible.visible && (selection !== lastSelection || changedFrame)) {
        const values = selection.segments
        const positions = new Float32Array(values.length * 1.5)
        for (let i = 0, j = 0; i < values.length; i += 2, j += 3) {
          positions[j] = values[i] / scale
          positions[j + 1] = y
          positions[j + 2] = values[i + 1] / scale
        }
        replace(eligible, new LineSegmentsGeometry().setPositions(positions))
      }
      for (const [marker, point] of [[a, selection?.a], [b, selection?.b]]) {
        marker.visible = !!point
        if (point) {
          marker.position.set(point.x / scale, y, point.z / scale)
          marker.scale.setScalar(radius * 0.15)
        }
      }
      lastOutline = contour
      lastSelection = selection
      lastY = y
      lastScale = scale
    }
  }
}
