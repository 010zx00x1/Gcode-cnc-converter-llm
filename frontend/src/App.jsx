/**
 * App principal del CNC Post-Processor.
 * Layout: header | upload | status | [resultados cuando done]
 */
import { useState, useCallback } from 'react'
import { useTranslation } from './useTranslation.js'
import FileUpload from './components/FileUpload.jsx'
import StatusBar from './components/StatusBar.jsx'
import Visualizer3D from './components/Visualizer3D.jsx'
import CodeDisplay from './components/CodeDisplay.jsx'
import ConfidencePanel from './components/ConfidencePanel.jsx'
import ConfigPanel from './components/ConfigPanel.jsx'
import styles from './App.module.css'

export default function App() {
  const { status, result, error, translate, reset } = useTranslation()
  const [filename, setFilename] = useState('')
  const [originalCode, setOriginalCode] = useState('')
  const [showConfig, setShowConfig] = useState(false)
  const [activeTab, setActiveTab] = useState('visual') // 'visual' | 'code'

  const isProcessing = status === 'uploading' || status === 'pending' || status === 'running'
  const isDone = status === 'done'

  const handleFile = useCallback(async (file) => {
    setFilename(file.name)
    const text = await file.text()
    setOriginalCode(text)
    translate(file)
  }, [translate])

  function handleReset() {
    reset()
    setFilename('')
    setOriginalCode('')
    setActiveTab('visual')
  }

  return (
    <div className={styles.app}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.logo}>⚙</span>
          <div>
            <h1 className={styles.title}>CNC Post-Processor</h1>
            <p className={styles.subtitle}>Fanuc → Siemens 840D con validación geométrica</p>
          </div>
        </div>
        <button className={styles.configBtn} onClick={() => setShowConfig(true)}>
          ⚙ LLM Config
        </button>
      </header>

      <main className={styles.main}>
        {/* Zona de carga */}
        {!isDone && (
          <section className={styles.uploadSection}>
            <FileUpload onFile={handleFile} disabled={isProcessing} />
            {filename && <p className={styles.fileInfo}>Archivo: <strong>{filename}</strong></p>}
          </section>
        )}

        {/* Barra de estado */}
        <StatusBar status={status} error={error} />

        {/* Resultados */}
        {isDone && result && (
          <div className={styles.results}>
            {/* Encabezado resultados */}
            <div className={styles.resultHeader}>
              <div>
                <h2 className={styles.resultTitle}>
                  {filename && <span className={styles.resultFile}>{filename}</span>}
                </h2>
                <p className={styles.resultMeta}>
                  Traducción completada
                </p>
              </div>
              <button className={styles.resetBtn} onClick={handleReset}>
                ← Nueva traducción
              </button>
            </div>

            {/* Layout: panel izquierdo (confianza) + contenido principal */}
            <div className={styles.resultLayout}>
              {/* Panel de confianza */}
              <aside className={styles.sidebar}>
                <ConfidencePanel result={result} />
              </aside>

              {/* Contenido principal: tabs visualizador / código */}
              <div className={styles.content}>
                <div className={styles.tabs}>
                  <button
                    className={`${styles.tab} ${activeTab === 'visual' ? styles.active : ''}`}
                    onClick={() => setActiveTab('visual')}
                  >
                    Visualizador 3D
                  </button>
                  <button
                    className={`${styles.tab} ${activeTab === 'code' ? styles.active : ''}`}
                    onClick={() => setActiveTab('code')}
                  >
                    Código
                  </button>
                </div>

                {activeTab === 'visual' && (
                  <Visualizer3D
                    sourcePoints={result.source_toolpath}
                    translatedPoints={result.translated_toolpath}
                    deviationIndices={result.deviation_points}
                  />
                )}

                {activeTab === 'code' && (
                  <CodeDisplay
                    original={originalCode}
                    translated={result.translated_code}
                    filename={filename}
                  />
                )}
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className={styles.footer}>
        <p>CNC Post-Processor MVP — Fanuc G-code → Siemens 840D</p>
      </footer>

      {/* Modal config */}
      {showConfig && <ConfigPanel onClose={() => setShowConfig(false)} />}
    </div>
  )
}
