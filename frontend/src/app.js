import { createViewer } from './viewer.js'
import { buildProfile, checkProfile } from './profile.js'
import { createSectionSession, matchesSample } from './section-session.js'

const el = id => document.getElementById(id)
const params = () => ({
  unit: el('unit').value, yellow: el('yellow').valueAsNumber, blue: el('blue').valueAsNumber,
  angle: el('angle').valueAsNumber, offset: el('offset').valueAsNumber, union: el('union').checked
})

async function checked(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) throw Error(await response.text() || response.statusText)
  return response
}

function download(blob, name) {
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}

function start() {
  let source
  let loadId = 0
  let loading = false
  let exporting = false
  let dirty = false
  let expanded = true
  let pointerCompare = false
  let keyboardCompare = false
  const compare = el('compare')

  const viewer = createViewer(el('viewport'), el('comparison-viewport'), updatePreview, (field, value) => {
    el(field).value = Number(value.toFixed(field === 'angle' ? 1 : 2))
    invalidate()
  })

  function invalidate() {
    dirty = true
    viewer.requestRender()
  }

  function previewStatus(kind, text, bounds = '') {
    el('preview-status').dataset.state = kind
    el('preview-status').textContent = text
    el('section-info').textContent = bounds
  }

  function displayPreview(current, profile) {
    compare.disabled = !expanded || !profile
    if (compare.disabled) pointerCompare = keyboardCompare = false
    const comparing = pointerCompare || keyboardCompare
    compare.setAttribute('aria-pressed', comparing)
    el('comparison-inset').hidden = !expanded || !profile || comparing
    const opacity = el('opacity').valueAsNumber
    el('opacityValue').textContent = `${opacity}%`
    viewer.updatePreview(current, profile, { expanded, comparing, opacity: opacity / 100 })
  }

  function updatePreview() {
    if (!dirty) return
    dirty = false
    const current = params()
    el('offsetValue').textContent = `${current.offset.toFixed(1)} mm`
    el('angleValue').textContent = `${current.angle.toFixed(1)}°`
    el('download').disabled = !source || loading
    if (!source || loading || !expanded) {
      el('apply').disabled = true
      displayPreview(current, null)
      return
    }

    const error = checkProfile(current)
    el('apply').disabled = exporting || !!error
    const section = error ? null : source.sections.get(current, source.verifiedSample)
    const profile = section && !section.message ? buildProfile(current, section) : null
    displayPreview(current, profile)
    const bounds = profile ? `截面 X  ${profile.left.toFixed(4)} ～ ${profile.right.toFixed(4)} mm` : ''
    if (error || section?.message) {
      previewStatus('warning', error || section.message)
    } else if (!section) {
      previewStatus('pending', '正在计算当前红线截面…')
    } else if (!profile) {
      previewStatus('warning', '梯形上底须为正宽度，请调整高度或角度。')
      el('apply').disabled = true
    } else if (current.union && !section.prepared) {
      previewStatus('warning', '近似预览 · 导出时会合并外壳，截面可能变化。', bounds)
    } else {
      previewStatus('ready', section.prepared ? '实时预览 · 样件已合并截面' : '实时预览 · 浏览器截面', bounds)
    }
  }

  async function load(file) {
    const id = ++loadId
    loading = true
    invalidate()
    previewStatus('pending', '正在读取 STL…')
    try {
      const blob = file || await (await checked('/sample.stl')).blob()
      const bytes = await blob.arrayBuffer()
      if (id !== loadId) return
      const verifiedSample = !file && await matchesSample(bytes).catch(() => false)
      if (id !== loadId) return
      const geometry = viewer.parse(bytes)
      source?.sections.dispose()
      source = {
        blob, verifiedSample,
        name: file?.name || 'xiong.stl',
        sections: createSectionSession(geometry, invalidate)
      }
      const box = geometry.boundingBox
      const height = box.max.y - box.min.y
      el('name').textContent = source.name
      el('count').textContent = `${(geometry.attributes.position.count / 3).toLocaleString()} 个三角面`
      el('unit').value = file ? 'mm' : 'cm'
      el('union').checked = !file
      el('yellow').value = file ? Number((box.min.y + height * 0.55).toFixed(3)) : 69
      el('blue').value = file ? Number((box.min.y + height * 0.85).toFixed(3)) : 87
      el('offset').value = 7.5
      el('angle').value = 53
      setMode('view')
      viewer.show(geometry)
      if (!exporting) el('status').textContent = ''
    } catch (error) {
      if (id === loadId) el('status').textContent = `无法打开模型。 ${error.message}`
    } finally {
      if (id === loadId) {
        loading = false
        if (!source) previewStatus('warning', '请打开一个有效的 STL 文件。')
        invalidate()
      }
    }
  }

  async function exportResult() {
    if (!source || loading || exporting) return
    const model = source
    const settings = params()
    const error = checkProfile(settings)
    if (error) {
      el('status').textContent = error
      return
    }
    // Hold the clicked file and parameters while the upload and export run.
    exporting = true
    el('apply').disabled = true
    el('status').textContent = `正在生成并校验 ${model.name} 的裁剪件…`
    try {
      const upload = await checked('/api/upload', {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: model.blob
      })
      const { model: modelId } = await upload.json()
      const response = await checked('/api/clip', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId, ...settings })
      })
      const name = model.name.replace(/\.stl$/i, '') + '-clipped.stl'
      download(await response.blob(), name)
      el('status').textContent = `已导出 ${name}`
    } catch (error) {
      el('status').textContent = `导出失败。 ${error.message}`
    } finally {
      exporting = false
      invalidate()
    }
  }

  const modeButtons = [...document.querySelectorAll('[data-edit]')]
  function setMode(mode) {
    viewer.setMode(mode)
    for (const button of modeButtons) button.setAttribute('aria-pressed', button.dataset.edit === mode)
  }

  for (const button of modeButtons) button.onclick = () => setMode(button.dataset.edit)
  for (const id of ['angle', 'offset', 'yellow', 'blue', 'unit', 'union', 'opacity']) el(id).oninput = invalidate
  for (const id of ['fit', 'side', 'front']) el(id).onclick = viewer[id]
  const toggle = el('toggle-preview')
  toggle.onclick = () => {
    expanded = !expanded
    toggle.setAttribute('aria-expanded', expanded)
    el('preview-body').inert = !expanded
    el('edit-tools').hidden = compare.hidden = !expanded
    document.querySelector('main').classList.toggle('preview-collapsed', !expanded)
    invalidate()
  }
  const comparePointer = active => {
    pointerCompare = active
    invalidate()
  }
  compare.onpointerenter = event => {
    if (event.pointerType !== 'touch') comparePointer(true)
  }
  compare.onpointerleave = () => comparePointer(false)
  compare.onpointerdown = event => {
    if (event.pointerType === 'touch') {
      compare.setPointerCapture(event.pointerId)
      comparePointer(true)
    }
  }
  compare.onpointerup = event => {
    if (event.pointerType === 'touch') comparePointer(false)
  }
  compare.onpointercancel = () => comparePointer(false)
  compare.onfocus = () => {
    keyboardCompare = compare.matches(':focus-visible')
    invalidate()
  }
  compare.onblur = () => {
    keyboardCompare = false
    invalidate()
  }
  el('apply').onclick = exportResult
  el('download').onclick = () => { if (source) download(source.blob, source.name) }
  el('upload').onclick = () => el('file').click()
  el('file').onchange = event => {
    if (event.target.files[0]) load(event.target.files[0])
    event.target.value = ''
  }
  const stage = el('stage')
  stage.ondragover = event => {
    event.preventDefault()
    stage.classList.add('drag')
  }
  stage.ondragleave = event => {
    if (!stage.contains(event.relatedTarget)) stage.classList.remove('drag')
  }
  stage.ondrop = event => {
    event.preventDefault()
    stage.classList.remove('drag')
    if (event.dataTransfer.files[0]) load(event.dataTransfer.files[0])
  }
  load()
}

try {
  start()
} catch (error) {
  el('preview-status').dataset.state = 'warning'
  el('preview-status').textContent = `无法初始化三维视窗。 ${error.message}`
}
