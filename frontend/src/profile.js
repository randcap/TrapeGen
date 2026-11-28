// TrapeGen uses local millimeters. See src/trapegen/config.py and profile.py.
export const UNIT_TO_MM = { mm: 1, cm: 10, m: 1000, in: 25.4 }
export const COORDINATE_MM = 1e-6
export const SECTION_SNAP_MM = 1e-7

export function validAbRange(range) {
  return range?.length === 2 && range.every(Number.isFinite) && range[0] < range[1]
}

export function checkProfile(params) {
  const { yellow, blue, offset, angle } = params
  if (![yellow, blue, offset, angle].every(Number.isFinite) || !UNIT_TO_MM[params.unit]) {
    return '请输入有效的参考线高度、单位和角度。'
  }
  if (offset < 5 || offset > 10 || angle < 52 || angle > 55) {
    return '偏移范围为 5–10 mm，斜面角度范围为 52–55°。'
  }
  if (params.ab_z_range_mm && !validAbRange(params.ab_z_range_mm)) {
    return '请输入有效的 A/B 搜索范围，Z 下限须小于上限。'
  }
  const red = yellow + offset
  if (!Number.isFinite(red) || blue - red <= COORDINATE_MM) return '蓝线必须高于红色截面。'
  return null
}

export function buildProfile(params, section) {
  const red = params.yellow + params.offset
  const slope = 1 / Math.tan(params.angle * Math.PI / 180)
  const inset = (params.blue - red) * slope
  const { left, right } = section
  if (right - left - 2 * inset <= COORDINATE_MM) return null
  return { red, blue: params.blue, left, right, slope, topLeft: left + inset, topRight: right - inset }
}
