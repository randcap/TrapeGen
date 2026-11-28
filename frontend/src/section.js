import { COORDINATE_MM, SECTION_SNAP_MM } from './profile.js'

const PLANE_EPSILON_MM = 1e-8
const failure = message => ({ message })

export function prepareSectionMesh(positions) {
  const count = positions.length / 9
  const lower = new Float32Array(count)
  const upper = new Float32Array(count)
  let min = Infinity
  let max = -Infinity
  for (let triangle = 0; triangle < count; triangle++) {
    const y = triangle * 9 + 1
    lower[triangle] = Math.min(positions[y], positions[y + 3], positions[y + 6])
    upper[triangle] = Math.max(positions[y], positions[y + 3], positions[y + 6])
    min = Math.min(min, lower[triangle])
    max = Math.max(max, upper[triangle])
  }
  return { positions, lower, upper, min, max }
}

function snap(value) {
  const scaled = value / SECTION_SNAP_MM
  const lower = Math.floor(scaled)
  return scaled - lower === 0.5 ? lower + (lower % 2 !== 0 ? 1 : 0) : Math.round(scaled)
}

function orientation(a, b, c) {
  const dx = b.x - a.x
  const dz = b.z - a.z
  const cross = dx * (c.z - a.z) - dz * (c.x - a.x)
  return Math.abs(cross) <= SECTION_SNAP_MM * Math.hypot(dx, dz) ? 0 : Math.sign(cross)
}

function between(point, a, b) {
  return point.x >= Math.min(a.x, b.x) - SECTION_SNAP_MM &&
    point.x <= Math.max(a.x, b.x) + SECTION_SNAP_MM &&
    point.z >= Math.min(a.z, b.z) - SECTION_SNAP_MM &&
    point.z <= Math.max(a.z, b.z) + SECTION_SNAP_MM
}

function intersects(a, b, c, d) {
  const abc = orientation(a, b, c)
  const abd = orientation(a, b, d)
  const cda = orientation(c, d, a)
  const cdb = orientation(c, d, b)
  return (abc * abd < 0 && cda * cdb < 0) ||
    (abc === 0 && between(c, a, b)) || (abd === 0 && between(d, a, b)) ||
    (cda === 0 && between(a, c, d)) || (cdb === 0 && between(b, c, d))
}

function inside(point, ring) {
  let result = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[j]
    const b = ring[i]
    if ((a.z > point.z) !== (b.z > point.z) &&
        point.x < a.x + (b.x - a.x) * (point.z - a.z) / (b.z - a.z)) result = !result
  }
  return result
}

function traceContours(vertices, edges) {
  // Checking crossings also detects overlapping outlines whose intersections
  // were not already vertices. Stop conservatively on pathologically dense input.
  const ordered = edges.map(([a, b]) => ({
    a, b, minX: Math.min(a.x, b.x), maxX: Math.max(a.x, b.x),
    minZ: Math.min(a.z, b.z), maxZ: Math.max(a.z, b.z)
  })).sort((a, b) => a.minX - b.minX)
  let comparisons = 0
  for (let i = 0; i < ordered.length; i++) {
    const first = ordered[i]
    for (let j = i + 1; j < ordered.length && ordered[j].minX <= first.maxX + SECTION_SNAP_MM; j++) {
      if (++comparisons > 2_000_000) return failure('截面轮廓过密，浏览器无法可靠验证边界。')
      const second = ordered[j]
      if (second.minZ > first.maxZ + SECTION_SNAP_MM || second.maxZ < first.minZ - SECTION_SNAP_MM) continue
      const shared = [first.a, first.b].find(point => point === second.a || point === second.b)
      if (shared) {
        const a = first.a === shared ? first.b : first.a
        const b = second.a === shared ? second.b : second.a
        if (!orientation(shared, a, b) && (between(a, shared, b) || between(b, shared, a))) {
          return failure('截面存在重叠边。')
        }
      } else if (intersects(first.a, first.b, second.a, second.b)) {
        return failure('截面轮廓相交或重叠。')
      }
    }
  }

  const rings = []
  const visited = new Set()
  for (const first of vertices.values()) {
    if (visited.has(first)) continue
    const ring = []
    let current = first
    let previous = null
    do {
      visited.add(current)
      ring.push(current)
      const [a, b] = current.neighbors
      const next = a === previous ? b : a
      previous = current
      current = next
    } while (current !== first)
    let area = 0
    for (let i = 1; i < ring.length - 1; i++) {
      const a = ring[i]
      const b = ring[i + 1]
      area += (a.x - first.x) * (b.z - first.z) - (a.z - first.z) * (b.x - first.x)
    }
    if (ring.length < 3 || Math.abs(area) <= SECTION_SNAP_MM ** 2) return failure('截面存在退化轮廓。')
    rings.push({ points: ring, area: Math.abs(area) })
  }
  // Like the Python polygonizer, an odd nesting depth is a hole, not a
  // separate region. Multiple independent regions require manual selection.
  if (rings.length > 512) return failure('截面轮廓过多，无法可靠选择外轮廓。')
  rings.sort((a, b) => b.area - a.area)
  const regions = rings.filter((ring, i) =>
    rings.slice(0, i).filter(candidate => inside(ring.points[0], candidate.points)).length % 2 === 0
  )
  if (regions.length !== 1) return failure(`截面有 ${regions.length} 个独立轮廓，无法自动选择外轮廓。`)
  return { outline: new Float64Array(regions[0].points.flatMap(({ x, z }) => [x, z])) }
}

export function selectAb(outline, range = null) {
  const segments = []
  let a = null
  let b = null
  for (let i = 0; i < outline.length; i += 2) {
    const next = (i + 2) % outline.length
    const x = outline[i]
    const z = outline[i + 1]
    const dx = outline[next] - x
    const dz = outline[next + 1] - z
    if (!dx && !dz) continue
    let start = 0
    let end = 1
    if (range) {
      if (dz === 0) {
        if (z < range[0] || z > range[1]) continue
      } else {
        const front = (range[0] - z) / dz
        const rear = (range[1] - z) / dz
        start = Math.max(0, Math.min(front, rear))
        end = Math.min(1, Math.max(front, rear))
        if (end <= start) continue // A point contact has no eligible contour segment.
      }
    }
    for (const t of [start, end]) {
      const point = { x: x + t * dx, z: z + t * dz }
      if (range) {
        point.z = Math.max(range[0], Math.min(range[1], point.z))
        segments.push(point.x, point.z)
      }
      if (!a || point.x < a.x) a = point
      if (!b || point.x > b.x) b = point
    }
  }
  if (!a) return failure('搜索条带内没有有效的外轮廓线段。')
  if (b.x - a.x <= COORDINATE_MM) return { message: '搜索范围内 X 宽度过小。', segments }
  return { left: a.x, right: b.x, a, b, segments }
}

export function sliceSection(mesh, yMm, scale) {
  if (!(mesh.min * scale < yMm && yMm < mesh.max * scale)) return failure('红色截面超出模型高度。')
  const { positions, lower, upper } = mesh
  const vertices = new Map()
  const edges = []
  const y = yMm / scale
  const eps = PLANE_EPSILON_MM / scale
  const getVertex = ([x, z]) => {
    const key = `${snap(x)},${snap(z)}`
    if (!vertices.has(key)) vertices.set(key, { x, z, neighbors: [] })
    return vertices.get(key)
  }

  for (let i = 0; i < lower.length; i++) {
    if (lower[i] > y + eps || upper[i] < y - eps) continue
    const base = i * 9
    const distances = [0, 3, 6].map(j => positions[base + j + 1] - y)
    const signs = distances.map(d => Math.abs(d) <= eps ? 0 : Math.sign(d))
    // Match Trimesh's coplanar-edge convention: keep the edge on the
    // positive side only and ignore fully coplanar faces.
    if (!signs.includes(1) || (!signs.includes(-1) && signs.filter(s => s === 0).length !== 2)) continue
    const points = []
    for (let a = 0; a < 3; a++) {
      const b = (a + 1) % 3
      const j = base + a * 3
      const k = base + b * 3
      if (signs[a] === 0) points.push([positions[j] * scale, positions[j + 2] * scale])
      if (signs[a] * signs[b] < 0) {
        const t = distances[a] / (distances[a] - distances[b])
        points.push([
          (positions[j] + t * (positions[k] - positions[j])) * scale,
          (positions[j + 2] + t * (positions[k + 2] - positions[j + 2])) * scale
        ])
      }
    }
    if (points.length !== 2) continue
    if (points.some(p => p.some(value => !Number.isSafeInteger(snap(value))))) {
      return failure('截面坐标超出浏览器的数值精度范围。')
    }
    const [a, b] = points.map(getVertex)
    if (a === b || a.neighbors.includes(b)) continue
    a.neighbors.push(b)
    b.neighbors.push(a)
    edges.push([a, b])
  }
  if (!edges.length) return failure('红色截面与模型没有有效交线。')
  for (const [key, vertex] of vertices) {
    if (!vertex.neighbors.length) vertices.delete(key)
    else if (vertex.neighbors.length !== 2) return failure('截面存在开口、分叉或重叠轮廓。')
  }
  return traceContours(vertices, edges)
}
