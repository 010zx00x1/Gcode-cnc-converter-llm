"""
LangGraph pipeline completo.
Parse → Translate → LLM (si necesario) → Generate → Simulate → Decide → Correct → Output
"""
from __future__ import annotations
import json
import re
from typing import TypedDict, Optional, List, Literal, Any

from langgraph.graph import StateGraph, END

from models.ir import (
    Program, Command, CommandType, TranslationStatus, Dialect
)
from gcode_parser.fanuc_parser import parse_fanuc
from translator.deterministic import translate_ir, load_equivalences
from translator.siemens_generator import generate_siemens
from simulator.toolpath import simulate_toolpath, Point3D
from simulator.comparator import compare_toolpaths, ComparisonResult, is_within_tolerance
from pipeline.confidence import calculate_confidence, confidence_label
from pipeline.prompts import (
    build_variable_prompt,
    build_conditional_prompt,
    build_correction_prompt,
    VARIABLE_TRANSLATION_SCHEMA,
    CONDITIONAL_TRANSLATION_SCHEMA,
    CORRECTION_SCHEMA,
)
from config import settings, load_llm_config


# ─── Estado del pipeline ──────────────────────────────────────────────────────

class TranslationState(TypedDict):
    source_code:          str
    source_ir:            Optional[Program]
    translated_ir:        Optional[Program]
    translated_code:      str
    source_toolpath:      List[Point3D]
    translated_toolpath:  List[Point3D]
    comparison:           Optional[dict]      # ComparisonResult como dict
    attempt:              int
    max_attempts:         int
    confidence:           float
    errors:               List[str]
    warnings:             List[str]
    done:                 bool


def initial_state(source_code: str, max_attempts: int = 3) -> TranslationState:
    return TranslationState(
        source_code=source_code,
        source_ir=None,
        translated_ir=None,
        translated_code="",
        source_toolpath=[],
        translated_toolpath=[],
        comparison=None,
        attempt=0,
        max_attempts=max_attempts,
        confidence=0.0,
        errors=[],
        warnings=[],
        done=False,
    )


# ─── LLM client factory ───────────────────────────────────────────────────────

def _get_llm():
    """Crea el LLM configurado en llm_config.json."""
    cfg = load_llm_config()
    provider = cfg.get("provider", "openai")
    model    = cfg.get("model", "gpt-4o")
    temp     = cfg.get("temperature", 0.1)
    tokens   = cfg.get("max_tokens", 2048)
    timeout  = cfg.get("timeout_seconds", 30)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            temperature=temp,
            max_tokens=tokens,
            timeout=timeout,
            api_key=settings.openai_api_key or None,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            temperature=temp,
            max_tokens=tokens,
            timeout=timeout,
            api_key=settings.anthropic_api_key or None,
        )
    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        base_url = cfg.get("available_providers", [{}])[2].get("base_url", "http://localhost:11434")
        for p in cfg.get("available_providers", []):
            if p.get("id") == "ollama":
                base_url = p.get("base_url", base_url)
        return ChatOllama(model=model, base_url=base_url, temperature=temp)
    else:
        raise ValueError(f"Provider no soportado: {provider}")


def _call_llm_json(prompt: str, schema: dict) -> Optional[dict]:
    """
    Llama al LLM y extrae JSON válido de la respuesta.
    Valida contra el schema básico (campos requeridos).
    Retorna None si falla la validación.
    """
    try:
        llm = _get_llm()
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)

        # Extraer bloque JSON de la respuesta
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            return None

        parsed = json.loads(json_match.group())

        # Validar campos requeridos
        required = schema.get("required", [])
        if not all(k in parsed for k in required):
            return None

        return parsed

    except Exception:
        return None


# ─── Nodos del pipeline ───────────────────────────────────────────────────────

def parse_node(state: TranslationState) -> TranslationState:
    """Parsea el código fuente Fanuc a IR."""
    try:
        program = parse_fanuc(state["source_code"])
        return {**state, "source_ir": program}
    except Exception as e:
        return {**state, "errors": state["errors"] + [f"Parse error: {e}"], "done": True}


def translate_node(state: TranslationState) -> TranslationState:
    """Traducción determinista IR Fanuc → IR Siemens."""
    if state.get("done") or state["source_ir"] is None:
        return state
    try:
        eq = load_equivalences()
        translated = translate_ir(state["source_ir"], eq)
        return {**state, "translated_ir": translated}
    except Exception as e:
        return {**state, "errors": state["errors"] + [f"Translate error: {e}"], "done": True}


def llm_node(state: TranslationState) -> TranslationState:
    """
    Resuelve los comandos marcados como NEEDS_LLM.
    El LLM solo opera sobre IR JSON — nunca genera G-code libre.
    """
    if state.get("done") or state["translated_ir"] is None:
        return state

    translated = state["translated_ir"]
    if translated.commands_need_llm == 0:
        return state

    warnings = list(state["warnings"])
    new_blocks = []

    for block in translated.blocks:
        new_cmds = []
        for cmd in block.commands:
            if cmd.translation_status != TranslationStatus.NEEDS_LLM:
                new_cmds.append(cmd)
                continue

            resolved = _resolve_with_llm(cmd, block.modal_state.model_dump(), warnings)
            new_cmds.append(resolved)

        new_block = block.model_copy(deep=True)
        new_block.commands = new_cmds
        new_blocks.append(new_block)

    new_translated = translated.model_copy(deep=True)
    new_translated.blocks = new_blocks
    new_translated.commands_need_llm = sum(
        1 for b in new_blocks for c in b.commands
        if c.needs_llm and c.translation_status == TranslationStatus.NEEDS_LLM
    )

    return {**state, "translated_ir": new_translated, "warnings": warnings}


def _resolve_with_llm(cmd: Command, modal_state: dict, warnings: list) -> Command:
    """Resuelve un Command individual con el LLM. Fallback a RAW si falla."""
    out = cmd.model_copy(deep=True)

    if cmd.type == CommandType.VARIABLE_SET:
        prompt = build_variable_prompt(
            fanuc_var=cmd.var_name or "",
            fanuc_expr=cmd.var_value or "",
        )
        result = _call_llm_json(prompt, VARIABLE_TRANSLATION_SCHEMA)
        if result:
            out.siemens_params = result
            out.var_name  = result.get("target", cmd.var_name)
            out.var_value = result.get("expression", cmd.var_value)
            out.translation_status = TranslationStatus.LLM_DONE
            out.needs_llm = False
            return out

    elif cmd.type in (CommandType.CONDITIONAL, CommandType.LOOP):
        prompt = build_conditional_prompt(
            original_text=cmd.original_text,
            modal_state=modal_state,
        )
        result = _call_llm_json(prompt, CONDITIONAL_TRANSLATION_SCHEMA)
        if result:
            out.siemens_params = result
            out.translation_status = TranslationStatus.LLM_DONE
            out.needs_llm = False
            return out

    # Fallback: marcar como RAW con warning
    warnings.append(f"No se pudo traducir (LLM falló): {cmd.original_text}")
    out.translation_status = TranslationStatus.RAW
    out.needs_llm = False
    return out


def generate_node(state: TranslationState) -> TranslationState:
    """Serializa el IR Siemens traducido a texto .mpf."""
    if state.get("done") or state["translated_ir"] is None:
        return state
    try:
        prog_name = state["source_ir"].program_name if state["source_ir"] else "MAIN"
        code = generate_siemens(state["translated_ir"], prog_name)
        return {**state, "translated_code": code}
    except Exception as e:
        return {**state, "errors": state["errors"] + [f"Generate error: {e}"], "done": True}


def simulate_node(state: TranslationState) -> TranslationState:
    """Simula ambos toolpaths y calcula la desviación."""
    if state.get("done"):
        return state
    if state["source_ir"] is None or state["translated_ir"] is None:
        return state
    try:
        src_tp  = simulate_toolpath(state["source_ir"])
        tran_tp = simulate_toolpath(state["translated_ir"])
        result  = compare_toolpaths(
            src_tp, tran_tp,
            threshold_mm=settings.deviation_threshold_mm,
        )
        return {
            **state,
            "source_toolpath":     src_tp,
            "translated_toolpath": tran_tp,
            "comparison":          result._asdict(),
        }
    except Exception as e:
        return {**state, "errors": state["errors"] + [f"Simulate error: {e}"]}


def decide_node(state: TranslationState) -> Literal["correct", "output"]:
    """Edge condicional: ¿necesita corrección?"""
    if state.get("done"):
        return "output"

    comparison = state.get("comparison")
    if comparison is None:
        return "output"

    max_dev   = comparison.get("max_deviation_mm", 0.0)
    threshold = comparison.get("threshold_mm", settings.deviation_threshold_mm)
    attempt   = state.get("attempt", 0)
    max_att   = state.get("max_attempts", 3)

    if max_dev > threshold and attempt < max_att:
        return "correct"
    return "output"


def correct_node(state: TranslationState) -> TranslationState:
    """
    Corrección por LLM: identifica los comandos con mayor desviación
    y pide al LLM que los corrija.
    """
    if state.get("done") or state["translated_ir"] is None:
        return state

    comparison = state.get("comparison", {})
    max_dev    = comparison.get("max_deviation_mm", 0.0)
    threshold  = comparison.get("threshold_mm", settings.deviation_threshold_mm)
    attempt    = state["attempt"] + 1
    warnings   = list(state["warnings"])

    # Identificar los bloques con comandos en zonas de alto error
    exceeding_idx = set(comparison.get("exceeding_indices", []))
    if not exceeding_idx:
        return {**state, "attempt": attempt}

    # Construir lista de comandos afectados para el prompt
    affected_commands = []
    translated = state["translated_ir"]
    for block in translated.blocks:
        for cmd in block.commands:
            if cmd.type in (CommandType.DRILL_CYCLE, CommandType.LINEAR_MOVE,
                            CommandType.ARC_CW, CommandType.ARC_CCW):
                affected_commands.append({
                    "original_text":  cmd.original_text,
                    "type":           cmd.type.value,
                    "siemens_params": cmd.siemens_params or {},
                })

    # Puntos con mayor error
    deviations = comparison.get("deviations", [])
    src_tp  = state["source_toolpath"]
    error_points = []
    for i in sorted(exceeding_idx)[:15]:
        if i < len(src_tp) and i < len(deviations):
            x, y, z = src_tp[i]
            error_points.append({
                "index": i,
                "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
                "deviation": round(deviations[i], 5),
            })

    prompt = build_correction_prompt(
        commands=affected_commands[:10],
        error_points=error_points,
        deviation_mm=max_dev,
        threshold_mm=threshold,
        attempt=attempt,
        max_attempts=state["max_attempts"],
    )

    result = _call_llm_json(prompt, CORRECTION_SCHEMA)

    if not result or "corrected_commands" not in result:
        warnings.append(f"Intento {attempt}: corrección LLM falló. Usando resultado anterior.")
        return {**state, "attempt": attempt, "warnings": warnings}

    # Aplicar correcciones al IR
    corrected_map = {
        c["original_text"]: c.get("siemens_params", {})
        for c in result["corrected_commands"]
    }

    new_translated = translated.model_copy(deep=True)
    for block in new_translated.blocks:
        for cmd in block.commands:
            if cmd.original_text in corrected_map:
                cmd.siemens_params = corrected_map[cmd.original_text]

    return {
        **state,
        "translated_ir": new_translated,
        "attempt": attempt,
        "warnings": warnings,
    }


def output_node(state: TranslationState) -> TranslationState:
    """Empaqueta el resultado final y calcula la confianza."""
    comparison_dict = state.get("comparison")
    comparison_obj  = None

    if comparison_dict:
        from simulator.comparator import ComparisonResult
        comparison_obj = ComparisonResult(**comparison_dict)

    score = calculate_confidence(
        translated=state["translated_ir"] or Program(),
        comparison=comparison_obj,
        attempts_used=state.get("attempt", 0),
        max_attempts=state.get("max_attempts", 3),
    )

    return {**state, "confidence": score, "done": True}


# ─── Construcción del grafo ───────────────────────────────────────────────────

def build_graph():
    g = StateGraph(TranslationState)

    g.add_node("parse",    parse_node)
    g.add_node("translate", translate_node)
    g.add_node("llm",      llm_node)
    g.add_node("generate", generate_node)
    g.add_node("simulate", simulate_node)
    g.add_node("correct",  correct_node)
    g.add_node("output",   output_node)

    g.set_entry_point("parse")
    g.add_edge("parse",    "translate")
    g.add_edge("translate","llm")
    g.add_edge("llm",      "generate")
    g.add_edge("generate", "simulate")

    g.add_conditional_edges(
        "simulate",
        decide_node,
        {"correct": "correct", "output": "output"},
    )

    # Después de corregir, regenerar y resimular
    g.add_edge("correct", "generate")
    g.add_edge("output",  END)

    return g.compile()


# ─── Entry point público ──────────────────────────────────────────────────────

def run_translation(source_code: str, max_attempts: int = 3) -> dict:
    """
    Ejecuta el pipeline completo y retorna el resultado listo para la API.

    Returns dict con:
        success, translated_code, source_toolpath, translated_toolpath,
        deviation_points, max_deviation_mm, confidence, attempts_used, warnings, errors
    """
    graph = build_graph()
    state = initial_state(source_code, max_attempts)
    final = graph.invoke(state)

    comparison = final.get("comparison") or {}
    exceeding  = comparison.get("exceeding_indices", [])

    return {
        "success":             not bool(final.get("errors")),
        "translated_code":     final.get("translated_code", ""),
        "source_toolpath":     final.get("source_toolpath", []),
        "translated_toolpath": final.get("translated_toolpath", []),
        "deviation_points":    exceeding,
        "max_deviation_mm":    comparison.get("max_deviation_mm", 0.0),
        "avg_deviation_mm":    comparison.get("avg_deviation_mm", 0.0),
        "confidence":          final.get("confidence", 0.0),
        "confidence_label":    confidence_label(final.get("confidence", 0.0)),
        "attempts_used":       final.get("attempt", 0),
        "warnings":            final.get("warnings", []),
        "errors":              final.get("errors", []),
    }
