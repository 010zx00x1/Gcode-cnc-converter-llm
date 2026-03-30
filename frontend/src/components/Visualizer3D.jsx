/**
 * Visualizador 3D de toolpaths con React Three Fiber.
 * Muestra en azul el toolpath original (Fanuc) y en verde el traducido (Siemens).
 * Los puntos con desviación > threshold se marcan en rojo.
 */
import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Line, GizmoHelper, GizmoViewport } from '@react-three/drei'
import * as THREE from 'three'
import styles from './Visualizer3D.module.css'

// Computa bounding box para centrar la cámara
function computeCenter(points) {
  if (!points || points.length === 0) return [0, 0, 0]
  let minX = Infinity, minY = Infinity, minZ = Infinity
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const [x, y, z] of points) {
    if (x < minX) minX = x; if (x > maxX) maxX = x
    if (y < minY) minY = y; if (y > maxY) maxY = y
    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z
  }
  return [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2]
}

function computeSize(points) {
  if (!points || points.length < 2) return 100
  let maxD = 0
  for (const [x, y, z] of points) {
    const d = Math.sqrt(x * x + y * y + z * z)
    if (d > maxD) maxD = d
  }
  return maxD || 100
}

// Convierte array [[x,y,z]] a Float32Array para Three.js
function toVec3Array(points) {
  if (!points || points.length === 0) return []
  return points.map(([x, y, z]) => new THREE.Vector3(x, z, -y)) // reorder: Y-up para Three.js
}

function ToolpathLine({ points, color, lineWidth = 1.5 }) {
  const vecs = useMemo(() => toVec3Array(points), [points])
  if (vecs.length < 2) return null
  return (
    <Line
      points={vecs}
      color={color}
      lineWidth={lineWidth}
    />
  )
}

function DeviationPoints({ sourcePoints, deviationIndices }) {
  const points = useMemo(() => {
    return deviationIndices
      .filter(i => i < sourcePoints.length)
      .map(i => sourcePoints[i])
  }, [sourcePoints, deviationIndices])

  if (points.length === 0) return null

  return (
    <>
      {points.map((p, i) => (
        <mesh key={i} position={[p[0], p[2], -p[1]]}>
          <sphereGeometry args={[0.8, 8, 8]} />
          <meshBasicMaterial color="#f75a5a" />
        </mesh>
      ))}
    </>
  )
}

function Scene({ sourcePoints, translatedPoints, deviationIndices }) {
  const center = useMemo(() => computeCenter(sourcePoints), [sourcePoints])
  const size   = useMemo(() => computeSize(sourcePoints), [sourcePoints])
  const camDist = size * 2.2

  return (
    <>
      <ambientLight intensity={0.5} />
      <pointLight position={[camDist, camDist, camDist]} intensity={1} />

      {/* Grid helper en el plano XZ */}
      <gridHelper
        args={[size * 3, 20, '#2e3348', '#1a1d27']}
        position={[center[0], 0, -center[1]]}
      />

      {/* Toolpaths */}
      <group position={[-center[0], -center[2], center[1]]}>
        <ToolpathLine points={sourcePoints}     color="#4f8ef7" lineWidth={2} />
        <ToolpathLine points={translatedPoints} color="#38e0c0" lineWidth={1.5} />
        <DeviationPoints sourcePoints={sourcePoints} deviationIndices={deviationIndices || []} />
      </group>

      <OrbitControls makeDefault dampingFactor={0.1} />
      <GizmoHelper alignment="bottom-right" margin={[80, 80]}>
        <GizmoViewport labelColor="white" axisHeadScale={0.8} />
      </GizmoHelper>
    </>
  )
}

export default function Visualizer3D({ sourcePoints, translatedPoints, deviationIndices }) {
  if (!sourcePoints || sourcePoints.length === 0) {
    return (
      <div className={styles.empty}>
        <p>Sin toolpath para mostrar</p>
      </div>
    )
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.legend}>
        <span className={styles.src}>— Original Fanuc</span>
        <span className={styles.dst}>— Traducido Siemens</span>
        {deviationIndices?.length > 0 &&
          <span className={styles.dev}>● Puntos con desviación ({deviationIndices.length})</span>
        }
      </div>
      <Canvas
        className={styles.canvas}
        camera={{ position: [100, 80, 100], fov: 45 }}
        gl={{ antialias: true }}
      >
        <Scene
          sourcePoints={sourcePoints}
          translatedPoints={translatedPoints}
          deviationIndices={deviationIndices}
        />
      </Canvas>
      <p className={styles.hint}>Arrastra para rotar • Scroll para zoom • Click derecho para mover</p>
    </div>
  )
}
