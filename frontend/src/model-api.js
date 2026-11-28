import { parseConnectorSurface } from './connector.js'

const uploads = new WeakMap()

export async function checked(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) {
    const error = Error(await response.text() || response.statusText)
    error.status = response.status
    throw error
  }
  return response
}

const postJson = (url, data) => checked(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
})

async function upload(model) {
  if (model.uploadId) return model.uploadId
  if (!uploads.has(model)) {
    const request = checked('/api/upload', {
      method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: model.blob
    }).then(response => response.json()).then(({ model: id }) => {
      model.uploadId = id
      return id
    }).finally(() => uploads.delete(model))
    uploads.set(model, request)
  }
  return uploads.get(model)
}

async function requestForModel(path, model, settings, useSample = false) {
  const id = useSample ? 'xiong' : await upload(model)
  try {
    return await postJson(path, { model: id, ...settings })
  } catch (error) {
    if (useSample || error.status !== 422 || !error.message.includes('模型已过期')) throw error
    if (model.uploadId === id) model.uploadId = undefined
    return postJson(path, { model: await upload(model), ...settings })
  }
}

export async function requestConnectorSurface(model, settings) {
  const response = await requestForModel('/api/connector-surface', model, settings, model.sample)
  return parseConnectorSurface(await response.json())
}

export async function requestClippedModel(model, settings) {
  const response = await requestForModel('/api/clip', model, settings)
  return response.blob()
}
