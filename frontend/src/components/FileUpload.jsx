/**
 * Zona de drag & drop para subir archivos .nc/.mpf/.txt
 */
import { useRef, useState } from 'react'
import styles from './FileUpload.module.css'

const ACCEPTED = ['.nc', '.mpf', '.txt']

export default function FileUpload({ onFile, disabled }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function handleFile(file) {
    if (!file) return
    const ext = '.' + file.name.split('.').pop().toLowerCase()
    if (!ACCEPTED.includes(ext)) {
      alert(`Extensión no soportada. Usa: ${ACCEPTED.join(', ')}`)
      return
    }
    onFile(file)
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    handleFile(e.dataTransfer.files[0])
  }

  function onDragOver(e) {
    e.preventDefault()
    setDragging(true)
  }

  return (
    <div
      className={`${styles.zone} ${dragging ? styles.dragging : ''} ${disabled ? styles.disabled : ''}`}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={() => setDragging(false)}
      onClick={() => !disabled && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED.join(',')}
        style={{ display: 'none' }}
        onChange={e => handleFile(e.target.files[0])}
      />
      <div className={styles.icon}>⚙</div>
      <p className={styles.label}>
        Arrastra tu archivo G-code Fanuc aquí<br />
        <span className={styles.sub}>o haz clic para seleccionar</span>
      </p>
      <p className={styles.formats}>{ACCEPTED.join('  •  ')}</p>
    </div>
  )
}
