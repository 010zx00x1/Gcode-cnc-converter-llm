/**
 * Vista lado a lado: código Fanuc original vs Siemens traducido.
 * El código Siemens tiene botón de descarga.
 */
import styles from './CodeDisplay.module.css'

export default function CodeDisplay({ original, translated, filename }) {
  function download() {
    const name = filename ? filename.replace(/\.[^.]+$/, '') + '_siemens.mpf' : 'traduccion.mpf'
    const blob = new Blob([translated], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={styles.wrapper}>
      <Pane title="Fanuc (original)" code={original} lang="fanuc" />
      <Pane title="Siemens 840D (traducido)" code={translated} lang="siemens" onDownload={download} />
    </div>
  )
}

function Pane({ title, code, lang, onDownload }) {
  return (
    <div className={styles.pane}>
      <div className={styles.header}>
        <span className={`${styles.badge} ${styles[lang]}`}>{title}</span>
        {onDownload && (
          <button className={styles.dlBtn} onClick={onDownload} title="Descargar .mpf">
            ↓ Descargar
          </button>
        )}
      </div>
      <pre className={styles.code}><code>{code || '(vacío)'}</code></pre>
    </div>
  )
}
