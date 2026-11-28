const rangeFields = ['min', 'max', 'step']

export function createParameterControls(root, dialog, changed) {
  const form = dialog.querySelector('form')
  const rangeError = dialog.querySelector('#slider-range-error')
  const sliders = new Map()
  let editing

  function syncThumb({ input, slider }) {
    if (slider && Number.isFinite(input.valueAsNumber)) slider.value = input.value
  }

  function openRange(parameter) {
    editing = parameter
    dialog.querySelector('h2').textContent = `${parameter.name} · 滑块范围`
    for (const field of rangeFields) form.elements[field].value = parameter.slider[field]
    rangeError.textContent = ''
    dialog.showModal()
  }

  form.onsubmit = event => {
    event.preventDefault()
    const [min, max, step] = rangeFields.map(field => form.elements[field].valueAsNumber)
    if (!Number.isFinite(max - min) || !(max > min) || !Number.isFinite(step) || !(step > 0)) {
      rangeError.textContent = '最小值须小于最大值，步长须为正数。'
      return
    }
    Object.assign(editing.slider, { min, max, step })
    syncThumb(editing)
    dialog.close()
  }
  dialog.querySelector('#slider-range-cancel').onclick = () => dialog.close()

  for (const row of root.querySelectorAll('[data-parameter]')) {
    const input = row.querySelector('input[type=number]')
    const slider = row.querySelector('input[type=range]')
    const parameter = { input, slider, name: row.dataset.parameter }
    input.oninput = () => {
      syncThumb(parameter)
      changed()
    }
    if (slider) {
      parameter.defaults = Object.fromEntries(rangeFields.map(field => [field, slider[field]]))
      sliders.set(slider.id, parameter)
      slider.oninput = () => {
        input.value = slider.value
        changed()
      }
      row.querySelector('[data-range]').onclick = () => openRange(parameter)
    }
    for (const button of row.querySelectorAll('[data-nudge]')) {
      button.onclick = () => {
        const base = Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : Number(input.defaultValue)
        const step = Number(parameter.defaults?.step ?? row.dataset.step)
        const value = base + Number(button.dataset.nudge) * step
        if (Number.isFinite(value)) input.value = Number(value.toPrecision(15))
        input.oninput()
      }
    }
  }

  return {
    snapshot() {
      return Object.fromEntries([...sliders].map(([id, { slider }]) =>
        [id, Object.fromEntries(rangeFields.map(field => [field, slider[field]]))]))
    },
    restore(saved) {
      if (dialog.open) dialog.close()
      for (const [id, parameter] of sliders) {
        Object.assign(parameter.slider, saved?.[id] ?? parameter.defaults)
        syncThumb(parameter)
      }
    },
    set(sliderId, value) {
      const { input } = sliders.get(sliderId)
      input.value = value
      input.oninput()
    }
  }
}
