import { UNIT_TO_MM } from './profile.js'
import sample from './sample-sections.json'

export async function matchesSample(bytes) {
  if (!globalThis.crypto?.subtle) return false
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  const hex = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('')
  return hex === sample.sha256
}

export function createSectionSession(geometry, changed) {
  let worker
  let latest
  let running
  let failed = false
  const cache = new Map()

  function schedule() {
    if (failed || running || !latest || cache.has(latest.key)) return
    if (!worker) {
      worker = new Worker(new URL('./section-worker.js', import.meta.url), { type: 'module' })
      worker.onmessage = ({ data }) => {
        cache.set(data.key, data)
        if (cache.size > 128) cache.delete(cache.keys().next().value)
        running = null
        if (latest?.key === data.key) changed()
        schedule()
      }
      worker.onerror = () => {
        failed = true
        worker.terminate()
        changed()
      }
      const positions = geometry.attributes.position.array.slice()
      worker.postMessage({ positions }, [positions.buffer])
    }
    running = latest.key
    worker.postMessage(latest)
  }

  return {
    get(params, isVerifiedSample) {
      const red = params.yellow + params.offset
      const step = Math.round(red * 10)
      const entry = sample.sections[step - sample.firstTenth]
      if (isVerifiedSample && params.union && params.unit === sample.unit &&
          Math.abs(red * 10 - step) < 1e-8 && entry) {
        latest = null
        if (!Array.isArray(entry)) return { message: '已合并样件在此高度没有唯一有效截面。' }
        return { left: entry[0], right: entry[1], prepared: true }
      }
      const key = `${params.unit}:${red}`
      if (cache.has(key)) {
        latest = null
        return cache.get(key)
      }
      if (failed) return { message: '截面计算线程不可用。' }
      latest = { key, red, scale: UNIT_TO_MM[params.unit] }
      schedule()
      return null
    },
    dispose() { worker?.terminate() }
  }
}
