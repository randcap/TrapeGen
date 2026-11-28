const sidesByShape = { circular: 64, triangular: 3, hexagonal: 6 }
const point = value => Array.isArray(value) && value.length === 2 && value.every(Number.isFinite)
const ring = value => Array.isArray(value) && value.length >= 3 && value.every(point)
const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
const samePoint = (a, b) => a[0] === b[0] && a[1] === b[1]

function between(p, a, b) {
  return p[0] >= Math.min(a[0], b[0]) && p[0] <= Math.max(a[0], b[0]) &&
    p[1] >= Math.min(a[1], b[1]) && p[1] <= Math.max(a[1], b[1])
}

function intersects(a, b, c, d) {
  const s = Math.sign(cross(a, b, c)), t = Math.sign(cross(a, b, d))
  const u = Math.sign(cross(c, d, a)), v = Math.sign(cross(c, d, b))
  return (s * t < 0 && u * v < 0) ||
    (!s && between(c, a, b)) || (!t && between(d, a, b)) ||
    (!u && between(a, c, d)) || (!v && between(b, c, d))
}

function inside([x, z], outline) {
  let result = false
  for (let i = 0, j = outline.length - 1; i < outline.length; j = i++) {
    const [ax, az] = outline[j], [bx, bz] = outline[i]
    if ((az > z) !== (bz > z) && x < ax + (z - az) * (bx - ax) / (bz - az)) result = !result
  }
  return result
}

export function readCustomProfile(json) {
  const data = JSON.parse(json)
  const points = Array.isArray(data) ? data : data?.profile_xz
  if (!ring(points) || points.length > 128) throw Error('profile_xz 须包含 3–128 个有限数值的 [X, Z] 点。')
  const open = samePoint(points[0], points.at(-1)) ? points.slice(0, -1) : points
  if (open.length < 3 || new Set(open.map(p => p.join(','))).size !== open.length) {
    throw Error('自定义轮廓至少需要三个互不重复的顶点。')
  }
  const span = Math.max(...open.flat().map(Math.abs))
  const normalized = open.map(([x, z]) => [x / span, z / span])
  const origin = normalized[0]
  const vertices = normalized.map(([x, z]) => [x - origin[0], z - origin[1]])
  let areaTwice = 0, sumX = 0, sumZ = 0
  for (let i = 0; i < vertices.length; i++) {
    const a = vertices[i]
    const b = vertices[(i + 1) % vertices.length]
    const before = vertices.at(i - 1)
    if (samePoint(a, b) || (!cross(before, a, b) && (between(b, before, a) || between(before, a, b)))) {
      throw Error('自定义轮廓包含重叠或退化的边。')
    }
    for (let j = i + 2; j < vertices.length; j++) {
      if (i === 0 && j === vertices.length - 1) continue
      if (intersects(a, b, vertices[j], vertices[(j + 1) % vertices.length])) throw Error('自定义轮廓存在自交。')
    }
    const weight = a[0] * b[1] - b[0] * a[1]
    areaTwice += weight
    sumX += (a[0] + b[0]) * weight
    sumZ += (a[1] + b[1]) * weight
  }
  if (!areaTwice) throw Error('自定义轮廓的面积须大于零。')
  const x = vertices.map(p => p[0]), z = vertices.map(p => p[1])
  const extent = Math.max(Math.max(...x) - Math.min(...x), Math.max(...z) - Math.min(...z))
  const cx = sumX / (3 * areaTwice), cz = sumZ / (3 * areaTwice)
  return { points, normalized: vertices.map(([px, pz]) => [(px - cx) / extent, (pz - cz) / extent]) }
}

export function parseConnectorSurface(data) {
  if (!Number.isFinite(data?.blue_y_mm) || !point(data.center_xz_mm) ||
      !Array.isArray(data.regions) || !data.regions.length || !data.regions.every(region =>
        ring(region?.outline_xz_mm) && Array.isArray(region.holes_xz_mm) && region.holes_xz_mm.every(ring))) {
    throw Error('切面响应缺少有效的轮廓或中心。')
  }
  return data
}

function crossesRing(profile, boundary) {
  for (let i = 0, j = profile.length - 1; i < profile.length; j = i++) {
    for (let k = 0, l = boundary.length - 1; k < boundary.length; l = k++) {
      if (intersects(profile[j], profile[i], boundary[l], boundary[k])) return true
    }
  }
  return false
}

export function placeConnector(spec, surface, custom) {
  const [shape, kind] = spec.preset.split('_')
  const n = sidesByShape[shape]
  const radius = shape === 'circular' ? 0.5 : 1 / (2 * Math.sin(Math.PI / n))
  const points = shape === 'custom' ? custom.normalized : Array.from({ length: n }, (_, i) => {
    const angle = i * (2 * Math.PI / n)
    return [radius * Math.cos(angle), radius * Math.sin(angle)]
  })
  const angle = -(spec.angle_deg % 360) * Math.PI / 180 // Right-handed rotation about +Y in the XZ plane.
  const cos = Math.cos(angle), sin = Math.sin(angle)
  const center = surface.center_xz_mm.map((value, i) => value + spec.offset_xz_mm[i])
  const outline = points.map(([x, z]) => [
    center[0] + spec.size_mm * (x * cos - z * sin),
    center[1] + spec.size_mm * (x * sin + z * cos)
  ])
  const isPost = kind === 'post'
  const start = surface.blue_y_mm
  const end = start + (isPost ? spec.depth_mm : -spec.depth_mm)
  if (!ring(outline) || !Number.isFinite(end)) throw Error('特征的位置或尺寸超出预览的坐标范围。')
  const regionIndex = surface.regions.findIndex(({ outline_xz_mm: boundary, holes_xz_mm: holes }) =>
    inside(outline[0], boundary) && !crossesRing(outline, boundary) && holes.every(hole =>
      !inside(outline[0], hole) && !inside(hole[0], outline) && !crossesRing(outline, hole)))
  return { center, outline, start, end, isPost, fits: regionIndex >= 0, regionIndex }
}
