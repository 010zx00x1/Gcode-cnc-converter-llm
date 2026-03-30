"""
Calculador de confianza de la traducción.
Score 0.0 - 1.0 basado en calidad objetiva de la traducción.
"""
from __future__ import annotations
from typing import Optional
from models.ir import Program, TranslationStatus
from simulator.comparator import ComparisonResult


def calculate_confidence(
    translated: Program,
    comparison: Optional[ComparisonResult],
    attempts_used: int,
    max_attempts: int = 3,
) -> float:
    """
    Calcula el score de confianza de la traducción.

    Penalizaciones:
    - -5%  por cada comando que necesitó LLM
    - -10% por cada intento de corrección usado
    - -20% si la desviación final > 0.005mm
    - -30% si hay comandos RAW (no traducidos)
    - -15% si la desviación > threshold (0.01mm)

    Returns:
        float entre 0.0 y 1.0
    """
    score = 1.0

    # Contar por status
    total = 0
    raw_count = 0
    llm_count = 0

    for block in translated.blocks:
        for cmd in block.commands:
            total += 1
            if cmd.translation_status == TranslationStatus.RAW:
                raw_count += 1
            if cmd.needs_llm:
                llm_count += 1

    # Penalizar comandos que necesitaron LLM
    if total > 0:
        llm_ratio = llm_count / total
        score -= llm_ratio * 0.25  # hasta -25% si todo es LLM

    # Penalizar comandos RAW
    if total > 0:
        raw_ratio = raw_count / total
        score -= raw_ratio * 0.40  # hasta -40% si todo es RAW

    # Penalizar reintentos de corrección
    score -= attempts_used * 0.10

    # Penalizar desviación geométrica
    if comparison is not None:
        if comparison.max_deviation_mm > comparison.threshold_mm:
            score -= 0.15
        if comparison.max_deviation_mm > 0.005:
            score -= 0.20
        if comparison.max_deviation_mm > 0.1:
            score -= 0.20  # penalización adicional por error grande

    return max(0.0, min(1.0, round(score, 3)))


def confidence_label(score: float) -> str:
    if score >= 0.90:
        return "ALTA"
    if score >= 0.70:
        return "MEDIA"
    if score >= 0.50:
        return "BAJA"
    return "MUY BAJA"
