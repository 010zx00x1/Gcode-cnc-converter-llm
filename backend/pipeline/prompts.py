"""
Prompts para el LLM.
CRÍTICO: el LLM nunca genera texto G-code libre.
Solo completa JSON con schema fijo — validado antes de usar.
"""
from __future__ import annotations
from typing import Any

# ─── Schema de salida que el LLM debe respetar ────────────────────────────────

VARIABLE_TRANSLATION_SCHEMA = {
    "type": "object",
    "required": ["target", "expression"],
    "properties": {
        "target":     {"type": "string", "description": "Variable Siemens (ej: R0, $R[5])"},
        "expression": {"type": "string", "description": "Expresión Siemens equivalente"},
    },
    "additionalProperties": False,
}

CONDITIONAL_TRANSLATION_SCHEMA = {
    "type": "object",
    "required": ["siemens_code"],
    "properties": {
        "siemens_code": {
            "type": "string",
            "description": "Líneas Siemens equivalentes (separadas por \\n si son múltiples)"
        },
    },
    "additionalProperties": False,
}

CORRECTION_SCHEMA = {
    "type": "object",
    "required": ["corrected_commands"],
    "properties": {
        "corrected_commands": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["original_text", "siemens_params"],
                "properties": {
                    "original_text":  {"type": "string"},
                    "siemens_params": {"type": "object"},
                },
            }
        },
        "explanation": {"type": "string"},
    },
    "additionalProperties": False,
}


# ─── Prompt: Traducir variable/expresión ambigua ──────────────────────────────

TRANSLATE_VARIABLE_PROMPT = """\
Eres un experto en traducción de G-code CNC entre Fanuc y Siemens 840D.
Tu tarea es traducir una expresión de variable Fanuc a su equivalente Siemens 840D.

REGLAS:
- Responde ÚNICAMENTE con JSON válido que cumpla el schema.
- NO generes texto G-code libre. Solo valores para el JSON.
- Siemens 840D usa variables R para locales, $R[n] para globales.
- Las variables de sistema tienen equivalentes específicos (ver tabla).

TABLA DE EQUIVALENCIAS DE VARIABLES DE SISTEMA:
- #3011 (fecha YYYYMMDD) → $AC_YEAR*10000 + $AC_MONTH*100 + $AC_DAY
- #3012 (hora HHMMSS)   → $AC_HOUR*10000 + $AC_MINUTE*100 + $AC_SECOND
- #2001 (tool length T1) → $TC_DP3[1,1]
- #2201 (tool radius T1) → $TC_DP6[1,1]
- #5001 (pos X)          → $AA_IW[X]
- #5002 (pos Y)          → $AA_IW[Y]
- #5003 (pos Z)          → $AA_IW[Z]

VARIABLES DE USUARIO:
- #100-#149 → R0-R49
- #500-#999 → $R[n-500]

EJEMPLOS:
Input: {{"fanuc_var": "#100", "fanuc_expr": "#3011"}}
Output: {{"target": "R0", "expression": "$AC_YEAR*10000+$AC_MONTH*100+$AC_DAY"}}

Input: {{"fanuc_var": "#101", "fanuc_expr": "#101 + 10.0"}}
Output: {{"target": "R1", "expression": "R1+10.0"}}

Input: {{"fanuc_var": "#500", "fanuc_expr": "#5001 * 2"}}
Output: {{"target": "$R[0]", "expression": "$AA_IW[X]*2"}}

SCHEMA DE RESPUESTA:
{schema}

COMANDO A TRADUCIR:
{command_json}

Responde SOLO con el JSON. Sin explicaciones fuera del JSON.
"""


# ─── Prompt: Traducir condicional/loop ────────────────────────────────────────

TRANSLATE_CONDITIONAL_PROMPT = """\
Eres un experto en traducción de G-code CNC entre Fanuc y Siemens 840D.
Tu tarea es traducir una instrucción condicional o de control de flujo Fanuc a Siemens 840D.

EQUIVALENCIAS:
- IF [cond] GOTO N → IF (cond) GOTOF Label  (GOTOF = salto hacia adelante)
- IF [cond] GOTO N → IF (cond) GOTOB Label  (GOTOB = salto hacia atrás)
- WHILE [cond] DO n ... END n → WHILE (cond) DO ... ENDWHILE
- Fanuc GT/LT/EQ/GE/LE/NE → Siemens >/</==/>=/<=/!=
- Fanuc AND/OR → Siemens AND/OR

EJEMPLOS:
Input:  "IF [#101 GT 20.0] GOTO 480"
Output: {{"siemens_code": "IF (R1>20.0) GOTOF LABEL480"}}

Input:  "IF [#100 EQ 0] GOTO 100"
Output: {{"siemens_code": "IF (R0==0) GOTOB LABEL100"}}

Input:  "WHILE [#1 LE 10] DO 1"
Output: {{"siemens_code": "WHILE (R0<=10)"}}

SCHEMA DE RESPUESTA:
{schema}

INSTRUCCIÓN A TRADUCIR:
{command_json}

Contexto modal: {modal_context}

Responde SOLO con el JSON. Sin explicaciones fuera del JSON.
"""


# ─── Prompt: Corrección por desviación geométrica ────────────────────────────

CORRECTION_PROMPT = """\
Eres un experto en traducción de G-code CNC entre Fanuc y Siemens 840D.

Se detectó una desviación geométrica de {deviation_mm:.4f}mm entre el toolpath original (Fanuc)
y el traducido (Siemens). El umbral aceptable es {threshold_mm:.4f}mm.

Los siguientes comandos Siemens generaron la desviación. Necesitas corregirlos.

CONTEXTO:
- Intento: {attempt} de {max_attempts}
- Desviación máxima detectada: {deviation_mm:.4f}mm
- Puntos con error: {exceeding_points}

COMANDOS CON DESVIACIÓN (en IR JSON):
{commands_json}

TOOLPATH ORIGINAL (puntos con mayor error, XYZ):
{error_points}

REGLAS:
- Modifica SOLO los siemens_params de los comandos afectados.
- NO cambies el tipo de comando ni el original_text.
- Mantén el schema exacto de cada comando.
- Los parámetros de ciclos CYCLE83 son: RTP, RFP, SDIS, DP, FDEP, FDPR, DAM, DTB.

SCHEMA DE RESPUESTA:
{schema}

Responde SOLO con el JSON de corrección.
"""


# ─── Builder functions ────────────────────────────────────────────────────────

def build_variable_prompt(fanuc_var: str, fanuc_expr: str) -> str:
    import json
    command = {"fanuc_var": fanuc_var, "fanuc_expr": fanuc_expr}
    return TRANSLATE_VARIABLE_PROMPT.format(
        schema=json.dumps(VARIABLE_TRANSLATION_SCHEMA, indent=2),
        command_json=json.dumps(command, indent=2),
    )


def build_conditional_prompt(original_text: str, modal_state: dict) -> str:
    import json
    return TRANSLATE_CONDITIONAL_PROMPT.format(
        schema=json.dumps(CONDITIONAL_TRANSLATION_SCHEMA, indent=2),
        command_json=json.dumps({"original": original_text}, indent=2),
        modal_context=json.dumps(modal_state, indent=2),
    )


def build_correction_prompt(
    commands: list,
    error_points: list,
    deviation_mm: float,
    threshold_mm: float,
    attempt: int,
    max_attempts: int,
) -> str:
    import json
    exceeding = sum(1 for p in error_points if p.get("deviation", 0) > threshold_mm)
    # Solo los 10 puntos con mayor error para no inflar el prompt
    top_points = sorted(error_points, key=lambda p: p.get("deviation", 0), reverse=True)[:10]

    return CORRECTION_PROMPT.format(
        deviation_mm=deviation_mm,
        threshold_mm=threshold_mm,
        attempt=attempt,
        max_attempts=max_attempts,
        exceeding_points=exceeding,
        commands_json=json.dumps(commands, indent=2),
        error_points=json.dumps(top_points, indent=2),
        schema=json.dumps(CORRECTION_SCHEMA, indent=2),
    )
