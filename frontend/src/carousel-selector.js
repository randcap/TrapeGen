import './carousel-selector.css'

function element(tag, className) {
  const node = document.createElement(tag)
  node.className = className
  return node
}

export class CarouselSelector {
  constructor(host, { items = [], selectedIndex = 0, onChange, label = '栏目选择', style = {} } = {}) {
    this.root = element('div', 'carousel-selector')
    this.root.role = 'group'
    this.root.setAttribute('aria-label', label)
    for (const [name, value] of Object.entries(style)) this.root.style.setProperty(`--carousel-${name}`, value)

    this.viewport = element('div', 'carousel-viewport')
    this.track = element('div', 'carousel-track')
    const window = element('div', 'carousel-window')
    const indicator = element('div', 'carousel-indicator')
    indicator.setAttribute('aria-hidden', 'true')
    this.viewport.append(this.track)
    window.append(this.viewport, indicator)

    const arrow = (text, name, step) => {
      const button = element('button', 'carousel-arrow')
      button.type = 'button'
      button.textContent = text
      button.setAttribute('aria-label', name)
      button.onclick = () => this.select(this.selectedIndex + step)
      return button
    }
    this.previous = arrow('‹', '上一项', -1)
    this.next = arrow('›', '下一项', 1)
    this.root.append(this.previous, window, this.next)
    host.append(this.root)

    this.onChange = onChange
    this.root.onkeydown = event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault()
      this.select(this.selectedIndex + (event.key === 'ArrowLeft' ? -1 : 1))
    }
    let wheelOffset = 0
    let lastWheel = -Infinity
    this.root.addEventListener('wheel', event => {
      if (event.ctrlKey || !this.items.length) return
      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
      if (!delta) return
      event.preventDefault()
      if (event.timeStamp - lastWheel > 180 || Math.sign(wheelOffset) !== Math.sign(delta)) wheelOffset = 0
      lastWheel = event.timeStamp
      wheelOffset += delta * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? this.viewport.clientWidth : 1)
      if (Math.abs(wheelOffset) >= 36) {
        this.select(this.selectedIndex + Math.sign(wheelOffset))
        wheelOffset = 0
      }
    }, { passive: false })

    let touch
    let swiped = false
    this.viewport.onpointerdown = event => {
      swiped = false
      if (event.pointerType === 'touch' && event.isPrimary) {
        touch = { id: event.pointerId, x: event.clientX, y: event.clientY }
      }
    }
    this.viewport.onpointercancel = () => { touch = undefined }
    this.viewport.onpointerup = event => {
      if (touch?.id !== event.pointerId) return
      const x = event.clientX - touch.x
      const y = event.clientY - touch.y
      touch = undefined
      if (Math.abs(x) < 24 || Math.abs(x) <= Math.abs(y)) return
      swiped = true
      this.select(this.selectedIndex - Math.sign(x))
    }
    this.viewport.addEventListener('click', event => {
      if (swiped && event.pointerType === 'touch') event.stopPropagation()
    }, true)

    this.setItems(items, selectedIndex)
    this.resizeObserver = new ResizeObserver(() => this.position(false))
    this.resizeObserver.observe(this.viewport)
    this.resizeObserver.observe(this.track)
  }

  setItems(items, index = this.selectedIndex) {
    const hadItemFocus = this.track.contains(document.activeElement)
    this.items = [...items]
    this.buttons = this.items.map(({ id, name, thumbnail, icon }, i) => {
      const button = element('button', 'carousel-card')
      button.type = 'button'
      button.dataset.itemId = id
      button.title = name
      const artwork = element('span', 'carousel-artwork')
      artwork.setAttribute('aria-hidden', 'true')
      if (thumbnail) {
        const image = document.createElement('img')
        image.src = thumbnail
        image.alt = ''
        image.draggable = false
        artwork.append(image)
      } else if (icon instanceof Node) artwork.append(icon.cloneNode(true))
      else if (icon) artwork.textContent = icon
      const title = element('span', 'carousel-name')
      title.textContent = name
      button.append(artwork, title)
      button.onclick = () => this.select(i)
      return button
    })
    this.track.replaceChildren(...this.buttons)
    this.setSelectedIndex(index, { animate: false })
    if (hadItemFocus) this.buttons[this.selectedIndex]?.focus({ preventScroll: true })
  }

  position(animate = true) {
    const button = this.buttons[this.selectedIndex]
    if (!button || !this.viewport.clientWidth) return
    const x = (this.viewport.clientWidth - button.offsetWidth) / 2 - button.offsetLeft
    const transform = `translateX(${x}px)`
    if (this.track.style.transform === transform) return
    if (!animate) this.track.style.transition = 'none'
    this.track.style.transform = transform
    if (!animate) {
      this.track.getBoundingClientRect()
      this.track.style.removeProperty('transition')
    }
  }

  setSelectedIndex(index, { animate = true } = {}) {
    const hadItemFocus = this.track.contains(document.activeElement)
    const requested = Number.isFinite(index) ? Math.trunc(index) : 0
    this.selectedIndex = this.items.length ? Math.max(0, Math.min(this.items.length - 1, requested)) : -1
    this.buttons.forEach((button, i) => {
      const selected = i === this.selectedIndex
      button.setAttribute('aria-pressed', selected)
      button.tabIndex = selected ? 0 : -1
    })
    this.previous.setAttribute('aria-disabled', this.selectedIndex <= 0)
    this.next.setAttribute('aria-disabled', this.selectedIndex < 0 || this.selectedIndex === this.items.length - 1)
    this.position(animate)
    if (hadItemFocus) this.buttons[this.selectedIndex]?.focus({ preventScroll: true })
  }

  select(index) {
    const before = this.selectedIndex
    this.setSelectedIndex(index)
    if (this.selectedIndex !== before) this.onChange?.(this.selectedIndex, this.items[this.selectedIndex])
  }

  destroy() {
    this.resizeObserver.disconnect()
    this.root.remove()
  }
}
