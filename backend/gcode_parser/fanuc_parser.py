"""
Parser de G-code Fanuc.
Convierte texto .nc a IR (Program).
"""
from __future__ import annotations
import re
from typing import Optional, Tuple
from models.ir import (
    Program, Block, Command, ModalState, Point3D, ArcCenter, DrillParams,
    CommandType, TranslationStatus, Dialect
)


# ─── Regex helpers ────────────────────────────────────────────────────────────

def _float(text: str, letter: str) -> Optional[float]:
    """Extrae el valor numérico de una letra en una línea. Ej: _float('X10.5 Y3', 'X') -> 10.5"""
    m = re.search(rf'{letter}([+-]?\d+\.?\d*)', text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _int(text: str, letter: str) -> Optional[int]:
    m = re.search(rf'{letter}(\d+)', text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _has(text: str, code: str) -> bool:
    """True si la línea contiene exactamente el código (ej. G83, M98)."""
    return bool(re.search(rf'\b{re.escape(code)}\b', text, re.IGNORECASE))


# ─── Dialect detection ────────────────────────────────────────────────────────

def detect_dialect(source: str) -> Dialect:
    """Detecta si el programa es Fanuc, Siemens u otro."""
    fanuc_score = 0
    siemens_score = 0

    if re.search(r'^O\d{4}', source, re.MULTILINE):
        fanuc_score += 3
    if re.search(r'#\d+', source):
        fanuc_score += 2
    if re.search(r'\bM98\b', source):
        fanuc_score += 2
    if re.search(r'\bG28\b', source):
        fanuc_score += 1

    if re.search(r'%_N_\w+_(MPF|SPF)', source):
        siemens_score += 3
    if re.search(r'\bCYCLE\d+', source):
        siemens_score += 3
    if re.search(r'\$[A-Z_]+', source):
        siemens_score += 2
    if re.search(r'\bCALL\b', source):
        siemens_score += 1
    if re.search(r'\bRET\b', source):
        siemens_score += 1

    if fanuc_score > siemens_score:
        return Dialect.FANUC
    if siemens_score > fanuc_score:
        return Dialect.SIEMENS
    return Dialect.UNKNOWN


# ─── Modal state tracker ──────────────────────────────────────────────────────

class ModalTracker:
    def __init__(self):
        self.state = ModalState()

    def update(self, line: str) -> ModalState:
        """Actualiza el estado modal con los códigos de esta línea y retorna snapshot."""
        upper = line.upper()

        if re.search(r'\bG90\b', upper): self.state.positioning = "G90"
        elif re.search(r'\bG91\b', upper): self.state.positioning = "G91"

        if re.search(r'\bG17\b', upper): self.state.plane = "G17"
        elif re.search(r'\bG18\b', upper): self.state.plane = "G18"
        elif re.search(r'\bG19\b', upper): self.state.plane = "G19"

        if re.search(r'\bG20\b', upper): self.state.units = "G20"
        elif re.search(r'\bG21\b', upper): self.state.units = "G21"

        if re.search(r'\bG98\b', upper): self.state.retract = "G98"
        elif re.search(r'\bG99\b', upper): self.state.retract = "G99"

        if re.search(r'\bG94\b', upper): self.state.feed_mode = "G94"
        elif re.search(r'\bG95\b', upper): self.state.feed_mode = "G95"

        s_val = _float(upper, 'S')
        if s_val is not None:
            self.state.spindle_speed = s_val

        f_val = _float(upper, 'F')
        if f_val is not None:
            self.state.feed_rate = f_val

        t_val = _int(upper, 'T')
        if t_val is not None:
            self.state.active_tool = t_val

        return self.state.model_copy()


# ─── Line parsers ─────────────────────────────────────────────────────────────

def _parse_move(line: str, cmd_type: CommandType, modal: ModalState) -> Command:
    upper = line.upper()
    target = Point3D(
        x=_float(upper, 'X'),
        y=_float(upper, 'Y'),
        z=_float(upper, 'Z'),
    )
    feed = _float(upper, 'F')
    arc = None

    if cmd_type in (CommandType.ARC_CW, CommandType.ARC_CCW):
        arc = ArcCenter(
            i=_float(upper, 'I'),
            j=_float(upper, 'J'),
            k=_float(upper, 'K'),
            r=_float(upper, 'R'),
        )

    return Command(
        type=cmd_type,
        original_text=line.strip(),
        target=target,
        arc=arc,
        feed=feed,
        translation_status=TranslationStatus.PENDING,
    )


def _parse_drill_cycle(line: str, cycle_code: str) -> Command:
    upper = line.upper()
    drill = DrillParams(
        cycle_code=cycle_code,
        z=_float(upper, 'Z'),
        r=_float(upper, 'R'),
        q=_float(upper, 'Q'),
        p=_float(upper, 'P'),
        f=_float(upper, 'F'),
        l=_int(upper, 'L'),
    )
    # Posición XY del primer agujero (si está en la misma línea)
    target = Point3D(x=_float(upper, 'X'), y=_float(upper, 'Y'))

    return Command(
        type=CommandType.DRILL_CYCLE,
        original_text=line.strip(),
        drill=drill,
        target=target,
        translation_status=TranslationStatus.PENDING,
    )


def _parse_tool_change(line: str) -> Command:
    upper = line.upper()
    return Command(
        type=CommandType.TOOL_CHANGE,
        original_text=line.strip(),
        tool_number=_int(upper, 'T'),
        translation_status=TranslationStatus.PENDING,
    )


def _parse_tool_length(line: str) -> Command:
    upper = line.upper()
    return Command(
        type=CommandType.TOOL_LENGTH_ON,
        original_text=line.strip(),
        offset_number=_int(upper, 'H'),
        translation_status=TranslationStatus.PENDING,
    )


def _parse_compensation(line: str, cmd_type: CommandType) -> Command:
    upper = line.upper()
    direction = None
    if cmd_type == CommandType.COMPENSATION_ON:
        direction = "LEFT" if re.search(r'\bG41\b', upper) else "RIGHT"
    return Command(
        type=cmd_type,
        original_text=line.strip(),
        comp_dir=direction,
        comp_offset=_int(upper, 'D'),
        translation_status=TranslationStatus.PENDING,
    )


def _parse_spindle(line: str) -> Command:
    upper = line.upper()
    if re.search(r'\bM3\b', upper):
        cmd_type = CommandType.SPINDLE_ON_CW
    elif re.search(r'\bM4\b', upper):
        cmd_type = CommandType.SPINDLE_ON_CCW
    else:
        cmd_type = CommandType.SPINDLE_OFF
    return Command(
        type=cmd_type,
        original_text=line.strip(),
        spindle_speed=_float(upper, 'S'),
        translation_status=TranslationStatus.PENDING,
    )


def _parse_subprogram_call(line: str) -> Command:
    upper = line.upper()
    return Command(
        type=CommandType.SUBPROGRAM_CALL,
        original_text=line.strip(),
        subprogram_number=_int(upper, 'P'),
        repeat_count=_int(upper, 'L') or 1,
        translation_status=TranslationStatus.PENDING,
    )


def _parse_variable(line: str) -> Command:
    """Parsea asignaciones de variables: #100 = #3011 + 30"""
    m = re.match(r'\s*(#\d+)\s*=\s*(.+)', line.strip(), re.IGNORECASE)
    if not m:
        return Command(type=CommandType.RAW, original_text=line.strip(),
                       translation_status=TranslationStatus.RAW)

    var_name = m.group(1)
    var_value = m.group(2).strip()

    # Detecta si usa variables de sistema que requieren LLM
    system_vars = {'#3011', '#3012'}
    needs_llm = any(sv in var_value for sv in system_vars)

    return Command(
        type=CommandType.VARIABLE_SET,
        original_text=line.strip(),
        var_name=var_name,
        var_value=var_value,
        needs_llm=needs_llm,
        translation_status=TranslationStatus.NEEDS_LLM if needs_llm else TranslationStatus.PENDING,
    )


def _parse_conditional(line: str) -> Command:
    """Parsea: IF [condicion] GOTO N / IF [condicion] THEN"""
    m = re.match(r'\s*IF\s*\[(.+?)\]\s*(?:GOTO\s*(\d+)|THEN)', line.strip(), re.IGNORECASE)
    if not m:
        return Command(type=CommandType.RAW, original_text=line.strip(),
                       translation_status=TranslationStatus.RAW)

    condition = m.group(1).strip()
    goto_label = int(m.group(2)) if m.group(2) else None

    return Command(
        type=CommandType.CONDITIONAL,
        original_text=line.strip(),
        condition=condition,
        goto_label=goto_label,
        needs_llm=True,
        translation_status=TranslationStatus.NEEDS_LLM,
    )


def _parse_modal_line(line: str) -> Command:
    upper = line.upper()
    codes = re.findall(r'G\d+(?:\.\d+)?', upper)
    return Command(
        type=CommandType.MODAL_CHANGE,
        original_text=line.strip(),
        modal_codes=codes,
        translation_status=TranslationStatus.PENDING,
    )


# ─── Main line classifier ─────────────────────────────────────────────────────

DRILL_CYCLES = {'G81', 'G82', 'G83', 'G84', 'G85', 'G86', 'G87', 'G88', 'G89'}
MODAL_ONLY   = {'G17', 'G18', 'G19', 'G90', 'G91', 'G20', 'G21', 'G94', 'G95', 'G98', 'G99', 'G80'}


def _classify_line(line: str, modal: ModalState, active_cycle: Optional[str] = None) -> list[Command]:
    """
    Clasifica una línea y retorna lista de Commands.
    Una línea puede tener múltiples comandos (T1 M6, S1200 M3, etc.)
    active_cycle: ciclo modal activo (ej. 'G83') para líneas XY de repetición.
    """
    stripped = line.strip()
    upper = stripped.upper()
    commands = []

    # Ignorar línea vacía, % delimitador, número de programa O####
    if not stripped or stripped == '%' or re.match(r'^O\d+$', stripped):
        return commands

    # Comentario
    if stripped.startswith('(') or stripped.startswith(';'):
        commands.append(Command(
            type=CommandType.COMMENT,
            original_text=stripped,
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    # Quitar N#### para los checks de variable y condicional
    stripped_no_n = re.sub(r'^N\d+\s*', '', stripped)

    # Variable assignment (#100 = ...)
    if re.match(r'\s*#\d+\s*=', stripped_no_n):
        commands.append(_parse_variable(stripped_no_n))
        return commands

    # Condicional
    if re.match(r'\s*IF\s*\[', stripped_no_n, re.IGNORECASE):
        commands.append(_parse_conditional(stripped_no_n))
        return commands

    # Quitar número de secuencia N## para el análisis
    clean = re.sub(r'^N\d+\s*', '', upper)

    # Ciclos de taladrado
    for cycle in DRILL_CYCLES:
        if re.search(rf'\b{cycle}\b', clean):
            commands.append(_parse_drill_cycle(stripped, cycle))
            return commands

    # G80 - cancelar ciclo
    if re.search(r'\bG80\b', clean):
        commands.append(Command(
            type=CommandType.MODAL_CHANGE,
            original_text=stripped,
            modal_codes=['G80'],
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    # Movimientos
    if re.search(r'\bG0\b', clean) and not re.search(r'\bG0[1-9]\b', clean):
        commands.append(_parse_move(stripped, CommandType.RAPID_MOVE, modal))
        # G28 puede ir junto con G0/G91
        if re.search(r'\bG28\b', clean):
            commands[-1].type = CommandType.HOME
        return commands

    if re.search(r'\bG1\b', clean) and not re.search(r'\bG1[0-9]\b', clean):
        commands.append(_parse_move(stripped, CommandType.LINEAR_MOVE, modal))
        return commands

    if re.search(r'\bG2\b', clean) and not re.search(r'\bG2[0-9]\b', clean):
        commands.append(_parse_move(stripped, CommandType.ARC_CW, modal))
        return commands

    if re.search(r'\bG3\b', clean) and not re.search(r'\bG3[0-9]\b', clean):
        commands.append(_parse_move(stripped, CommandType.ARC_CCW, modal))
        return commands

    # Compensación
    if re.search(r'\bG41\b', clean) or re.search(r'\bG42\b', clean):
        commands.append(_parse_compensation(stripped, CommandType.COMPENSATION_ON))
        return commands

    if re.search(r'\bG40\b', clean):
        commands.append(_parse_compensation(stripped, CommandType.COMPENSATION_OFF))
        return commands

    if re.search(r'\bG43\b', clean):
        commands.append(_parse_tool_length(stripped))
        return commands

    if re.search(r'\bG49\b', clean):
        commands.append(Command(
            type=CommandType.TOOL_LENGTH_OFF,
            original_text=stripped,
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    # Tool change (T# M6)
    if re.search(r'\bM6\b', clean):
        commands.append(_parse_tool_change(stripped))
        return commands

    # Spindle
    if re.search(r'\bM[345]\b', clean):
        commands.append(_parse_spindle(stripped))
        return commands

    # Coolant
    if re.search(r'\bM8\b', clean):
        commands.append(Command(
            type=CommandType.COOLANT_ON,
            original_text=stripped,
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    if re.search(r'\bM9\b', clean):
        commands.append(Command(
            type=CommandType.COOLANT_OFF,
            original_text=stripped,
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    # Subprograma
    if re.search(r'\bM98\b', clean):
        commands.append(_parse_subprogram_call(stripped))
        return commands

    if re.search(r'\bM99\b', clean):
        commands.append(Command(
            type=CommandType.SUBPROGRAM_END,
            original_text=stripped,
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    # Fin de programa
    if re.search(r'\bM30\b', clean) or re.search(r'\bM2\b', clean):
        commands.append(Command(
            type=CommandType.PROGRAM_END,
            original_text=stripped,
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    # Solo códigos modales (G90 G21 G17 etc.)
    modal_codes = re.findall(r'\bG\d+\b', clean)
    if modal_codes and all(c in MODAL_ONLY for c in modal_codes):
        commands.append(Command(
            type=CommandType.MODAL_CHANGE,
            original_text=stripped,
            modal_codes=modal_codes,
            translation_status=TranslationStatus.PENDING,
        ))
        return commands

    # Línea con solo XY — si hay ciclo modal activo, es repetición del ciclo
    if re.search(r'[XY][+-]?\d', clean) and not re.search(r'[GMTFS]', clean):
        if active_cycle and active_cycle in DRILL_CYCLES:
            # Posición nueva para el mismo ciclo modal
            target = Point3D(x=_float(clean, 'X'), y=_float(clean, 'Y'))
            commands.append(Command(
                type=CommandType.DRILL_CYCLE,
                original_text=stripped,
                drill=DrillParams(cycle_code=active_cycle),
                target=target,
                translation_status=TranslationStatus.PENDING,
            ))
        else:
            commands.append(_parse_move(stripped, CommandType.LINEAR_MOVE, modal))
        return commands

    # No reconocido -> RAW
    commands.append(Command(
        type=CommandType.RAW,
        original_text=stripped,
        translation_status=TranslationStatus.RAW,
    ))
    return commands


# ─── Main parser ──────────────────────────────────────────────────────────────

def parse_fanuc(source: str) -> Program:
    """
    Parsea código G-code Fanuc y retorna un Program (IR).
    """
    dialect = detect_dialect(source)
    program = Program(dialect=dialect, raw_source=source)

    # Extraer nombre del programa (O####)
    m = re.search(r'^O(\d+)', source, re.MULTILINE)
    if m:
        program.program_name = f"O{m.group(1)}"

    modal = ModalTracker()
    lines = source.splitlines()

    current_program = program
    main_program_seen = False  # True tras consumir el O#### del programa principal
    subprogram_name = None
    active_cycle: Optional[str] = None  # ciclo modal activo (G81-G89)

    for seq, raw_line in enumerate(lines):
        line = raw_line.strip()

        # O#### → primer match = programa principal (skip), siguientes = subprogramas
        sub_match = re.match(r'^O(\d{4,})$', line)
        if sub_match:
            if not main_program_seen:
                main_program_seen = True
                continue  # ya guardamos el nombre arriba
            subprogram_name = f"O{sub_match.group(1)}"
            sub_prog = Program(
                dialect=Dialect.FANUC,
                program_name=subprogram_name,
                raw_source="",
            )
            program.subprograms[subprogram_name] = sub_prog
            current_program = sub_prog
            active_cycle = None  # reset al entrar en subprograma
            continue

        # Trackear ciclo modal activo
        upper_line = line.upper()
        for cycle in DRILL_CYCLES:
            if re.search(rf'\b{cycle}\b', upper_line):
                active_cycle = cycle
                break
        if re.search(r'\bG80\b', upper_line) or re.search(r'\bM30\b', upper_line):
            active_cycle = None

        # Actualizar estado modal con esta línea
        snap = modal.update(line)

        # Extraer número de secuencia
        n_match = re.match(r'^N(\d+)', line.upper())
        line_number = int(n_match.group(1)) if n_match else None

        commands = _classify_line(line, snap, active_cycle)

        if not commands:
            continue

        block = Block(
            line_number=line_number,
            sequence=seq,
            original_text=raw_line,
            modal_state=snap,
            commands=commands,
        )
        current_program.blocks.append(block)

    # Stats
    total = sum(len(b.commands) for b in program.blocks)
    needs_llm = sum(
        1 for b in program.blocks
        for c in b.commands
        if c.needs_llm
    )
    program.total_commands = total
    program.commands_need_llm = needs_llm

    return program
