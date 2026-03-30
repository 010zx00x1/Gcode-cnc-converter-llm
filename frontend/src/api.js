/**
 * API client para el backend CNC Post-Processor.
 */

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

/** Sube archivo .nc y recibe job_id */
export async function submitTranslation(file) {
  const form = new FormData()
  form.append('file', file)
  return request('/api/translate', { method: 'POST', body: form })
}

/** Polling: retorna estado/resultado del job */
export async function getJobStatus(jobId) {
  return request(`/api/jobs/${jobId}`)
}

/** Configuración LLM */
export async function getConfig() {
  return request('/api/config')
}

export async function updateConfig(config) {
  return request('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
}

export async function getHealth() {
  return request('/api/health')
}
