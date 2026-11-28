import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { UNIT_TO_MM } from './profile.js'
import { createPreviewMaterial, createPreviewPlanes } from './preview.js'
import { createCutCaps } from './caps.js'
import { createSearchBand } from './search-band.js'
import { createConnectorPreview, createConnectorResult } from './connector-preview.js'

export function createViewer(host, inset, beforeRender, edit) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  host.append(renderer.domElement)
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1000)
  const orbit = new OrbitControls(camera, renderer.domElement)
  let frame = null
  function requestRender() {
    if (frame !== null) return
    frame = requestAnimationFrame(() => {
      frame = null
      beforeRender()
      render()
    })
  }
  orbit.addEventListener('change', requestRender)
  const lighting = new THREE.Group()
  lighting.add(new THREE.HemisphereLight(0xfffbdf, 0x70887c, 2))
  const light = new THREE.DirectionalLight(0xfff3dc, 2.5)
  light.position.set(-4, 7, 5)
  lighting.add(light)
  scene.add(lighting)

  const preview = createPreviewMaterial()
  const emptyGeometry = new THREE.BufferGeometry()
  const model = new THREE.Mesh(emptyGeometry, preview.material)
  model.visible = false
  const removed = createPreviewMaterial({ ghost: true })
  const ghost = new THREE.Mesh(model.geometry, removed.material)
  ghost.visible = false
  const insetScene = new THREE.Scene()
  insetScene.background = new THREE.Color(0xf1f5ef)
  const insetPreview = createPreviewMaterial()
  const insetModel = new THREE.Mesh(model.geometry, insetPreview.material)
  insetScene.add(lighting.clone(), insetModel)
  const caps = createCutCaps(renderer, preview.material.color)
  caps.surface.visible = caps.inset.visible = false
  scene.add(caps.surface)
  insetScene.add(caps.inset)
  const insetCamera = camera.clone()
  const insetDirection = new THREE.Vector3()
  const insetBounds = new THREE.Box3()
  const insetFocus = new THREE.Sphere()
  const references = new THREE.Group()
  const grid = new THREE.GridHelper(1, 20, 0x859b92, 0xa8b8ac)
  grid.material.transparent = true
  grid.material.opacity = 0.48
  grid.material.depthWrite = false
  const axes = new THREE.AxesHelper(1)
  references.add(grid, axes)
  references.visible = false
  const planes = createPreviewPlanes()
  const searchBand = createSearchBand()
  const connector = createConnectorPreview()
  const connectorResult = createConnectorResult(preview.material.color)
  const anchor = new THREE.Object3D()
  scene.add(references, model, ghost, planes.group, searchBand.group, connector.group, connectorResult.main, anchor)
  insetScene.add(connectorResult.inset)

  // Follow the Editor viewport's convention of suspending camera controls
  // while a TransformControls handle owns the pointer.
  const gizmo = new TransformControls(camera, renderer.domElement)
  gizmo.setSize(0.72)
  scene.add(gizmo.getHelper())
  let mode = 'view'
  let bounds, center, radius, activeParams, activeProfile
  let showTools = false
  gizmo.addEventListener('change', requestRender)
  gizmo.addEventListener('dragging-changed', ({ value }) => {
    orbit.enabled = !value
  })
  gizmo.addEventListener('objectChange', () => {
    if (!gizmo.dragging || !activeParams) return
    if (mode === 'angle') {
      edit('angle', THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(anchor.rotation.z), 52, 55))
    } else {
      edit(mode, anchor.position.y * UNIT_TO_MM[activeParams.unit])
    }
  })

  function syncGizmo() {
    if (gizmo.dragging) return
    if (!showTools || !bounds || !activeParams || mode === 'view' ||
        (mode === 'angle' ? !activeProfile : !Number.isFinite(activeParams[mode]))) {
      if (gizmo.object) gizmo.detach()
      return
    }
    const scale = UNIT_TO_MM[activeParams.unit]
    const rotating = mode === 'angle'
    if (rotating) {
      anchor.position.set(activeProfile.left / scale, activeProfile.red / scale, bounds.max.z + 1 / scale)
      anchor.rotation.set(0, 0, THREE.MathUtils.degToRad(activeParams.angle))
    } else {
      anchor.position.set(center.x, activeParams[mode] / scale, bounds.max.z + 1 / scale)
      anchor.rotation.set(0, 0, 0)
    }
    if (!gizmo.object) gizmo.attach(anchor)
  }

  function fitDistance(view, padding, extent = radius) {
    const halfFov = THREE.MathUtils.degToRad(view.fov / 2)
    return extent * padding / Math.sin(Math.atan(Math.tan(halfFov) * Math.min(1, view.aspect)))
  }

  function render() {
    renderer.setViewport(0, 0, host.clientWidth, host.clientHeight)
    renderer.render(scene, camera)
    if (!activeProfile || !inset.clientWidth || !inset.clientHeight) return

    // Draw the comparison on the same canvas, using the original GPU buffers.
    const rectangle = inset.getBoundingClientRect()
    const canvas = host.getBoundingClientRect()
    const left = Math.round(rectangle.left - canvas.left)
    const bottom = Math.round(canvas.bottom - rectangle.bottom)
    const width = inset.clientWidth
    const height = inset.clientHeight
    if (left < 0 || bottom < 0 || left + width > host.clientWidth || bottom + height > host.clientHeight) return
    insetCamera.aspect = width / height
    insetCamera.near = camera.near
    const distance = fitDistance(insetCamera, 1.06, insetFocus.radius)
    insetCamera.far = Math.max(camera.far, distance + insetFocus.radius * 2)
    insetDirection.copy(camera.position).sub(orbit.target).normalize()
    insetCamera.position.copy(insetFocus.center).addScaledVector(insetDirection, distance)
    insetCamera.lookAt(insetFocus.center)
    insetCamera.updateProjectionMatrix()
    renderer.setViewport(left, bottom, width, height)
    renderer.setScissor(left, bottom, width, height)
    renderer.setScissorTest(true)
    renderer.render(insetScene, insetCamera)
    renderer.setScissorTest(false)
  }

  function fit(direction = camera.position.clone().sub(orbit.target)) {
    if (!bounds) return
    if (!direction.lengthSq()) direction.set(0.45, 0.18, 1)
    const distance = fitDistance(camera, 1.18)
    orbit.target.copy(center)
    camera.position.copy(center).addScaledVector(direction.normalize(), distance)
    camera.near = radius / 1000
    camera.far = distance * 150
    orbit.minDistance = radius * 0.08
    orbit.maxDistance = distance * 80
    camera.updateProjectionMatrix()
    orbit.update()
    requestRender()
  }
  new ResizeObserver(() => {
    renderer.setSize(host.clientWidth, host.clientHeight)
    camera.aspect = Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight)
    camera.updateProjectionMatrix()
    requestRender()
  }).observe(host)

  return {
    requestRender,
    parse(buffer) {
      const geometry = new STLLoader().parse(buffer)
      geometry.computeBoundingBox()
      geometry.computeBoundingSphere()
      if (!Number.isFinite(geometry.boundingSphere.radius) || geometry.boundingSphere.radius <= 0) {
        geometry.dispose()
        throw Error('STL 缺少有效三角面。')
      }
      return geometry
    },
    show(geometry, { fitView = true } = {}) {
      model.geometry = ghost.geometry = insetModel.geometry = geometry
      caps.setGeometry(geometry)
      model.visible = true
      bounds = geometry.boundingBox
      center = geometry.boundingSphere.center
      radius = geometry.boundingSphere.radius
      grid.position.set(center.x, bounds.min.y, center.z)
      grid.scale.setScalar(radius * 3.5)
      const axisLength = max => THREE.MathUtils.clamp(max + radius * 0.16, radius * 0.65, radius * 1.5)
      axes.scale.set(axisLength(bounds.max.x), axisLength(bounds.max.y), axisLength(bounds.max.z))
      if (fitView) fit(new THREE.Vector3(0.32, 0.12, 1))
    },
    clear() {
      model.geometry = ghost.geometry = insetModel.geometry = emptyGeometry
      caps.setGeometry(emptyGeometry)
      model.visible = false
      bounds = center = radius = undefined
    },
    updatePreview(params, profile, { expanded, comparing, connectorMode, surface, placement, opacity, outline, ab }) {
      activeParams = params
      activeProfile = expanded || connectorMode ? profile : null
      showTools = expanded && !comparing
      if (!showTools && gizmo.dragging) gizmo.pointerUp(null)
      const scale = UNIT_TO_MM[params.unit]
      connector.update(surface, placement, scale)
      connector.group.visible &&= !comparing
      const hasFeature = connectorResult.update(activeProfile ? surface : null, placement, scale, comparing)
      const mainFeature = comparing && hasFeature
      caps.update(activeProfile, scale, bounds, { mainTop: !mainFeature, insetTop: !hasFeature })
      preview.set(activeProfile, scale, mainFeature)
      insetPreview.set(activeProfile, scale, hasFeature)
      if (bounds) insetFocus.set(center, radius)
      if (hasFeature && placement.isPost && placement.end / scale > bounds.max.y) {
        insetBounds.copy(bounds)
        insetBounds.max.y = placement.end / scale
        insetBounds.getBoundingSphere(insetFocus)
      }
      removed.set(activeProfile, scale)
      removed.material.opacity = opacity
      ghost.visible = !!activeProfile && showTools && !connectorMode && opacity > 0
      references.visible = !!bounds && expanded
      planes.set(bounds, params, activeProfile, showTools)
      searchBand.update(bounds, radius, scale, params.yellow + params.offset,
        params.ab_z_range_mm, outline, ab, showTools)
      syncGizmo()
      return hasFeature
    },
    setMode(next) {
      if (gizmo.dragging) gizmo.pointerUp(null)
      mode = next
      gizmo.setMode(mode === 'angle' ? 'rotate' : 'translate')
      gizmo.showX = false
      gizmo.showY = mode !== 'angle'
      gizmo.showZ = mode === 'angle'
      syncGizmo()
      requestRender()
    },
    fit: () => fit(),
    front: () => fit(new THREE.Vector3(0, 0, 1)),
    side: () => fit(new THREE.Vector3(1, 0, 0)),
    top: () => fit(new THREE.Vector3(0, 1, 1e-6))
  }
}
