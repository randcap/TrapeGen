import { CarouselSelector } from './carousel-selector.js'

export function createModelPicker(panel, toggle, selectModel) {
  const models = []
  let selectedIndex = -1
  const carousel = new CarouselSelector(panel, {
    label: '暂存模型', style: { 'item-width': 'var(--model-card-width, 142px)' },
    onChange: index => selectModel(models[index])
  })
  panel.addEventListener('toggle', () => {
    const open = panel.matches(':popover-open')
    toggle.setAttribute('aria-expanded', open)
    if (open) panel.querySelector('[aria-pressed=true]')?.focus({ preventScroll: true })
  })

  return {
    add(entry) {
      const model = { ...entry, id: `model-${models.length + 1}` }
      models.push(model)
      const counts = new Map()
      for (const { name } of models) counts.set(name, (counts.get(name) ?? 0) + 1)
      const ordinals = new Map()
      carousel.setItems(models.map(({ id, name, thumbnail }) => {
        const ordinal = (ordinals.get(name) ?? 0) + 1
        ordinals.set(name, ordinal)
        return { id, name: counts.get(name) > 1 ? `${name} (${ordinal})` : name, thumbnail, icon: '◇' }
      }), selectedIndex)
      toggle.disabled = false
      return model
    },
    highlight(model) {
      selectedIndex = models.indexOf(model)
      carousel.setSelectedIndex(selectedIndex)
    }
  }
}
