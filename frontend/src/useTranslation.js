/**
 * Hook que maneja el ciclo completo de traducción con polling.
 * POST → job_id → GET /jobs/:id cada 2s hasta done/error.
 */
import { useState, useRef, useCallback } from 'react'
import { submitTranslation, getJobStatus } from './api.js'

const POLL_MS = 2000

export function useTranslation() {
  const [state, setState] = useState({
    status: 'idle',   // idle | uploading | pending | running | done | error
    result: null,
    error: null,
    jobId: null,
  })
  const timerRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const poll = useCallback((jobId) => {
    timerRef.current = setInterval(async () => {
      try {
        const data = await getJobStatus(jobId)
        if (data.status === 'done' || data.status === 'error') {
          stopPolling()
          setState({
            status: data.status,
            result: data.status === 'done' ? data : null,
            error: data.status === 'error' ? (data.errors?.[0] || 'Error desconocido') : null,
            jobId,
          })
        } else {
          setState(prev => ({ ...prev, status: data.status }))
        }
      } catch (err) {
        stopPolling()
        setState(prev => ({ ...prev, status: 'error', error: err.message }))
      }
    }, POLL_MS)
  }, [stopPolling])

  const translate = useCallback(async (file) => {
    stopPolling()
    setState({ status: 'uploading', result: null, error: null, jobId: null })
    try {
      const { job_id } = await submitTranslation(file)
      setState(prev => ({ ...prev, status: 'pending', jobId: job_id }))
      poll(job_id)
    } catch (err) {
      setState({ status: 'error', result: null, error: err.message, jobId: null })
    }
  }, [stopPolling, poll])

  const reset = useCallback(() => {
    stopPolling()
    setState({ status: 'idle', result: null, error: null, jobId: null })
  }, [stopPolling])

  return { ...state, translate, reset }
}
