/**
 * Barra de estado del job con spinner y mensajes.
 */
import styles from './StatusBar.module.css'

const MESSAGES = {
  idle:      '',
  uploading: 'Subiendo archivo...',
  pending:   'En cola — iniciando pipeline...',
  running:   'Traduciendo: parse → translate → simulate...',
  done:      'Traducción completa',
  error:     'Error en la traducción',
}

export default function StatusBar({ status, error }) {
  if (status === 'idle') return null

  const isActive = status === 'uploading' || status === 'pending' || status === 'running'
  const isError  = status === 'error'
  const isDone   = status === 'done'

  return (
    <div className={`${styles.bar} ${isError ? styles.error : ''} ${isDone ? styles.done : ''}`}>
      {isActive && <span className={styles.spinner} />}
      {isDone && <span className={styles.check}>✓</span>}
      {isError && <span className={styles.x}>✕</span>}
      <span className={styles.msg}>
        {isError ? (error || MESSAGES.error) : MESSAGES[status]}
      </span>
    </div>
  )
}
