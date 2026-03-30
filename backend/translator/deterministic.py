"""
Traductor determinista: IR Fanuc → IR Siemens.
Usa equivalences.json como fuente de verdad.
No toca el LLM. Marca needs_llm=True en los casos ambiguos.
"""
from __future__ import annotations
import json
import copy
from pathlib import Path
from typing import Optional
from models.ir import (
    Program, Block, Command, CommandType, TranslationStatus,
    DrillParams, Point3D, Dialect
)

EQUIVALENCES_PATH = Path(__file__).parent.parent / "data" / "equivalences.json"


def load_equivalences() -> dict:
    with open(EQUIVALENCES_PATH, "r") as f:
        return json.load(f)


# ─── Traductores por tipo de command ─────────────────────────────────────────

def _translate_modal(cmd: Command, eq: dict) -> Command:
    out = cmd.model_copy(deep=True)
    if not cmd.modal_codes:
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    siemens_codes = []
    for code in cmd.modal_codes:
        upper = code.upper()
        # Unidades: G20→G70, G21→G71
        if upper in eq.get("units", {}):
            siemens_codes.append(eq["units"][upper]["siemens"])
        # G80 cancel ciclo → se omite en Siemens
        elif upper == "G80":
            pass  # no genera código Siemens
        else:
            siemens_codes.append(code)  # el resto es idéntico

    out.modal_codes = siemens_codes if siemens_codes else None
    out.translation_status = TranslationStatus.TRANSLATED
    return out


def _translate_move(cmd: Command) -> Command:
    out = cmd.model_copy(deep=True)
    out.translation_status = TranslationStatus.TRANSLATED
    return out  # G0/G1/G2/G3 son idénticos


def _translate_drill_cycle(cmd: Command, eq: dict) -> Command:
    out = cmd.model_copy(deep=True)
    if not cmd.drill:
        out.translation_status = TranslationStatus.RAW
        return out

    cycle_code = cmd.drill.cycle_code.upper()
    cycles_eq = eq.get("cycles", {})

    if cycle_code not in cycles_eq:
        out.needs_llm = True
        out.translation_status = TranslationStatus.NEEDS_LLM
        return out

    cycle_def = cycles_eq[cycle_code]
    siemens_name = cycle_def.get("siemens")

    if siemens_name is None:
        # G80 u otro que se ignora
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    param_map = cycle_def.get("param_map", {})

    # Construir dict de parámetros Siemens
    siemens_params = {}

    # Rellenar defaults primero
    for key, val in param_map.items():
        if key.startswith("_"):
            siemens_key = key[1:]  # quitar _
            if val is not None:
                siemens_params[siemens_key] = val

    # Mapear parámetros Fanuc a Siemens
    fanuc_src = {
        "R": cmd.drill.r,
        "Z": cmd.drill.z,
        "Q": cmd.drill.q,
        "P": cmd.drill.p,
        "F": cmd.drill.f,
    }

    for fanuc_key, siemens_key in param_map.items():
        if fanuc_key.startswith("_"):
            continue
        fanuc_val = fanuc_src.get(fanuc_key)
        if fanuc_val is not None:
            # Caso especial: G82 P (ms) → DTB (segundos)
            if fanuc_key == "P" and siemens_key == "DTB":
                siemens_params[siemens_key] = fanuc_val / 1000.0
            else:
                siemens_params[siemens_key] = fanuc_val

    # RFP (plano referencia) = 0 por defecto
    if "RFP" not in siemens_params:
        siemens_params["RFP"] = 0.0

    # SDIS (distancia de seguridad) = 2mm por defecto si no está
    if "SDIS" not in siemens_params:
        siemens_params["SDIS"] = 2.0

    out.siemens_params = {"cycle": siemens_name, **siemens_params}
    out.translation_status = TranslationStatus.TRANSLATED
    return out


def _translate_compensation(cmd: Command, eq: dict) -> Command:
    out = cmd.model_copy(deep=True)
    comp_eq = eq.get("compensation", {})

    if cmd.type == CommandType.COMPENSATION_OFF:
        g40 = comp_eq.get("G40", {})
        out.siemens_params = {"code": g40.get("siemens", "G40")}
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    if cmd.type == CommandType.COMPENSATION_ON:
        code = "G41" if cmd.comp_dir == "LEFT" else "G42"
        eq_entry = comp_eq.get(code, {})
        out.siemens_params = {"code": eq_entry.get("siemens", code)}
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    out.translation_status = TranslationStatus.TRANSLATED
    return out


def _translate_tool_length(cmd: Command) -> Command:
    """G43 → implícito en Siemens. Se omite en la generación."""
    out = cmd.model_copy(deep=True)
    out.siemens_params = {"action": "implicit"}
    out.translation_status = TranslationStatus.TRANSLATED
    return out


def _translate_tool_change(cmd: Command) -> Command:
    out = cmd.model_copy(deep=True)
    out.translation_status = TranslationStatus.TRANSLATED
    return out  # T# M6 es igual en Siemens


def _translate_subprogram_call(cmd: Command, eq: dict) -> Command:
    out = cmd.model_copy(deep=True)
    sub_eq = eq.get("subprograms", {}).get("M98", {})
    num = cmd.subprogram_number
    reps = cmd.repeat_count or 1
    # Usar formato L#### para números, CALL "nombre" para strings
    if num is not None:
        out.siemens_params = {
            "format": "L",
            "number": num,
            "repeats": reps,
        }
    else:
        out.siemens_params = {
            "format": "CALL",
            "name": cmd.subprogram_name or "",
            "repeats": reps,
        }
    out.translation_status = TranslationStatus.TRANSLATED
    return out


def _translate_home(cmd: Command) -> Command:
    """G28 G91 Z0 → G74 Z1=0 en Siemens."""
    out = cmd.model_copy(deep=True)
    out.siemens_params = {"code": "G74", "axes": "Z1=0"}
    out.translation_status = TranslationStatus.TRANSLATED
    return out


def _translate_variable(cmd: Command, eq: dict) -> Command:
    """Variables: sustitución directa de variables de sistema conocidas."""
    out = cmd.model_copy(deep=True)
    sys_vars = eq.get("system_variables", {})

    if not cmd.var_name or not cmd.var_value:
        out.translation_status = TranslationStatus.RAW
        return out

    # Traducir nombre de variable (target)
    siemens_target = _map_variable(cmd.var_name, sys_vars, eq)

    # Traducir expresión (sustituir variables de sistema)
    expr = cmd.var_value
    for fanuc_var, var_def in sys_vars.items():
        if fanuc_var in expr:
            siemens_equiv = var_def.get("siemens")
            if siemens_equiv:
                expr = expr.replace(fanuc_var, siemens_equiv)
            elif var_def.get("needs_llm"):
                out.needs_llm = True
                out.translation_status = TranslationStatus.NEEDS_LLM
                return out

    # Traducir variables de usuario (#100 → R0, #500 → $R[0])
    import re
    def replace_user_var(match):
        n = int(match.group(1))
        return _map_user_var_number(n)

    expr = re.sub(r'#(\d+)', replace_user_var, expr)

    out.var_name = siemens_target
    out.var_value = expr
    out.siemens_params = {"target": siemens_target, "expression": expr}
    out.translation_status = TranslationStatus.TRANSLATED
    return out


def _map_variable(fanuc_var: str, sys_vars: dict, eq: dict) -> str:
    """Mapea una variable Fanuc a su equivalente Siemens."""
    import re
    # Sistema
    clean = fanuc_var.strip()
    if clean in sys_vars:
        sv = sys_vars[clean]
        if sv.get("siemens"):
            return sv["siemens"]
    # Usuario: #100-#149 → R0-R49, #500-#999 → $R[n-500]
    m = re.match(r'#(\d+)', clean)
    if m:
        n = int(m.group(1))
        return _map_user_var_number(n)
    return clean


def _map_user_var_number(n: int) -> str:
    if 1 <= n <= 33:
        return f"R{n - 1}"
    if 100 <= n <= 149:
        return f"R{n - 100}"
    if 500 <= n <= 999:
        return f"$R[{n - 500}]"
    return f"R{n}"  # fallback


# ─── Dispatcher principal ─────────────────────────────────────────────────────

def _translate_command(cmd: Command, eq: dict) -> Command:
    t = cmd.type

    if t in (CommandType.RAPID_MOVE, CommandType.LINEAR_MOVE,
             CommandType.ARC_CW, CommandType.ARC_CCW):
        return _translate_move(cmd)

    if t == CommandType.DRILL_CYCLE:
        return _translate_drill_cycle(cmd, eq)

    if t == CommandType.MODAL_CHANGE:
        return _translate_modal(cmd, eq)

    if t in (CommandType.COMPENSATION_ON, CommandType.COMPENSATION_OFF):
        return _translate_compensation(cmd, eq)

    if t == CommandType.TOOL_LENGTH_ON:
        return _translate_tool_length(cmd)

    if t == CommandType.TOOL_LENGTH_OFF:
        out = cmd.model_copy(deep=True)
        out.siemens_params = {"action": "implicit"}
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    if t == CommandType.TOOL_CHANGE:
        return _translate_tool_change(cmd)

    if t == CommandType.SUBPROGRAM_CALL:
        return _translate_subprogram_call(cmd, eq)

    if t == CommandType.SUBPROGRAM_END:
        out = cmd.model_copy(deep=True)
        out.siemens_params = {"code": "RET"}
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    if t == CommandType.HOME:
        return _translate_home(cmd)

    if t == CommandType.VARIABLE_SET:
        return _translate_variable(cmd, eq)

    if t in (CommandType.CONDITIONAL, CommandType.LOOP):
        out = cmd.model_copy(deep=True)
        out.needs_llm = True
        out.translation_status = TranslationStatus.NEEDS_LLM
        return out

    if t in (CommandType.SPINDLE_ON_CW, CommandType.SPINDLE_ON_CCW,
             CommandType.SPINDLE_OFF, CommandType.COOLANT_ON,
             CommandType.COOLANT_OFF, CommandType.PROGRAM_END):
        out = cmd.model_copy(deep=True)
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    if t == CommandType.COMMENT:
        out = cmd.model_copy(deep=True)
        out.translation_status = TranslationStatus.TRANSLATED
        return out

    # RAW o desconocido
    out = cmd.model_copy(deep=True)
    out.translation_status = TranslationStatus.RAW
    return out


# ─── Entry point ──────────────────────────────────────────────────────────────

def translate_ir(source: Program, equivalences: Optional[dict] = None) -> Program:
    """
    Traduce un Program IR Fanuc a un Program IR Siemens.
    Retorna nuevo Program (inmutable — no modifica el original).
    """
    eq = equivalences or load_equivalences()
    translated = source.model_copy(deep=True)
    translated.dialect = Dialect.SIEMENS

    total_needs_llm = 0

    for block in translated.blocks:
        new_commands = []
        for cmd in block.commands:
            t_cmd = _translate_command(cmd, eq)
            new_commands.append(t_cmd)
            if t_cmd.needs_llm:
                total_needs_llm += 1
        block.commands = new_commands

    translated.commands_need_llm = total_needs_llm
    return translated
