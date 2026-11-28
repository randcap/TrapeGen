import { CarouselSelector } from './carousel-selector.js'

export function createModelPicker(panel, toggle, dialog, { selectModel, deleteModel }) {
  const models = []
  let nextId = 1
  let selected
  let candidate
  const carousel = new CarouselSelector(panel, {
    label: '暂存模型', style: { 'item-width': 'var(--model-card-width, 142px)' },
    onChange: index => selectModel(models[index])
  })
  panel.addEventListener('toggle', () => {
    const open = panel.matches(':popover-open')
    toggle.setAttribute('aria-expanded', open)
    if (open) focusSelected()
  })

  function focusSelected() {
    panel.querySelector('[aria-pressed=true]')?.focus({ preventScroll: true })
  }

  function confirmRemoval(model, title) {
    candidate = model
    dialog.querySelector('#model-delete-name').textContent = title
    dialog.querySelector('#model-delete-export').hidden = !model.exporting
    dialog.returnValue = ''
    dialog.showModal()
  }

  dialog.addEventListener('close', () => {
    const model = candidate
    candidate = undefined
    if (dialog.returnValue === 'delete' && models.includes(model)) deleteModel(model)
    if (models.length && !panel.matches(':popover-open')) panel.showPopover()
    if (models.length && panel.matches(':popover-open')) focusSelected()
  })

  function syncItems() {
    const counts = new Map()
    for (const { name } of models) counts.set(name, (counts.get(name) ?? 0) + 1)
    const ordinals = new Map()
    carousel.setItems(models.map(model => {
      const { id, name, thumbnail } = model
      const ordinal = (ordinals.get(name) ?? 0) + 1
      ordinals.set(name, ordinal)
      const title = counts.get(name) > 1 ? `${name} (${ordinal})` : name
      return { id, name: title, thumbnail, icon: '◇', action: {
        icon: '×', label: `删除 ${title}`, onClick: () => confirmRemoval(model, title)
      } }
    }), models.indexOf(selected))
    toggle.disabled = !models.length
    if (!models.length) panel.hidePopover()
  }

  return {
    get selected() { return selected },
    add(entry) {
      const model = { ...entry, id: `model-${nextId++}` }
      models.push(model)
      syncItems()
      return model
    },
    remove(model, preferred) {
      const index = models.indexOf(model)
      if (index < 0) return selected
      models.splice(index, 1)
      if (selected === model) selected = models.includes(preferred) ? preferred : models[index] ?? models[index - 1]
      syncItems()
      return selected
    },
    highlight(model) {
      selected = model
      carousel.setSelectedIndex(models.indexOf(model))
    }
  }
}
