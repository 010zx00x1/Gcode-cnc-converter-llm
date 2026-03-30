"""
Generador de texto Siemens 840D desde IR traducido.
Serialización determinista — el LLM nunca llega aquí.
"""
from __future__ import annotations
from typing import Optional
from models.ir import (
    Program, Block, Command, CommandType, TranslationStatus, Point3D
)


def _fmt_coord(val: Optional[float], axis: str) -> str:
    if val is None:
        return ""
    return f"{axis}{val:g}"


def _fmt_coords(target: Optional[Point3D]) -> str:
    if target is None:
        return ""
    parts = []
    if target.x is not None: parts.append(f"X{target.x:g}")
    if target.y is not None: parts.append(f"Y{target.y:g}")
    if target.z is not None: parts.append(f"Z{target.z:g}")
    return " ".join(parts)


def _fmt_arc(cmd: Command) -> str:
    parts = [_fmt_coords(cmd.target)]
    if cmd.arc:
        if cmd.arc.r is not None:
            parts.append(f"CR={cmd.arc.r:g}")
        else:
            if cmd.arc.i is not None: parts.append(f"I={cmd.arc.i:g}")
            if cmd.arc.j is not None: parts.append(f"J={cmd.arc.j:g}")
            if cmd.arc.k is not None: parts.append(f"K={cmd.arc.k:g}")
    if cmd.feed is not None:
        parts.append(f"F={cmd.feed:g}")
    return " ".join(p for p in parts if p)


def _generate_command(cmd: Command, block_n: int) -> Optional[str]:
    """Genera texto Siemens para un Command. Retorna None si se debe omitir."""
    t = cmd.type

    # ── Comentario ─────────────────────────────────────────────────────────
    if t == CommandType.COMMENT:
        text = cmd.original_text.strip()
        if text.startswith("(") and text.endswith(")"):
            return f"; {text[1:-1].strip()}"
        return f"; {text.lstrip(';').strip()}"

    # ── Modal ───────────────────────────────────────────────────────────────
    if t == CommandType.MODAL_CHANGE:
        codes = cmd.modal_codes or []
        if not codes:
            return None
        return " ".join(codes)

    # ── Movimientos ─────────────────────────────────────────────────────────
    if t == CommandType.RAPID_MOVE:
        coords = _fmt_coords(cmd.target)
        return f"G0 {coords}".strip() if coords else None

    if t == CommandType.LINEAR_MOVE:
        parts = ["G1", _fmt_coords(cmd.target)]
        if cmd.feed is not None:
            parts.append(f"F{cmd.feed:g}")
        line = " ".join(p for p in parts if p)
        return line if "X" in line or "Y" in line or "Z" in line else None

    if t == CommandType.ARC_CW:
        return f"G2 {_fmt_arc(cmd)}"

    if t == CommandType.ARC_CCW:
        return f"G3 {_fmt_arc(cmd)}"

    # ── Home ────────────────────────────────────────────────────────────────
    if t == CommandType.HOME:
        if cmd.siemens_params:
            return f"{cmd.siemens_params.get('code', 'G74')} {cmd.siemens_params.get('axes', '')}"
        return "G74 Z1=0"

    # ── Ciclos de taladrado ─────────────────────────────────────────────────
    if t == CommandType.DRILL_CYCLE:
        if not cmd.siemens_params:
            return f"; [RAW] {cmd.original_text}"

        cycle = cmd.siemens_params.get("cycle", "CYCLE81")
        params = cmd.siemens_params

        # Posición XY primero (en Siemens la posición va en línea separada antes del ciclo)
        # Retornamos dos líneas: posición + ciclo
        lines = []
        if cmd.target and (cmd.target.x is not None or cmd.target.y is not None):
            lines.append(f"G0 {_fmt_coords(cmd.target)}")

        if cycle == "CYCLE81":
            rtp  = params.get("RTP", 2.0)
            rfp  = params.get("RFP", 0.0)
            sdis = params.get("SDIS", 2.0)
            dp   = params.get("DP", 0.0)
            fdpr = params.get("FDPR", 100.0)
            lines.append(f"CYCLE81({rtp:g},{rfp:g},{sdis:g},{dp:g},,{fdpr:g})")

        elif cycle == "CYCLE82":
            rtp  = params.get("RTP", 2.0)
            rfp  = params.get("RFP", 0.0)
            sdis = params.get("SDIS", 2.0)
            dp   = params.get("DP", 0.0)
            dtb  = params.get("DTB", 0.0)
            fdpr = params.get("FDPR", 100.0)
            lines.append(f"CYCLE82({rtp:g},{rfp:g},{sdis:g},{dp:g},,{dtb:g},{fdpr:g})")

        elif cycle == "CYCLE83":
            rtp  = params.get("RTP", 2.0)
            rfp  = params.get("RFP", 0.0)
            sdis = params.get("SDIS", 2.0)
            dp   = params.get("DP", 0.0)
            fdep = params.get("FDEP", 5.0)
            fdpr = params.get("FDPR", 100.0)
            dam  = params.get("DAM", 0.0)
            dtb  = params.get("DTB", 0.0)
            lines.append(
                f"CYCLE83({rtp:g},{rfp:g},{sdis:g},{dp:g},,{fdep:g},,{fdpr:g},{dam:g},{dtb:g})"
            )

        elif cycle == "CYCLE84":
            rtp  = params.get("RTP", 2.0)
            rfp  = params.get("RFP", 0.0)
            sdis = params.get("SDIS", 2.0)
            dp   = params.get("DP", 0.0)
            sdac = params.get("SDAC", 3)
            lines.append(f"CYCLE84({rtp:g},{rfp:g},{sdis:g},{dp:g},,,,,,,,{sdac})")

        elif cycle == "CYCLE85":
            rtp  = params.get("RTP", 2.0)
            rfp  = params.get("RFP", 0.0)
            sdis = params.get("SDIS", 2.0)
            dp   = params.get("DP", 0.0)
            fdpr = params.get("FDPR", 100.0)
            fdpra = params.get("FDPRA") or fdpr
            lines.append(f"CYCLE85({rtp:g},{rfp:g},{sdis:g},{dp:g},,0,{fdpr:g},{fdpra:g})")

        else:
            lines.append(f"; [CYCLE no mapeado] {cmd.original_text}")

        return "\n".join(lines)

    # ── Tool change ─────────────────────────────────────────────────────────
    if t == CommandType.TOOL_CHANGE:
        n = cmd.tool_number or 1
        return f"T{n} D1\nM6"

    # ── Tool length (implícito en Siemens) ──────────────────────────────────
    if t in (CommandType.TOOL_LENGTH_ON, CommandType.TOOL_LENGTH_OFF):
        return None  # se omite

    # ── Compensación ────────────────────────────────────────────────────────
    if t == CommandType.COMPENSATION_ON:
        code = "G41" if cmd.comp_dir == "LEFT" else "G42"
        return code

    if t == CommandType.COMPENSATION_OFF:
        return "G40"

    # ── Spindle ─────────────────────────────────────────────────────────────
    if t == CommandType.SPINDLE_ON_CW:
        s = f"S{cmd.spindle_speed:g} " if cmd.spindle_speed else ""
        return f"{s}M3".strip()

    if t == CommandType.SPINDLE_ON_CCW:
        s = f"S{cmd.spindle_speed:g} " if cmd.spindle_speed else ""
        return f"{s}M4".strip()

    if t == CommandType.SPINDLE_OFF:
        return "M5"

    # ── Coolant ─────────────────────────────────────────────────────────────
    if t == CommandType.COOLANT_ON:
        return "M8"

    if t == CommandType.COOLANT_OFF:
        return "M9"

    # ── Subprogramas ────────────────────────────────────────────────────────
    if t == CommandType.SUBPROGRAM_CALL:
        if cmd.siemens_params:
            fmt = cmd.siemens_params.get("format", "L")
            reps = cmd.siemens_params.get("repeats", 1)
            p_str = f" P{reps}" if reps > 1 else ""
            if fmt == "L":
                num = cmd.siemens_params.get("number", 0)
                return f"L{num}{p_str}"
            else:
                name = cmd.siemens_params.get("name", "")
                return f'CALL "{name}"{p_str}'
        return f"; [RAW subprograma] {cmd.original_text}"

    if t == CommandType.SUBPROGRAM_END:
        return "RET"

    # ── Fin de programa ─────────────────────────────────────────────────────
    if t == CommandType.PROGRAM_END:
        return "M30"

    # ── Variables ───────────────────────────────────────────────────────────
    if t == CommandType.VARIABLE_SET:
        if cmd.siemens_params:
            target = cmd.siemens_params.get("target", "R0")
            expr   = cmd.siemens_params.get("expression", "0")
            return f"{target}={expr}"
        if cmd.var_name and cmd.var_value:
            return f"{cmd.var_name}={cmd.var_value}"
        return f"; [RAW var] {cmd.original_text}"

    # ── Condicional / Loop (pendiente LLM) ──────────────────────────────────
    if t in (CommandType.CONDITIONAL, CommandType.LOOP):
        return f"; [NEEDS_LLM] {cmd.original_text}"

    # ── RAW ─────────────────────────────────────────────────────────────────
    if t == CommandType.RAW:
        return f"; [RAW] {cmd.original_text}"

    return f"; [UNKNOWN] {cmd.original_text}"


def generate_siemens(program: Program, program_name: str = "MAIN") -> str:
    """
    Serializa un Program IR (ya traducido) a texto Siemens 840D.
    Retorna el código .mpf como string.
    """
    lines = []

    # Header Siemens
    safe_name = program_name.replace("O", "P").upper()
    lines.append(f"%_N_{safe_name}_MPF")
    lines.append(f"; Traducido por cnc-postprocessor-llm")
    lines.append(f"; Programa original: {program.program_name}")
    lines.append("")

    seq = 10
    for block in program.blocks:
        for cmd in block.commands:
            text = _generate_command(cmd, seq)
            if text is None:
                continue
            # Una línea puede generar múltiples líneas (ciclos con posición XY)
            for part in text.split("\n"):
                part = part.strip()
                if part:
                    lines.append(f"N{seq} {part}")
                    seq += 10

    # Footer
    if not any("M30" in l for l in lines):
        lines.append(f"N{seq} M30")

    return "\n".join(lines)
