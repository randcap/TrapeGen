import * as THREE from 'three'

const horizontal = (left, right, height, near, far) => [
  new THREE.Vector3(left, height, far),
  new THREE.Vector3(right - left, 0, 0),
  new THREE.Vector3(0, 0, near - far)
]

export function createCutCaps(renderer, color) {
  const surface = new THREE.Group()
  const inset = new THREE.Group()
  const maskScene = new THREE.Scene()
  maskScene.background = new THREE.Color(0x000000)
  const maskCamera = new THREE.OrthographicCamera()
  const clipPlane = new THREE.Plane()
  renderer.localClippingEnabled = true

  // Count both sides of the clipped shell. A nonzero count describes its
  // interior cross section, including nested voids and overlapping shells.
  const winding = (side, operation) => new THREE.Mesh(undefined, new THREE.MeshBasicMaterial({
    side, clippingPlanes: [clipPlane], colorWrite: false, depthWrite: false, depthTest: false,
    stencilWrite: true, stencilZPass: operation
  }))
  const back = winding(THREE.BackSide, THREE.IncrementWrapStencilOp)
  const front = winding(THREE.FrontSide, THREE.DecrementWrapStencilOp)
  const fill = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
    vertexShader: 'void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: 'void main() { gl_FragColor = vec4(1.0); }',
    stencilWrite: true, stencilFunc: THREE.NotEqualStencilFunc, depthTest: false, depthWrite: false
  }))
  fill.frustumCulled = false
  fill.renderOrder = 1
  maskScene.add(back, front, fill)

  const planeGeometry = new THREE.PlaneGeometry(1, 1)
  function createFace(shoulders = false) {
    const target = new THREE.WebGLRenderTarget(1, 1, { stencilBuffer: true })
    const material = new THREE.MeshStandardMaterial({
      color, roughness: 0.8, side: THREE.DoubleSide, alphaMap: target.texture, alphaTest: 0.5
    })
    const range = { value: new THREE.Vector2(0, 1) }
    material.onBeforeCompile = shader => {
      shader.uniforms.capRange = range
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\nuniform vec2 capRange;')
        .replace('#include <alphamap_fragment>', `#include <alphamap_fragment>
          bool betweenSides = vAlphaMapUv.x >= capRange.x && vAlphaMapUv.x <= capRange.y;
          if (${shoulders ? '' : '!'}betweenSides) discard;`)
    }
    material.customProgramCacheKey = () => shoulders ? 'cut-cap-shoulders' : 'cut-cap'
    const mesh = new THREE.Mesh(planeGeometry, material)
    const thumbnail = new THREE.Mesh(planeGeometry, material)
    surface.add(mesh)
    inset.add(thumbnail)
    return { target, mesh, thumbnail, range, key: null }
  }

  const top = createFace()
  const left = createFace()
  const right = createFace()
  const shoulders = createFace(true)
  const u = new THREE.Vector3()
  const v = new THREE.Vector3()
  const normal = new THREE.Vector3()
  const center = new THREE.Vector3()
  const basis = new THREE.Matrix4()

  function prepareFace(face, [start, across, up]) {
    const key = [...start, ...across, ...up].join(',')
    if (face.key === key) return
    face.key = key
    const width = across.length()
    const height = up.length()
    u.copy(across).divideScalar(width)
    v.copy(up).divideScalar(height)
    normal.crossVectors(u, v)
    basis.makeBasis(u, v, normal)
    center.copy(start).addScaledVector(across, 0.5).addScaledVector(up, 0.5)
    face.mesh.position.copy(center)
    face.mesh.quaternion.setFromRotationMatrix(basis)
    face.mesh.scale.set(width, height, 1)
    face.thumbnail.position.copy(face.mesh.position)
    face.thumbnail.quaternion.copy(face.mesh.quaternion)
    face.thumbnail.scale.copy(face.mesh.scale)

    const sphere = back.geometry.boundingSphere
    const reach = sphere.radius + center.distanceTo(sphere.center)
    maskCamera.position.copy(center).addScaledVector(normal, 2 * reach)
    maskCamera.up.copy(v)
    maskCamera.lookAt(center)
    maskCamera.left = -width / 2
    maskCamera.right = width / 2
    maskCamera.top = height / 2
    maskCamera.bottom = -height / 2
    maskCamera.near = 0
    maskCamera.far = 4 * reach
    maskCamera.updateProjectionMatrix()
    clipPlane.setFromNormalAndCoplanarPoint(normal, center)

    // Keep approximately square texels without oversampling narrow sloped faces.
    const resolution = 1024 / Math.max(width, height)
    face.target.setSize(Math.max(16, Math.ceil(width * resolution)),
                        Math.max(16, Math.ceil(height * resolution)))
    renderer.setRenderTarget(face.target)
    renderer.render(maskScene, maskCamera)
    renderer.setRenderTarget(null)
  }

  return {
    surface, inset,
    setGeometry(geometry) {
      back.geometry = front.geometry = geometry
      for (const face of [top, left, right, shoulders]) face.key = null
    },
    update(profile, scale, bounds) {
      surface.visible = inset.visible = !!profile
      if (!profile) return
      const margin = 1 / scale
      const near = bounds.min.z - margin
      const far = bounds.max.z + margin
      const xmin = bounds.min.x - margin
      const xmax = bounds.max.x + margin
      const y0 = profile.red / scale
      const y1 = profile.blue / scale
      const x0 = profile.left / scale
      const x1 = profile.right / scale
      const c = profile.topLeft / scale
      const d = profile.topRight / scale
      const toU = x => (x - xmin) / (xmax - xmin)
      top.range.value.set(toU(c), toU(d))
      shoulders.range.value.set(toU(x0), toU(x1))
      prepareFace(top, horizontal(xmin, xmax, y1, near, far))
      prepareFace(shoulders, horizontal(xmin, xmax, y0, near, far))
      prepareFace(left, [
        new THREE.Vector3(x0, y0, far), new THREE.Vector3(c - x0, y1 - y0, 0),
        new THREE.Vector3(0, 0, near - far)
      ])
      prepareFace(right, [
        new THREE.Vector3(x1, y0, near), new THREE.Vector3(d - x1, y1 - y0, 0),
        new THREE.Vector3(0, 0, far - near)
      ])
    }
  }
}
