"""
Tests del parser Fanuc.
TDD: estos tests definen el comportamiento esperado del parser.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from gcode_parser.fanuc_parser import parse_fanuc, detect_dialect
from models.ir import (
    CommandType, TranslationStatus, Dialect, ModalState
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def first_command(nc_line: str):
    """Parsea una sola línea y retorna el primer command."""
    prog = parse_fanuc(nc_line)
    assert prog.blocks, f"No se generaron bloques para: {nc_line!r}"
    assert prog.blocks[0].commands, f"No se generaron commands para: {nc_line!r}"
    return prog.blocks[0].commands[0]


def commands_of_type(program, cmd_type):
    return [
        c for b in program.blocks
        for c in b.commands
        if c.type == cmd_type
    ]


# ─── Dialect detection ────────────────────────────────────────────────────────

class TestDialectDetection:
    def test_fanuc_detected_by_o_number(self):
        assert detect_dialect("O0001\nG0 X0 Y0") == Dialect.FANUC

    def test_fanuc_detected_by_hash_variable(self):
        assert detect_dialect("#100 = 5.0\nM30") == Dialect.FANUC

    def test_fanuc_detected_by_m98(self):
        assert detect_dialect("M98 P1000") == Dialect.FANUC

    def test_siemens_detected_by_cycle(self):
        assert detect_dialect("CYCLE83(2.0, 0, 2.0, -25.0)") == Dialect.SIEMENS

    def test_siemens_detected_by_dollar_variable(self):
        assert detect_dialect("$AC_TIMER = 0") == Dialect.SIEMENS


# ─── Movimientos básicos ──────────────────────────────────────────────────────

class TestBasicMoves:
    def test_rapid_move_g0(self):
        cmd = first_command("G0 X10.0 Y20.0 Z-5.0")
        assert cmd.type == CommandType.RAPID_MOVE
        assert cmd.target.x == 10.0
        assert cmd.target.y == 20.0
        assert cmd.target.z == -5.0

    def test_rapid_move_n_prefix(self):
        cmd = first_command("N80 G0 X0 Y0")
        assert cmd.type == CommandType.RAPID_MOVE
        assert cmd.target.x == 0.0

    def test_linear_move_g1(self):
        cmd = first_command("G1 X100.0 Y0 F200.0")
        assert cmd.type == CommandType.LINEAR_MOVE
        assert cmd.target.x == 100.0
        assert cmd.feed == 200.0

    def test_arc_cw_g2_ij(self):
        cmd = first_command("G2 X70.0 Y10.0 I20.0 J0.0 F150.0")
        assert cmd.type == CommandType.ARC_CW
        assert cmd.target.x == 70.0
        assert cmd.arc.i == 20.0
        assert cmd.arc.j == 0.0

    def test_arc_ccw_g3_ij(self):
        cmd = first_command("G3 X50.0 Y30.0 I0.0 J20.0")
        assert cmd.type == CommandType.ARC_CCW
        assert cmd.arc.i == 0.0
        assert cmd.arc.j == 20.0

    def test_arc_with_radius(self):
        cmd = first_command("G2 X10.0 Y10.0 R5.0")
        assert cmd.type == CommandType.ARC_CW
        assert cmd.arc.r == 5.0
        assert cmd.arc.i is None

    def test_negative_z(self):
        cmd = first_command("G1 Z-25.5 F80.0")
        assert cmd.target.z == -25.5

    def test_partial_coords(self):
        """Solo X, sin Y ni Z."""
        cmd = first_command("G1 X50.0")
        assert cmd.target.x == 50.0
        assert cmd.target.y is None
        assert cmd.target.z is None


# ─── Ciclos de taladrado ──────────────────────────────────────────────────────

class TestDrillCycles:
    def test_g83_peck_drilling(self):
        cmd = first_command("G83 X10.0 Y10.0 Z-25.0 R2.0 Q5.0 F100.0")
        assert cmd.type == CommandType.DRILL_CYCLE
        assert cmd.drill.cycle_code == "G83"
        assert cmd.drill.z == -25.0
        assert cmd.drill.r == 2.0
        assert cmd.drill.q == 5.0
        assert cmd.drill.f == 100.0
        assert cmd.target.x == 10.0
        assert cmd.target.y == 10.0

    def test_g81_simple_drill(self):
        cmd = first_command("G81 X60.0 Y60.0 Z-10.0 R2.0 F150.0")
        assert cmd.type == CommandType.DRILL_CYCLE
        assert cmd.drill.cycle_code == "G81"
        assert cmd.drill.z == -10.0
        assert cmd.drill.q is None

    def test_g82_dwell(self):
        cmd = first_command("G82 X0 Y0 Z-5.0 R2.0 P500 F100.0")
        assert cmd.drill.cycle_code == "G82"
        assert cmd.drill.p == 500.0

    def test_g84_tapping(self):
        cmd = first_command("G84 X0 Y0 Z-15.0 R2.0 F125.0")
        assert cmd.drill.cycle_code == "G84"

    def test_g80_cancel(self):
        cmd = first_command("G80")
        assert cmd.type == CommandType.MODAL_CHANGE
        assert "G80" in cmd.modal_codes


# ─── Compensación de radio ────────────────────────────────────────────────────

class TestCompensation:
    def test_g41_left(self):
        cmd = first_command("G41 D2")
        assert cmd.type == CommandType.COMPENSATION_ON
        assert cmd.comp_dir == "LEFT"
        assert cmd.comp_offset == 2

    def test_g42_right(self):
        cmd = first_command("G42 D1")
        assert cmd.type == CommandType.COMPENSATION_ON
        assert cmd.comp_dir == "RIGHT"

    def test_g40_cancel(self):
        cmd = first_command("G40")
        assert cmd.type == CommandType.COMPENSATION_OFF

    def test_g43_tool_length(self):
        cmd = first_command("G43 H1")
        assert cmd.type == CommandType.TOOL_LENGTH_ON
        assert cmd.offset_number == 1


# ─── Tool change ─────────────────────────────────────────────────────────────

class TestToolChange:
    def test_t1_m6(self):
        cmd = first_command("T1 M6")
        assert cmd.type == CommandType.TOOL_CHANGE
        assert cmd.tool_number == 1

    def test_t2_m6(self):
        cmd = first_command("T2 M6")
        assert cmd.tool_number == 2


# ─── Spindle & coolant ────────────────────────────────────────────────────────

class TestSpindleAndCoolant:
    def test_m3_spindle_cw(self):
        cmd = first_command("S1200 M3")
        assert cmd.type == CommandType.SPINDLE_ON_CW
        assert cmd.spindle_speed == 1200.0

    def test_m5_spindle_off(self):
        cmd = first_command("M5")
        assert cmd.type == CommandType.SPINDLE_OFF

    def test_m8_coolant_on(self):
        cmd = first_command("M8")
        assert cmd.type == CommandType.COOLANT_ON

    def test_m9_coolant_off(self):
        cmd = first_command("M9")
        assert cmd.type == CommandType.COOLANT_OFF


# ─── Subprogramas ─────────────────────────────────────────────────────────────

class TestSubprograms:
    def test_m98_call(self):
        cmd = first_command("M98 P9001 L2")
        assert cmd.type == CommandType.SUBPROGRAM_CALL
        assert cmd.subprogram_number == 9001
        assert cmd.repeat_count == 2

    def test_m98_no_repeat(self):
        cmd = first_command("M98 P1000")
        assert cmd.subprogram_number == 1000
        assert cmd.repeat_count == 1

    def test_m99_end(self):
        cmd = first_command("M99")
        assert cmd.type == CommandType.SUBPROGRAM_END

    def test_m30_end(self):
        cmd = first_command("M30")
        assert cmd.type == CommandType.PROGRAM_END


# ─── Variables ───────────────────────────────────────────────────────────────

class TestVariables:
    def test_user_variable_assignment(self):
        cmd = first_command("#101 = 25.5")
        assert cmd.type == CommandType.VARIABLE_SET
        assert cmd.var_name == "#101"
        assert cmd.var_value == "25.5"
        assert cmd.needs_llm is False

    def test_system_variable_needs_llm(self):
        cmd = first_command("#100 = #3011")
        assert cmd.type == CommandType.VARIABLE_SET
        assert cmd.needs_llm is True
        assert cmd.translation_status == TranslationStatus.NEEDS_LLM

    def test_arithmetic_expression(self):
        cmd = first_command("#102 = #101 + 10.0")
        assert cmd.var_value == "#101 + 10.0"


# ─── Condicionales ────────────────────────────────────────────────────────────

class TestConditionals:
    def test_if_goto(self):
        cmd = first_command("IF [#101 GT 20.0] GOTO 480")
        assert cmd.type == CommandType.CONDITIONAL
        assert cmd.condition == "#101 GT 20.0"
        assert cmd.goto_label == 480
        assert cmd.needs_llm is True

    def test_if_goto_needs_llm(self):
        cmd = first_command("IF [#100 EQ 0] GOTO 100")
        assert cmd.translation_status == TranslationStatus.NEEDS_LLM


# ─── Modal state tracking ────────────────────────────────────────────────────

class TestModalState:
    def test_g90_g21_g17_tracked(self):
        prog = parse_fanuc("N10 G21 G17 G90 G94\nN20 G0 X0 Y0")
        move_block = prog.blocks[1]
        assert move_block.modal_state.units == "G21"
        assert move_block.modal_state.plane == "G17"
        assert move_block.modal_state.positioning == "G90"

    def test_g91_incremental_tracked(self):
        prog = parse_fanuc("G91\nG0 X5.0")
        assert prog.blocks[1].modal_state.positioning == "G91"

    def test_g98_g99_tracked(self):
        prog = parse_fanuc("G99\nG83 Z-25 R2 Q5 F100")
        drill_block = prog.blocks[1]
        assert drill_block.modal_state.retract == "G99"


# ─── Programa completo (fixture) ──────────────────────────────────────────────

class TestFullProgram:
    def test_fixture_parses_without_error(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture, 'r') as f:
            source = f.read()
        prog = parse_fanuc(source)
        assert prog.program_name == "O0042"
        assert prog.total_commands > 0

    def test_fixture_has_drill_cycles(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture, 'r') as f:
            source = f.read()
        prog = parse_fanuc(source)
        drills = commands_of_type(prog, CommandType.DRILL_CYCLE)
        assert len(drills) >= 5  # 3x G83 + 2x G81 en el fixture

    def test_fixture_has_subprogram(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture, 'r') as f:
            source = f.read()
        prog = parse_fanuc(source)
        calls = commands_of_type(prog, CommandType.SUBPROGRAM_CALL)
        assert len(calls) >= 1
        assert calls[0].subprogram_number == 9001

    def test_fixture_detects_llm_needed(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture, 'r') as f:
            source = f.read()
        prog = parse_fanuc(source)
        # #100 = #3011 debe marcar needs_llm
        assert prog.commands_need_llm >= 1

    def test_fixture_has_embedded_subprogram(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture, 'r') as f:
            source = f.read()
        prog = parse_fanuc(source)
        assert "O9001" in prog.subprograms
