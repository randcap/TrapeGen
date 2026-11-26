import * as THREE from 'three'
import { UNIT_TO_MM } from './profile.js'

export function createPreviewMaterial({ ghost = false } = {}) {
  const region = {
    cropLimits: { value: new THREE.Vector4() },
    cropSlope: { value: 0 },
    cropUnit: { value: 1 },
    cropEnabled: { value: false },
    cropGhost: { value: ghost }
  }
  const material = new THREE.MeshStandardMaterial({
    color: ghost ? 0x923c37 : 0xd6b995,
    roughness: 0.8,
    side: ghost ? THREE.FrontSide : THREE.DoubleSide,
    transparent: ghost,
    depthWrite: !ghost
  })
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, region)
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec2 cropPosition;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\ncropPosition = position.xy;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying vec2 cropPosition;
        uniform vec4 cropLimits;
        uniform float cropSlope;
        uniform float cropUnit;
        uniform bool cropEnabled;
        uniform bool cropGhost;`)
      .replace('#include <color_fragment>', `#include <color_fragment>
        vec2 cropMm = cropPosition * cropUnit;
        float dy = cropMm.y - cropLimits.x;
        float inset = dy * cropSlope;
        bool removed = dy > 0.0 &&
            (cropMm.y > cropLimits.y || cropMm.x < cropLimits.z + inset ||
             cropMm.x > cropLimits.w - inset);
        if (cropEnabled && removed != cropGhost) discard;`)
  }
  return {
    material,
    set(profile, scale) {
      region.cropEnabled.value = !!profile
      region.cropUnit.value = scale || 1
      if (profile) {
        region.cropLimits.value.set(profile.red, profile.blue, profile.left, profile.right)
        region.cropSlope.value = profile.slope
      }
    }
  }
}

function plane(color, opacity) {
  const position = new THREE.BufferAttribute(new Float32Array(12), 3)
  position.setUsage(THREE.DynamicDrawUsage)
  const surface = new THREE.BufferGeometry()
  surface.setAttribute('position', position)
  surface.setIndex([0, 1, 2, 0, 2, 3])
  const mesh = new THREE.Mesh(surface, new THREE.MeshBasicMaterial({
    color, opacity, transparent: true, side: THREE.DoubleSide,
    depthWrite: false, forceSinglePass: true,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1
  }))
  const contour = new THREE.BufferGeometry()
  contour.setAttribute('position', position)
  const outline = new THREE.LineLoop(contour, new THREE.LineBasicMaterial({
    color, opacity: 0.86, transparent: true, depthWrite: false
  }))
  mesh.frustumCulled = outline.frustumCulled = false
  const group = new THREE.Group()
  group.add(mesh, outline)
  return {
    group,
    set(vertices) {
      group.visible = !!vertices
      if (vertices) {
        position.array.set(vertices)
        position.needsUpdate = true
      }
    }
  }
}

export function createPreviewPlanes() {
  const group = new THREE.Group()
  const yellow = plane(0xbc960d, 0.12)
  const red = plane(0xc64232, 0.14)
  const blue = plane(0x287bb8, 0.17)
  const left = plane(0x8056bb, 0.23)
  const right = plane(0x8056bb, 0.23)
  group.add(yellow.group, red.group, blue.group, left.group, right.group)

  return {
    group,
    set(bounds, params, profile, visible) {
      group.visible = !!bounds && visible
      if (!group.visible) return
      const scale = UNIT_TO_MM[params.unit]
      const { min, max } = bounds
      const margin = 1 / scale
      const visualMargin = Math.max(margin, (max.x - min.x) * 0.04)
      const near = min.z - margin
      const far = max.z + margin
      const horizontal = (height, x0 = min.x - visualMargin, x1 = max.x + visualMargin) => {
        if (!Number.isFinite(height)) return null
        const y = height / scale
        return [x0, y, near, x1, y, near, x1, y, far, x0, y, far]
      }
      const sloped = (bottom, top) => {
        if (!profile) return null
        const x0 = bottom / scale
        const x1 = top / scale
        const y0 = profile.red / scale
        const y1 = profile.blue / scale
        return [x0, y0, near, x1, y1, near, x1, y1, far, x0, y0, far]
      }
      yellow.set(horizontal(params.yellow))
      red.set(horizontal(params.yellow + params.offset))
      // The blue plane spans the reference height, even if the profile is invalid.
      blue.set(horizontal(params.blue))
      left.set(sloped(profile?.left, profile?.topLeft))
      right.set(sloped(profile?.right, profile?.topRight))
    }
  }
}
