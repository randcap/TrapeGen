import * as THREE from 'three'

const planarPoints = ring => ring.map(([x, z]) => new THREE.Vector2(x, -z))

function planarShape(outline, holes = []) {
  const shape = new THREE.Shape(planarPoints(outline))
  for (const hole of holes) shape.holes.push(new THREE.Path(planarPoints(hole)))
  return shape
}

function surfaceGeometry(regions) {
  const boundary = []
  const shapes = regions.map(({ outline_xz_mm: outline, holes_xz_mm: holes }) => {
    for (const ring of [outline, ...holes]) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        boundary.push(ring[j][0], 0, ring[j][1], ring[i][0], 0, ring[i][1])
      }
    }
    return planarShape(outline, holes)
  })
  return [new THREE.ShapeGeometry(shapes).rotateX(-Math.PI / 2),
    new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(boundary, 3))]
}

export function createConnectorPreview() {
  const group = new THREE.Group()
  group.visible = false
  const surface = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({
    color: 0x3b9eda, opacity: 0.24, transparent: true, side: THREE.DoubleSide,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2
  }))
  const border = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({
    color: 0x155888, transparent: true, opacity: 0.8, depthWrite: false, depthTest: false
  }))
  const volume = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({
    transparent: true, opacity: 0.45, side: THREE.DoubleSide, forceSinglePass: true, depthWrite: false
  }))
  const edges = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({
    transparent: true, opacity: 0.9, depthWrite: false
  }))
  surface.renderOrder = 6
  border.renderOrder = 7
  volume.renderOrder = 8
  edges.renderOrder = 9
  group.add(surface, border, volume, edges)
  let previousSurface
  let previousPlacement

  function replace(object, geometry) {
    object.geometry.dispose()
    object.geometry = geometry
  }

  return {
    group,
    update(data, placement, scale) {
      group.visible = !!data
      if (data !== previousSurface) {
        const [face, lines] = data ? surfaceGeometry(data.regions) : [new THREE.BufferGeometry(), new THREE.BufferGeometry()]
        replace(surface, face)
        replace(border, lines)
        previousSurface = data
      }
      const key = placement && JSON.stringify(placement)
      volume.visible = edges.visible = !!placement
      if (key !== previousPlacement) {
        const geometry = placement ? new THREE.ExtrudeGeometry(planarShape(placement.outline), {
          depth: Math.abs(placement.end - placement.start), bevelEnabled: false
        }).rotateX(-Math.PI / 2).translate(0, Math.min(placement.start, placement.end), 0) : new THREE.BufferGeometry()
        replace(volume, geometry)
        replace(edges, placement ? new THREE.EdgesGeometry(geometry) : new THREE.BufferGeometry())
        previousPlacement = key
      }
      if (!data) return
      group.scale.setScalar(1 / scale)
      surface.position.y = border.position.y = data.blue_y_mm
      if (placement) {
        const color = placement.isPost && placement.fits ? 0x007c67 : 0xb33327
        volume.material.color.setHex(color)
        edges.material.color.setHex(color)
        volume.material.depthTest = edges.material.depthTest = placement.isPost
      }
    }
  }
}

function featureWalls({ outline, start, end, isPost }) {
  const y0 = Math.min(start, end)
  const y1 = Math.max(start, end)
  // A post faces outwards, while a hole wall faces into the opening.
  const forward = THREE.ShapeUtils.isClockWise(planarPoints(outline)) === isPost
  const vertices = []
  for (let i = 0; i < outline.length; i++) {
    const [ax, az] = outline[i]
    const [bx, bz] = outline[(i + 1) % outline.length]
    const a0 = [ax, y0, az], a1 = [ax, y1, az]
    const b0 = [bx, y0, bz], b1 = [bx, y1, bz]
    if (forward) vertices.push(...a0, ...a1, ...b1, ...a0, ...b1, ...b0)
    else vertices.push(...a0, ...b1, ...a1, ...a0, ...b0, ...b1)
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
  geometry.computeVertexNormals()
  return geometry
}

export function createConnectorResult(color) {
  const main = new THREE.Group()
  const inset = new THREE.Group()
  main.visible = inset.visible = false
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.8 })

  function sharedMesh() {
    const view = new THREE.Mesh(new THREE.BufferGeometry(), material)
    const thumbnail = new THREE.Mesh(view.geometry, material)
    main.add(view)
    inset.add(thumbnail)
    return geometry => {
      view.geometry.dispose()
      view.geometry = thumbnail.geometry = geometry
    }
  }

  const updateCap = sharedMesh()
  const updateWalls = sharedMesh()
  const updateEnd = sharedMesh()
  let previousSurface
  let previousOpening
  let previousFeature

  return {
    main, inset,
    update(surface, placement, scale, comparing) {
      const valid = !!surface?.regions[placement?.regionIndex] && placement.fits &&
        (placement.isPost ? placement.end > placement.start : placement.end < placement.start)
      main.visible = valid && comparing
      inset.visible = valid
      if (!valid) return false

      main.scale.setScalar(1 / scale)
      inset.scale.setScalar(1 / scale)
      const opening = JSON.stringify([placement.regionIndex, placement.outline])
      if (surface !== previousSurface || opening !== previousOpening) {
        const shapes = surface.regions.map(({ outline_xz_mm: outline, holes_xz_mm: holes }, i) =>
          planarShape(outline, i === placement.regionIndex ? [...holes, placement.outline] : holes))
        // Open the top under the feature so the walls join without another coplanar lid.
        updateCap(new THREE.ShapeGeometry(shapes).rotateX(-Math.PI / 2).translate(0, surface.blue_y_mm, 0))
        previousSurface = surface
        previousOpening = opening
      }
      const feature = JSON.stringify([opening, placement.start, placement.end, placement.isPost])
      if (feature !== previousFeature) {
        updateWalls(featureWalls(placement))
        updateEnd(new THREE.ShapeGeometry(planarShape(placement.outline)).rotateX(-Math.PI / 2)
          .translate(0, placement.end, 0))
        previousFeature = feature
      }
      return true
    }
  }
}
