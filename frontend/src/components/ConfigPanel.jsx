/**
 * Panel de configuración del LLM.
 * Lee y escribe en /api/config (→ llm_config.json).
 */
import { useState, useEffect } from 'react'
import { getConfig, updateConfig } from '../api.js'
import styles from './ConfigPanel.module.css'

export default function ConfigPanel({ onClose }) {
  const [cfg, setCfg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getConfig()
      .then(setCfg)
      .catch(e => setError(e.message))
  }, [])

  async function save() {
    setSaving(true)
    setError('')
    try {
      await updateConfig(cfg)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  function set(key, value) {
    setCfg(prev => ({ ...prev, [key]: value }))
  }

  if (!cfg) return (
    <div className={styles.modal}>
      <div className={styles.box}>
        {error ? <p className={styles.err}>{error}</p> : <p className={styles.loading}>Cargando...</p>}
      </div>
    </div>
  )

  const providers = cfg.available_providers || []

  return (
    <div className={styles.modal} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.box}>
        <div className={styles.head}>
          <h2>Configuración LLM</h2>
          <button className={styles.close} onClick={onClose}>✕</button>
        </div>

        <div className={styles.body}>
          <label className={styles.field}>
            <span>Provider</span>
            <select value={cfg.provider} onChange={e => set('provider', e.target.value)}>
              {providers.map(p => (
                <option key={p.id} value={p.id}>{p.id}</option>
              ))}
            </select>
          </label>

          <label className={styles.field}>
            <span>Modelo</span>
            <select value={cfg.model} onChange={e => set('model', e.target.value)}>
              {(providers.find(p => p.id === cfg.provider)?.models || [cfg.model]).map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>

          <label className={styles.field}>
            <span>Temperature <em>{cfg.temperature}</em></span>
            <input
              type="range" min="0" max="1" step="0.05"
              value={cfg.temperature}
              onChange={e => set('temperature', parseFloat(e.target.value))}
            />
          </label>

          <label className={styles.field}>
            <span>Max tokens</span>
            <input
              type="number" min="256" max="8192" step="256"
              value={cfg.max_tokens}
              onChange={e => set('max_tokens', parseInt(e.target.value))}
            />
          </label>

          <label className={styles.field}>
            <span>Timeout (s)</span>
            <input
              type="number" min="10" max="120" step="5"
              value={cfg.timeout_seconds}
              onChange={e => set('timeout_seconds', parseInt(e.target.value))}
            />
          </label>

          <p className={styles.note}>
            Las API keys se configuran en el archivo <code>.env</code> del backend.
          </p>

          {error && <p className={styles.err}>{error}</p>}
        </div>

        <div className={styles.foot}>
          <button className={styles.cancel} onClick={onClose}>Cancelar</button>
          <button className={styles.save} onClick={save} disabled={saving}>
            {saving ? 'Guardando...' : saved ? '✓ Guardado' : 'Guardar'}
          </button>
        </div>
      </div>
    </div>
  )
}
