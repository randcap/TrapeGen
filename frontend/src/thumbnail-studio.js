import * as THREE from 'three'

let studio

function createStudio() {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
  renderer.setSize(192, 146, false)
  renderer.setClearColor(0, 0)
  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera()
  const key = new THREE.DirectionalLight(0xf0fff8, 2.45)
  key.position.set(-3, 6, 4)
  scene.add(new THREE.HemisphereLight(0xf8fffd, 0x526e61, 1.6), key)
  return { renderer, scene, camera }
}

export function renderThumbnail(objects, center, frame, direction) {
  studio ??= createStudio()
  const { renderer, scene, camera } = studio
  camera.left = -frame * 192 / 146
  camera.right = -camera.left
  camera.top = frame
  camera.bottom = -frame
  camera.near = frame / 100
  camera.far = frame * 12
  camera.position.copy(center).addScaledVector(direction.clone().normalize(), frame * 4)
  camera.lookAt(center)
  camera.updateProjectionMatrix()
  scene.add(...objects)
  try {
    renderer.render(scene, camera)
    return renderer.domElement.toDataURL('image/png')
  } finally {
    scene.remove(...objects)
  }
}

export function renderModelThumbnail(geometry) {
  const material = new THREE.MeshStandardMaterial({ color: 0xd6b995, roughness: 0.8, side: THREE.DoubleSide })
  const { center, radius } = geometry.boundingSphere
  try {
    return renderThumbnail([new THREE.Mesh(geometry, material)], center, radius * 1.06, new THREE.Vector3(.32, .12, 1))
  } finally {
    material.dispose()
  }
}
