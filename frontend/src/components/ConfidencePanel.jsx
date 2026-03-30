/**
 * Panel de confianza: score circular + métricas clave.
 */
import styles from './ConfidencePanel.module.css'

const COLORS = {
  ALTA:     '#3ecf8e',
  MEDIA:    '#f0a500',
  BAJA:     '#f75a5a',
  'MUY BAJA': '#8b0000',
}

export default function ConfidencePanel({ result }) {
  const { confidence, confidence_label, max_deviation_mm, avg_deviation_mm, attempts_used, warnings } = result
  const pct = Math.round(confidence * 100)
  const color = COLORS[confidence_label] || '#6b7a99'
  const circumference = 2 * Math.PI * 36

  return (
    <div className={styles.panel}>
      <h3 className={styles.title}>Confianza de traducción</h3>

      <div className={styles.scoreRow}>
        {/* Círculo SVG */}
        <svg viewBox="0 0 80 80" className={styles.ring}>
          <circle cx="40" cy="40" r="36" fill="none" stroke="var(--border)" strokeWidth="6" />
          <circle
            cx="40" cy="40" r="36"
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - confidence)}
            transform="rotate(-90 40 40)"
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
          />
          <text x="40" y="44" textAnchor="middle" fill={color} fontSize="14" fontWeight="bold">
            {pct}%
          </text>
        </svg>

        <div className={styles.label} style={{ color }}>
          {confidence_label}
        </div>
      </div>

      <div className={styles.metrics}>
        <Metric label="Desviación máx." value={`${max_deviation_mm.toFixed(4)} mm`} />
        <Metric label="Desviación prom." value={`${avg_deviation_mm.toFixed(4)} mm`} />
        <Metric label="Intentos LLM" value={attempts_used} />
      </div>

      {warnings.length > 0 && (
        <div className={styles.warnings}>
          <p className={styles.warnTitle}>Advertencias ({warnings.length})</p>
          <ul>
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={styles.metricValue}>{value}</span>
    </div>
  )
}
