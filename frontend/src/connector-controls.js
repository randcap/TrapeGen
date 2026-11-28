import { CarouselSelector } from './carousel-selector.js'
import { placeConnector, readCustomProfile } from './connector.js'
import { renderConnectorThumbnail } from './connector-thumbnail.js'

const presets = [
  { id: 'circular_post', name: '圆柱', icon: '●' },
  { id: 'circular_hole', name: '圆孔', icon: '○' },
  { id: 'triangular_post', name: '三角棱柱', icon: '▲' },
  { id: 'triangular_hole', name: '三角棱孔', icon: '△' },
  { id: 'hexagonal_post', name: '六角棱柱', icon: '⬢' },
  { id: 'hexagonal_hole', name: '六角棱孔', icon: '⬡' }
]

function thumbnail(preset, profile) {
  try {
    return renderConnectorThumbnail(preset, profile)
  } catch (error) {
    console.warn('无法生成装配特征缩略图', error)
  }
}

export function createConnectorControls(panel, palette, changed, retry) {
  const field = id => panel.querySelector(`#connector-${id}`)
  const fileInput = field('file')
  const status = field('status')
  const retryButton = field('retry')
  const kind = field('kind')
  const controls = ['size', 'depth', 'angle', 'x', 'z'].map(field)
  const fileJobs = new WeakMap()
  const createDraft = () => ({ open: false, preset: 'circular_post', kind: 'post',
    values: controls.map(control => control.defaultValue) })
  let draft = createDraft()
  let presetItems = presets
  const carousel = new CarouselSelector(palette, {
    items: presetItems, label: '装配特征类型', onChange: (_, item) => select(item.id)
  })

  function syncItems() {
    const items = draft.custom ? [...presetItems, {
      id: 'custom', name: '自定义', icon: '◇', thumbnail: draft.custom.thumbnails[kind.value]
    }] : presetItems
    carousel.setItems(items, items.findIndex(item => item.id === draft.preset))
  }

  function syncSelection() {
    const { preset } = draft
    field('custom-mode').hidden = preset !== 'custom'
    field('size-label').textContent = preset === 'custom' ? '轮廓最大边长' :
      preset.startsWith('circular') ? '直径' : '边长'
    field('depth-label').textContent = (preset === 'custom' ? kind.value === 'post' : preset.endsWith('_post')) ? '柱高' : '孔深'
  }

  function select(next) {
    draft.preset = next
    syncSelection()
    changed()
  }

  function read() {
    const { preset } = draft
    const [size, depth, angle, x, z] = controls.map(control => control.valueAsNumber)
    if (![size, depth, angle, x, z].every(Number.isFinite) || size <= 0 || depth <= 0) {
      return { error: '尺寸和柱高或孔深须为正数，角度及偏移须为有限数值。' }
    }
    const spec = {
      preset: preset === 'custom' ? `custom_${kind.value}` : preset,
      size_mm: size, depth_mm: depth, angle_deg: angle, offset_xz_mm: [x, z]
    }
    if (preset === 'custom') spec.profile_xz = draft.custom.profile.points
    return { spec }
  }

  for (const control of panel.querySelectorAll('input[type=number], select')) control.oninput = () => {
    if (control === kind) syncItems()
    syncSelection()
    changed()
  }
  field('upload').onclick = () => fileInput.click()
  fileInput.onchange = async () => {
    const file = fileInput.files[0]
    fileInput.value = ''
    if (!file) return
    const owner = draft
    const job = {}
    fileJobs.set(owner, job)
    try {
      const profile = readCustomProfile(await file.text())
      if (fileJobs.get(owner) !== job) return
      owner.custom = { profile, thumbnails: { post: thumbnail('custom_post', profile), hole: thumbnail('custom_hole', profile) } }
      owner.fileInfo = { text: file.name, state: 'ready' }
      owner.preset = 'custom'
    } catch (error) {
      if (fileJobs.get(owner) !== job) return
      owner.fileInfo = { state: 'warning', text: `无法读取轮廓 ${error instanceof SyntaxError ? 'JSON 格式无效。' : error.message}` }
    }
    if (owner === draft) {
      syncFileInfo()
      syncItems()
      syncSelection()
      changed()
    }
  }
  panel.addEventListener('toggle', changed)
  retryButton.onclick = retry
  syncSelection()

  function syncFileInfo() {
    field('file-info').textContent = draft.fileInfo?.text ?? ''
    field('file-info').dataset.state = draft.fileInfo?.state ?? ''
  }

  return {
    get open() { return panel.open },
    createDraft,
    saveDraft() {
      draft.open = panel.open
      draft.kind = kind.value
      draft.values = controls.map(control => control.value)
    },
    restoreDraft(next) {
      draft = next
      status.textContent = ''
      delete status.dataset.state
      retryButton.hidden = true
      controls.forEach((control, i) => { control.value = draft.values[i] })
      kind.value = draft.kind
      panel.open = draft.open
      syncSelection()
      syncFileInfo()
      syncItems()
    },
    read,
    update(state, baseMessage) {
      palette.hidden = !panel.open
      if (!panel.open) return {}
      if (presetItems === presets) {
        presetItems = presets.map(item => ({ ...item, thumbnail: thumbnail(item.id) }))
        syncItems()
      }
      const { spec, error } = read()
      let placement
      let placementError
      if (state.surface && spec) {
        try {
          placement = placeConnector(spec, state.surface, draft.custom?.profile)
        } catch (error) {
          placementError = error.message
        }
      }
      let kind = 'warning'
      let text = baseMessage || state.error || error || placementError
      if (state.pending) {
        kind = 'pending'
        text = '正在读取真实蓝切面…'
      } else if (!text && placement) {
        kind = placement.fits ? 'ready' : 'warning'
        text = placement.fits
          ? `特征中心 X ${placement.center[0].toFixed(2)} · Z ${placement.center[1].toFixed(2)} mm`
          : '特征与切面外边界或内孔相交，请调整尺寸或位置。'
      }
      status.dataset.state = kind
      if (status.textContent !== text) status.textContent = text || ''
      retryButton.hidden = !state.error
      return { placement, invalid: !!(error || placementError) }
    }
  }
}
