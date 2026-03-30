"""
Intermediate Representation (IR) para G-code.
Contrato entre parser, traductor y simulador.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class CommandType(str, Enum):
    RAPID_MOVE      = "RAPID_MOVE"       # G0
    LINEAR_MOVE     = "LINEAR_MOVE"      # G1
    ARC_CW          = "ARC_CW"           # G2
    ARC_CCW         = "ARC_CCW"          # G3
    DRILL_CYCLE     = "DRILL_CYCLE"      # G81-G89
    TOOL_CHANGE     = "TOOL_CHANGE"      # T# M6
    SPINDLE_ON_CW   = "SPINDLE_ON_CW"    # M3
    SPINDLE_ON_CCW  = "SPINDLE_ON_CCW"   # M4
    SPINDLE_OFF     = "SPINDLE_OFF"      # M5
    COOLANT_ON      = "COOLANT_ON"       # M8
    COOLANT_OFF     = "COOLANT_OFF"      # M9
    SUBPROGRAM_CALL = "SUBPROGRAM_CALL"  # M98
    SUBPROGRAM_END  = "SUBPROGRAM_END"   # M99
    PROGRAM_END     = "PROGRAM_END"      # M30 / M2
    VARIABLE_SET    = "VARIABLE_SET"     # #var = expr
    CONDITIONAL     = "CONDITIONAL"      # IF [...] GOTO / IF [...] THEN
    LOOP            = "LOOP"             # WHILE [...] DO ... END
    COMPENSATION_ON = "COMPENSATION_ON"  # G41 / G42
    COMPENSATION_OFF= "COMPENSATION_OFF" # G40
    TOOL_LENGTH_ON  = "TOOL_LENGTH_ON"   # G43
    TOOL_LENGTH_OFF = "TOOL_LENGTH_OFF"  # G49
    MODAL_CHANGE    = "MODAL_CHANGE"     # G90/G91, G20/G21, G17/G18/G19, G98/G99
    HOME            = "HOME"             # G28
    COMMENT         = "COMMENT"          # ( texto ) o ; texto
    RAW             = "RAW"              # Línea no reconocida


class TranslationStatus(str, Enum):
    PENDING    = "pending"
    TRANSLATED = "translated"
    NEEDS_LLM  = "needs_llm"
    LLM_DONE   = "llm_done"
    RAW        = "raw"          # No se pudo traducir


class Dialect(str, Enum):
    FANUC   = "fanuc"
    SIEMENS = "siemens"
    HAAS    = "haas"
    UNKNOWN = "unknown"


# ─── Modal State ──────────────────────────────────────────────────────────────

class ModalState(BaseModel):
    """Estado modal de la máquina en un punto del programa."""
    positioning: str = "G90"   # G90=absoluto, G91=incremental
    plane:       str = "G17"   # G17=XY, G18=ZX, G19=YZ
    units:       str = "G21"   # G21=mm, G20=inches (Fanuc) / G71=mm, G70=inches (Siemens)
    retract:     str = "G98"   # G98=retract a posición inicial, G99=retract a R
    feed_mode:   str = "G94"   # G94=mm/min, G95=mm/rev
    active_tool: Optional[int] = None
    spindle_speed: Optional[float] = None
    feed_rate:   Optional[float] = None


# ─── Commands ─────────────────────────────────────────────────────────────────

class Point3D(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None


class ArcCenter(BaseModel):
    i: Optional[float] = None  # offset X desde posición actual
    j: Optional[float] = None  # offset Y
    k: Optional[float] = None  # offset Z
    r: Optional[float] = None  # radio (alternativa a IJK)
    # Regla de desambiguación: R positivo = arco corto (≤180°), R negativo = arco largo


class DrillParams(BaseModel):
    cycle_code: str            # "G83", "G81", etc.
    z:  Optional[float] = None # profundidad final
    r:  Optional[float] = None # plano R (retract)
    q:  Optional[float] = None # incremento peck (G83)
    p:  Optional[float] = None # dwell en ms (G82, G84)
    f:  Optional[float] = None # feed rate
    l:  Optional[int]   = None # repeticiones


class Command(BaseModel):
    type: CommandType
    original_text: str = ""
    translation_status: TranslationStatus = TranslationStatus.PENDING

    # Movimientos (RAPID, LINEAR, ARC)
    target: Optional[Point3D] = None
    arc:    Optional[ArcCenter] = None
    feed:   Optional[float] = None

    # Ciclos de taladrado
    drill:  Optional[DrillParams] = None

    # Tool change
    tool_number:   Optional[int] = None
    offset_number: Optional[int] = None  # H# para G43, D# para G41/G42

    # Spindle
    spindle_speed: Optional[float] = None
    spindle_dir:   Optional[str]   = None  # "CW" | "CCW"

    # Subprogramas
    subprogram_number: Optional[int]  = None
    subprogram_name:   Optional[str]  = None
    repeat_count:      Optional[int]  = None

    # Variables
    var_name:  Optional[str] = None   # "#100" o "R10"
    var_value: Optional[str] = None   # expresión como string

    # Condicional / Loop
    condition:  Optional[str] = None  # expresión como string
    goto_label: Optional[int] = None
    body:       Optional[List["Command"]] = None  # para WHILE

    # Modal
    modal_codes: Optional[List[str]] = None  # ["G90", "G21"]

    # Compensación
    comp_dir:    Optional[str] = None  # "LEFT" | "RIGHT"
    comp_offset: Optional[int] = None  # número de offset D#

    # Traducción Siemens (se llena después del translate node)
    siemens_params: Optional[Dict[str, Any]] = None

    # Metadata
    needs_llm: bool = False
    llm_confidence: Optional[float] = None


# ─── Block ────────────────────────────────────────────────────────────────────

class Block(BaseModel):
    """Una línea del programa G-code."""
    line_number:   Optional[int] = None    # N10, N20, etc.
    sequence:      int = 0                 # índice 0-based en el programa
    original_text: str = ""
    modal_state:   ModalState = Field(default_factory=ModalState)
    commands:      List[Command] = Field(default_factory=list)
    is_subprogram_def: bool = False        # True si es la línea Oxxx


# ─── Program ──────────────────────────────────────────────────────────────────

class Program(BaseModel):
    """El programa completo parseado."""
    dialect:      Dialect = Dialect.FANUC
    program_name: str = ""          # "O0001"
    raw_source:   str = ""
    blocks:       List[Block] = Field(default_factory=list)

    # Subprogramas embebidos en el mismo archivo
    subprograms:  Dict[str, "Program"] = Field(default_factory=dict)

    # Stats post-parse
    total_commands:   int = 0
    commands_need_llm: int = 0


# Necesario para referencias forward
Command.model_rebuild()
Program.model_rebuild()
