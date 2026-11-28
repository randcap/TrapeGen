import { createViewer } from './viewer.js'
import { buildProfile, checkProfile, UNIT_TO_MM } from './profile.js'
import { selectAb } from './section.js'
import { createSectionSession, matchesSample } from './section-session.js'
import { createModelPose } from './model-pose.js'
import { createConnectorControls } from './connector-controls.js'
import { createConnectorSurfaceSession } from './connector-surface.js'
import { createModelPicker } from './model-picker.js'
import { checked, requestClippedModel, requestConnectorSurface } from './model-api.js'
import { renderModelThumbnail } from './thumbnail-studio.js'

const el = id => document.getElementById(id)
const params = () => ({
  unit: el('unit').value, yellow: el('yellow').valueAsNumber, blue: el('blue').valueAsNumber,
  angle: el('angle').valueAsNumber, offset: el('offset').valueAsNumber, union: el('union').checked,
  ab_z_range_mm: el('ab-enabled').checked ? ['ab-min', 'ab-max'].map(id => el(id).valueAsNumber) : null
})

const rangeFields = ['ab-min', 'ab-max'].map(id => ({ number: el(id), slider: el(`${id}-slider`) }))
const valueFields = ['unit', 'yellow', 'blue', 'offset', 'angle', 'ab-min', 'ab-max', 'opacity', 'pose-step']

const cutSettings = (model, current) => ({ ...current, transform: model.pose.toRows(UNIT_TO_MM[current.unit]) })

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
  let selectionIntent = 0
  let importQueue = Promise.resolve()
  let loading = false
  let loadStatus = ''
  let dirty = false
  let expanded = true
  let pointerCompare = false
  let keyboardCompare = false
  let abCache
  const compare = el('compare')
  const inset = el('comparison-inset')
  const insetLabel = inset.querySelector('figcaption')
  const poseButtons = [...document.querySelectorAll('[data-pose-axis]')]
  const poseStep = el('pose-step')
  const main = document.querySelector('main')
  const sidebar = main.querySelector('aside')
  const surfaces = createConnectorSurfaceSession(requestConnectorSurface, invalidate)
  const connector = createConnectorControls(el('connector-panel'), el('connector-palette'), invalidate, surfaces.retry)
  const picker = createModelPicker(el('model-picker'), el('model-picker-toggle'), model => {
    selectionIntent++
    loadStatus = ''
    activateModel(model)
  })

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

  function displayPreview(current, profile, outline, ab, surface, placement) {
    const editing = expanded || connector.open
    compare.hidden = !editing
    compare.disabled = !editing || !profile
    if (compare.disabled) pointerCompare = keyboardCompare = false
    const comparing = pointerCompare || keyboardCompare
    compare.setAttribute('aria-pressed', comparing)
    inset.hidden = compare.disabled || comparing
    const opacity = el('opacity').valueAsNumber
    el('opacityValue').textContent = `${opacity}%`
    const active = !!source && !loading
    const hasFeature = viewer.updatePreview(current, profile, { expanded: active && expanded, comparing,
      connectorMode: active && connector.open,
      surface, placement, opacity: opacity / 100, outline, ab })
    const label = hasFeature ? '加工后' : '裁剪后'
    if (insetLabel.textContent !== label) insetLabel.textContent = label
  }

  function search(outline, range) {
    const [min, max] = range ?? []
    if (!abCache || abCache.outline !== outline || abCache.min !== min || abCache.max !== max) {
      abCache = { outline, min, max, result: selectAb(outline, range) }
    }
    return abCache.result
  }

  function syncBandSliders() {
    el('ab-controls').hidden = !el('ab-enabled').checked
    if (!source) return
    const scale = UNIT_TO_MM[el('unit').value]
    const { min: lower, max: upper } = source.workGeometry.boundingBox
    const min = lower.z * scale
    const max = upper.z * scale
    for (const { number, slider } of rangeFields) {
      slider.min = min
      slider.max = max
      slider.disabled = !(max > min)
      if (Number.isFinite(number.valueAsNumber)) slider.value = number.value
    }
  }

  function syncPoseControls() {
    const unavailable = !source || loading
    const isOriginal = source?.pose.isOriginal ?? true
    el('pose-toggle').disabled = poseStep.disabled = unavailable
    el('pose-reset').disabled = unavailable || isOriginal
    const state = isOriginal ? '原始姿态' : '姿态已调整'
    if (el('pose-state').textContent !== state) el('pose-state').textContent = state
    const degrees = poseStep.valueAsNumber
    for (const button of poseButtons) button.disabled = unavailable || !Number.isFinite(degrees) || degrees <= 0
  }

  function disposeWorkMesh(model) {
    model.sections?.dispose()
    if (model.workGeometry !== model.originalGeometry) model.workGeometry?.dispose()
  }

  function updateWorkMesh(fitView) {
    const { originalGeometry, pose } = source
    const geometry = pose.isOriginal ? originalGeometry : originalGeometry.clone().applyMatrix4(pose.matrix)
    disposeWorkMesh(source)
    source.workGeometry = geometry
    source.sections = createSectionSession(geometry, invalidate)
    abCache = null
    viewer.show(geometry, { fitView })
    syncBandSliders()
    syncPoseControls()
    invalidate()
  }

  function updatePreview() {
    if (!dirty) return
    dirty = false
    const current = params()
    el('offsetValue').textContent = `${current.offset.toFixed(1)} mm`
    el('angleValue').textContent = `${current.angle.toFixed(1)}°`
    el('download').disabled = !source || loading
    const status = source?.exporting ? source.exportStatus : loadStatus || source?.exportStatus || ''
    if (el('status').textContent !== status) el('status').textContent = status
    const editing = expanded || connector.open
    main.classList.toggle('connector-active', connector.open)
    main.classList.toggle('preview-collapsed', !editing)
    el('export-actions').hidden = !editing
    const active = source && !loading
    const error = active ? checkProfile(current) : null
    const surfaceModel = active && connector.open && !error ? source : null
    const state = surfaces.update(surfaceModel, surfaceModel && cutSettings(source, current))
    const { placement, invalid } = connector.update(state, active ? error : '请先加载 STL。')
    if (!active || !editing) {
      el('apply').disabled = true
      displayPreview({ ...current, ab_z_range_mm: null }, null)
      return
    }

    el('apply').disabled = source.exporting || !!error || !!invalid
    const section = error ? null : source.sections.get(current, source.verifiedSample && source.pose.isOriginal)
    const outline = section?.outline
    const selection = outline ? search(outline, current.ab_z_range_mm) : section
    const profile = selection && !selection.message ? buildProfile(current, selection) : null
    const ab = current.ab_z_range_mm ? selection : null
    displayPreview(current, profile, outline, ab, state.surface, placement)
    const bounds = ab?.a && ab?.b
      ? [ab.a, ab.b].map(({ x, z }, i) => `${i ? 'B' : 'A'}  X ${x.toFixed(4)} · Z ${z.toFixed(4)} mm`).join('\n')
      : profile ? `截面 X  ${profile.left.toFixed(4)} ～ ${profile.right.toFixed(4)} mm` : ''
    if (error || selection?.message) {
      const approximate = current.union && !section?.prepared && !error
      const message = error || selection.message
      previewStatus('warning', approximate ? `${message} 合并外壳后可能变化。` : message, bounds)
      if (ab?.message && !approximate) el('apply').disabled = true
    } else if (!section) {
      previewStatus('pending', current.ab_z_range_mm ? '正在准备当前红线截面的外轮廓…' : '正在计算当前红线截面…')
    } else if (!profile) {
      const approximate = current.ab_z_range_mm && current.union && !section.prepared
      const message = '梯形上底须为正宽度，请调整高度或角度。'
      previewStatus('warning', approximate ? `${message} 合并外壳后可能变化。` : message, bounds)
      el('apply').disabled ||= !approximate
    } else if (current.union && !section.prepared) {
      previewStatus('warning', '近似预览 · 导出时会合并外壳，截面可能变化。', bounds)
    } else {
      previewStatus('ready', section.prepared ? '实时预览 · 样件已合并截面' : '实时预览 · 浏览器截面', bounds)
    }
  }

  function setLoading(value) {
    loading = value
    sidebar.inert = el('connector-palette').inert = value
    el('pose-controls').hidePopover?.()
    syncPoseControls()
    invalidate()
  }

  function saveDraft() {
    source.values = Object.fromEntries(valueFields.map(id => [id, el(id).value]))
    source.union = el('union').checked
    source.abEnabled = el('ab-enabled').checked
    connector.saveDraft()
  }

  async function activateModel(model, preparedGeometry) {
    const id = ++loadId
    picker.highlight(model)
    if (source === model) {
      setLoading(false)
      return
    }
    if (source && !loading) saveDraft()
    surfaces.update(null)
    setLoading(true)
    previewStatus('pending', `正在读取 ${model.name}…`)
    let geometry = preparedGeometry
    try {
      if (!geometry) {
        const bytes = await model.blob.arrayBuffer()
        if (id !== loadId) return
        geometry = viewer.parse(bytes)
      }
      if (id !== loadId) return
      const previous = source
      source = model
      source.originalGeometry = geometry
      geometry = null
      el('name').textContent = model.name
      el('count').textContent = `${model.faceCount.toLocaleString()} 个三角面`
      main.dataset.activeModelId = model.id
      for (const [field, value] of Object.entries(model.values)) el(field).value = value
      el('union').checked = model.union
      el('ab-enabled').checked = model.abEnabled
      connector.restoreDraft(model.connector)
      pointerCompare = keyboardCompare = false
      setMode('view')
      updateWorkMesh(true)
      if (previous) {
        disposeWorkMesh(previous)
        previous.originalGeometry.dispose()
        previous.sections = previous.workGeometry = previous.originalGeometry = undefined
      }
    } catch (error) {
      if (id !== loadId) return
      loadStatus = `无法打开 ${model.name}。 ${error.message}`
      if (source) picker.highlight(source)
    } finally {
      geometry?.dispose()
      if (id === loadId) {
        setLoading(false)
        if (!source) previewStatus('warning', '请打开一个有效的 STL 文件。')
      }
    }
  }

  function importModels(files) {
    if (!files.length) return
    const intent = ++selectionIntent
    loadStatus = ''
    importQueue = importQueue.then(async () => {
      for (const file of files) {
        const name = file?.name || 'xiong.stl'
        let geometry
        try {
          const blob = file || await (await checked('/sample.stl')).blob()
          const bytes = await blob.arrayBuffer()
          const verifiedSample = await matchesSample(bytes).catch(() => false)
          geometry = viewer.parse(bytes)
          const box = geometry.boundingBox
          const dy = box.max.y - box.min.y
          const demo = !file || verifiedSample
          let thumbnail
          try {
            thumbnail = renderModelThumbnail(geometry)
          } catch (error) {
            console.warn('无法生成模型缩略图', error)
          }
          const model = picker.add({ blob, name, thumbnail, sample: !file, verifiedSample, faceCount: geometry.attributes.position.count / 3,
            pose: createModelPose(box), connector: connector.createDraft(), union: demo, abEnabled: false,
            values: {
              unit: demo ? 'cm' : 'mm',
              yellow: demo ? 69 : (box.min.y + dy * 0.55).toFixed(3),
              blue: demo ? 87 : (box.min.y + dy * 0.85).toFixed(3),
              offset: 7.5, angle: 53, 'ab-min': demo ? -12 : box.min.z, 'ab-max': demo ? 12 : box.max.z,
              opacity: 20, 'pose-step': 90
            } })
          if (!source || intent === selectionIntent) {
            const prepared = geometry
            geometry = null
            await activateModel(model, prepared)
          }
        } catch (error) {
          if (!source || intent === selectionIntent) {
            loadStatus = `无法打开 ${name}。 ${error.message}`
            if (!source) previewStatus('warning', '请打开一个有效的 STL 文件。')
            invalidate()
          }
        } finally {
          geometry?.dispose()
        }
      }
    })
  }

  async function exportResult() {
    if (!source || loading || source.exporting) return
    const model = source
    const settings = params()
    const error = checkProfile(settings)
    if (error) {
      model.exportStatus = error
      invalidate()
      return
    }
    // Hold the clicked file and parameters while the upload and export run.
    const payload = cutSettings(model, settings)
    if (connector.open) {
      const { spec, error } = connector.read()
      if (error) {
        model.exportStatus = error
        invalidate()
        return
      }
      payload.connector = spec
    }
    model.exporting = true
    loadStatus = ''
    el('apply').disabled = true
    model.exportStatus = `正在生成并校验 ${model.name} 的裁剪件…`
    invalidate()
    try {
      const clipped = await requestClippedModel(model, payload)
      const name = model.name.replace(/\.stl$/i, '') + '-clipped.stl'
      download(clipped, name)
      model.exportStatus = `已导出 ${name}`
    } catch (error) {
      model.exportStatus = `导出失败。 ${error.message}`
    } finally {
      model.exporting = false
      if (source === model) invalidate()
    }
  }

  const modeButtons = [...document.querySelectorAll('[data-edit]')]
  function setMode(mode) {
    viewer.setMode(mode)
    for (const button of modeButtons) button.setAttribute('aria-pressed', button.dataset.edit === mode)
  }

  for (const button of modeButtons) button.onclick = () => setMode(button.dataset.edit)
  poseStep.oninput = syncPoseControls
  for (const button of poseButtons) button.onclick = () => {
    if (!source || loading || button.disabled) return
    source.pose.rotate(button.dataset.poseAxis, Number(button.dataset.direction) * poseStep.valueAsNumber)
    updateWorkMesh(false)
  }
  el('pose-reset').onclick = () => {
    if (!source || loading) return
    source.pose.reset()
    updateWorkMesh(false)
  }
  for (const id of ['angle', 'offset', 'yellow', 'blue', 'union', 'opacity']) el(id).oninput = invalidate
  function updateBandInputs() {
    syncBandSliders()
    invalidate()
  }
  for (const id of ['unit', 'ab-enabled']) el(id).oninput = updateBandInputs
  for (const { number, slider } of rangeFields) {
    number.oninput = updateBandInputs
    slider.oninput = () => {
      number.value = Number(slider.valueAsNumber.toFixed(3))
      invalidate()
    }
  }
  for (const id of ['fit', 'side', 'front', 'top']) el(id).onclick = viewer[id]
  const toggle = el('toggle-preview')
  toggle.onclick = () => {
    expanded = !expanded
    toggle.setAttribute('aria-expanded', expanded)
    el('preview-body').inert = !expanded
    el('edit-tools').hidden = !expanded
    main.classList.toggle('crop-collapsed', !expanded)
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
    importModels([...event.target.files])
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
    importModels([...event.dataTransfer.files])
  }
  importModels([null])
}

try {
  start()
} catch (error) {
  el('preview-status').dataset.state = 'warning'
  el('preview-status').textContent = `无法初始化三维视窗。 ${error.message}`
}
