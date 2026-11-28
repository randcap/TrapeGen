export function createConnectorSurfaceSession(fetchSurface, changed, delay = 300) {
  let current = null
  let state = {}
  let timer
  let running = false

  function schedule() {
    clearTimeout(timer)
    // The server serializes geometry jobs. Submit only the latest context after an in-flight job settles.
    if (!current || running) return
    timer = setTimeout(async () => {
      const request = current
      running = true
      try {
        const surface = await fetchSurface(request.model, request.settings)
        if (current === request) state = { surface }
      } catch (error) {
        if (current === request) state = { error: error.message }
      } finally {
        running = false
        if (current === request) changed()
        else schedule()
      }
    }, delay)
  }

  return {
    update(model, settings) {
      if (!model) {
        if (current) {
          current = null
          state = {}
          clearTimeout(timer)
        }
        return state
      }
      const key = JSON.stringify(settings)
      if (current?.model !== model || current.key !== key) {
        current = { model, settings, key }
        state = { pending: true }
        schedule()
      }
      return state
    },

    retry() {
      if (current && state.error) {
        state = { pending: true }
        schedule()
        changed()
      }
    }
  }
}
