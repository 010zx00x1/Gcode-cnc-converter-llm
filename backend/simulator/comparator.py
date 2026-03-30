"""
Comparador de toolpaths.
Calcula desviación geométrica punto a punto entre original y traducido.
"""
from __future__ import annotations
import math
from typing import List, Tuple, NamedTuple

Point3D = Tuple[float, float, float]


class ComparisonResult(NamedTuple):
    max_deviation_mm:    float
    avg_deviation_mm:    float
    total_points:        int
    points_exceeding:    int          # puntos que superan el threshold
    threshold_mm:        float
    deviations:          List[float]  # desviación por punto (alineado)
    exceeding_indices:   List[int]    # índices de puntos con desviación > threshold


def _euclidean(a: Point3D, b: Point3D) -> float:
    return math.sqrt(
        (a[0] - b[0]) ** 2 +
        (a[1] - b[1]) ** 2 +
        (a[2] - b[2]) ** 2
    )


def _resample(points: List[Point3D], n: int) -> List[Point3D]:
    """
    Remuestrea una lista de puntos a exactamente n puntos
    mediante interpolación lineal de arclength.
    Necesario cuando los dos toolpaths tienen distinto número de puntos.
    """
    if len(points) == 0:
        return [(0.0, 0.0, 0.0)] * n
    if len(points) == 1:
        return [points[0]] * n
    if len(points) == n:
        return list(points)

    # Calcular longitudes acumuladas
    cum_lengths = [0.0]
    for i in range(1, len(points)):
        cum_lengths.append(cum_lengths[-1] + _euclidean(points[i - 1], points[i]))

    total_length = cum_lengths[-1]
    if total_length == 0:
        return [points[0]] * n

    result = []
    for i in range(n):
        target_len = total_length * i / (n - 1) if n > 1 else 0.0

        # Buscar segmento donde cae target_len
        idx = 0
        for j in range(1, len(cum_lengths)):
            if cum_lengths[j] >= target_len:
                idx = j - 1
                break
        else:
            idx = len(points) - 2

        seg_len = cum_lengths[idx + 1] - cum_lengths[idx]
        if seg_len == 0:
            result.append(points[idx])
            continue

        t = (target_len - cum_lengths[idx]) / seg_len
        ax, ay, az = points[idx]
        bx, by, bz = points[idx + 1]
        result.append((
            ax + (bx - ax) * t,
            ay + (by - ay) * t,
            az + (bz - az) * t,
        ))

    return result


def compare_toolpaths(
    original: List[Point3D],
    translated: List[Point3D],
    threshold_mm: float = 0.01,
) -> ComparisonResult:
    """
    Compara dos toolpaths punto a punto.

    Si tienen distinto número de puntos, remuestrea el más corto
    al número de puntos del más largo (preserva geometría del original).

    Args:
        original:    toolpath del programa Fanuc original
        translated:  toolpath del programa Siemens traducido
        threshold_mm: umbral para marcar puntos como "excedentes"

    Returns:
        ComparisonResult con estadísticas de desviación
    """
    if not original or not translated:
        return ComparisonResult(
            max_deviation_mm=0.0,
            avg_deviation_mm=0.0,
            total_points=0,
            points_exceeding=0,
            threshold_mm=threshold_mm,
            deviations=[],
            exceeding_indices=[],
        )

    n = max(len(original), len(translated))

    orig_r = _resample(original, n)
    tran_r = _resample(translated, n)

    deviations = [_euclidean(a, b) for a, b in zip(orig_r, tran_r)]
    exceeding = [i for i, d in enumerate(deviations) if d > threshold_mm]

    return ComparisonResult(
        max_deviation_mm=max(deviations),
        avg_deviation_mm=sum(deviations) / len(deviations),
        total_points=n,
        points_exceeding=len(exceeding),
        threshold_mm=threshold_mm,
        deviations=deviations,
        exceeding_indices=exceeding,
    )


def is_within_tolerance(result: ComparisonResult) -> bool:
    return result.max_deviation_mm <= result.threshold_mm
