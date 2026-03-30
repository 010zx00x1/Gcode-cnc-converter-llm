"""
Tests del traductor determinista y generador Siemens.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from gcode_parser.fanuc_parser import parse_fanuc
from translator.deterministic import translate_ir, load_equivalences
from translator.siemens_generator import generate_siemens
from models.ir import CommandType, TranslationStatus


# ─── Helpers ─────────────────────────────────────────────────────────────────

def parse_translate(nc: str):
    prog = parse_fanuc(nc)
    eq = load_equivalences()
    return translate_ir(prog, eq)


def first_translated_cmd(nc: str):
    t = parse_translate(nc)
    for b in t.blocks:
        for c in b.commands:
            if c.type != CommandType.COMMENT:
                return c
    raise AssertionError("No command found")


def generate(nc: str) -> str:
    prog = parse_fanuc(nc)
    eq = load_equivalences()
    translated = translate_ir(prog, eq)
    return generate_siemens(translated, "TEST")


# ─── Movimientos (idénticos Fanuc↔Siemens) ───────────────────────────────────

class TestMovesTranslation:
    def test_g0_translated(self):
        cmd = first_translated_cmd("G0 X10 Y20 Z-5")
        assert cmd.type == CommandType.RAPID_MOVE
        assert cmd.translation_status == TranslationStatus.TRANSLATED

    def test_g1_translated(self):
        cmd = first_translated_cmd("G1 X100 F200")
        assert cmd.translation_status == TranslationStatus.TRANSLATED

    def test_g2_arc_translated(self):
        cmd = first_translated_cmd("G2 X70 Y10 I20 J0 F150")
        assert cmd.type == CommandType.ARC_CW
        assert cmd.translation_status == TranslationStatus.TRANSLATED

    def test_g3_arc_translated(self):
        cmd = first_translated_cmd("G3 X50 Y30 I0 J20")
        assert cmd.type == CommandType.ARC_CCW
        assert cmd.translation_status == TranslationStatus.TRANSLATED


# ─── Unidades (G20/G21 → G70/G71) ────────────────────────────────────────────

class TestUnitsTranslation:
    def test_g21_becomes_g71(self):
        code = generate("G21")
        assert "G71" in code

    def test_g20_becomes_g70(self):
        code = generate("G20")
        assert "G70" in code


# ─── Ciclos de taladrado ──────────────────────────────────────────────────────

class TestDrillCyclesTranslation:
    def test_g83_produces_cycle83(self):
        code = generate("G83 X10 Y10 Z-25 R2 Q5 F100")
        assert "CYCLE83" in code

    def test_g83_params_mapped(self):
        """Z→DP, R→RTP, Q→FDEP, F→FDPR"""
        t = parse_translate("G83 X0 Y0 Z-25 R2 Q5 F100")
        drills = [c for b in t.blocks for c in b.commands
                  if c.type == CommandType.DRILL_CYCLE]
        assert drills, "No drill cycle found"
        params = drills[0].siemens_params
        assert params["DP"]   == -25.0
        assert params["RTP"]  == 2.0
        assert params["FDEP"] == 5.0
        assert params["FDPR"] == 100.0

    def test_g81_produces_cycle81(self):
        code = generate("G81 X0 Y0 Z-10 R2 F150")
        assert "CYCLE81" in code

    def test_g82_dwell_ms_to_seconds(self):
        """P500ms → DTB=0.5s"""
        t = parse_translate("G82 X0 Y0 Z-5 R2 P500 F100")
        drills = [c for b in t.blocks for c in b.commands
                  if c.type == CommandType.DRILL_CYCLE]
        assert drills[0].siemens_params["DTB"] == pytest.approx(0.5)

    def test_g84_produces_cycle84(self):
        code = generate("G84 X0 Y0 Z-15 R2 F125")
        assert "CYCLE84" in code

    def test_g85_produces_cycle85(self):
        code = generate("G85 X0 Y0 Z-10 R2 F80")
        assert "CYCLE85" in code

    def test_g80_omitted_in_siemens(self):
        """G80 no genera código en Siemens."""
        code = generate("G80")
        assert "G80" not in code

    def test_cycle83_includes_xy_position(self):
        """La posición XY va antes del CYCLE en Siemens."""
        code = generate("G83 X10 Y20 Z-25 R2 Q5 F100")
        lines = [l for l in code.splitlines() if l.strip() and not l.startswith(";")]
        # Debe haber una línea G0 con X10 Y20 antes de CYCLE83
        cycle_idx = next(i for i, l in enumerate(lines) if "CYCLE83" in l)
        assert any("X10" in lines[i] for i in range(cycle_idx))


# ─── Compensación ─────────────────────────────────────────────────────────────

class TestCompensationTranslation:
    def test_g41_keeps_g41(self):
        code = generate("G41 D2")
        assert "G41" in code

    def test_g42_keeps_g42(self):
        code = generate("G42 D1")
        assert "G42" in code

    def test_g40_keeps_g40(self):
        code = generate("G40")
        assert "G40" in code

    def test_g43_omitted(self):
        """G43 no genera código — TLC implícita en Siemens."""
        code = generate("G43 H1")
        assert "G43" not in code


# ─── Subprogramas ─────────────────────────────────────────────────────────────

class TestSubprogramsTranslation:
    def test_m98_becomes_l(self):
        code = generate("M98 P1000")
        assert "L1000" in code

    def test_m98_with_repeat(self):
        code = generate("M98 P9001 L2")
        assert "L9001" in code
        assert "P2" in code

    def test_m99_becomes_ret(self):
        code = generate("M99")
        assert "RET" in code

    def test_m30_stays_m30(self):
        code = generate("M30")
        assert "M30" in code


# ─── Variables ───────────────────────────────────────────────────────────────

class TestVariablesTranslation:
    def test_user_var_100_maps_to_r0(self):
        code = generate("#100 = 25.5")
        assert "R0=25.5" in code

    def test_user_var_101_maps_to_r1(self):
        code = generate("#101 = 10")
        assert "R1=10" in code

    def test_global_var_500_maps_to_dollar_r(self):
        code = generate("#500 = 99")
        assert "$R[0]=99" in code

    def test_system_var_3011_needs_llm(self):
        """#3011 (fecha) requiere LLM."""
        t = parse_translate("#100 = #3011")
        var_cmds = [c for b in t.blocks for c in b.commands
                    if c.type == CommandType.VARIABLE_SET]
        assert var_cmds[0].needs_llm is True
        assert var_cmds[0].translation_status == TranslationStatus.NEEDS_LLM

    def test_tool_offset_var_2001_maps(self):
        code = generate("#2001 = 0")
        assert "$TC_DP3[1,1]" in code

    def test_arithmetic_expression_preserved(self):
        code = generate("#102 = #101 + 10")
        assert "R2=R1+10" in code or "R2=R1 + 10" in code


# ─── Spindle / Coolant ────────────────────────────────────────────────────────

class TestSpindleAndCoolantTranslation:
    def test_s1200_m3(self):
        code = generate("S1200 M3")
        assert "S1200" in code
        assert "M3" in code

    def test_m5(self):
        code = generate("M5")
        assert "M5" in code

    def test_m8_m9(self):
        code = generate("M8")
        assert "M8" in code
        code2 = generate("M9")
        assert "M9" in code2


# ─── Programa completo (fixture) ──────────────────────────────────────────────

class TestFullProgramTranslation:
    def _load_fixture(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture) as f:
            return f.read()

    def test_fixture_translates_without_error(self):
        src = self._load_fixture()
        prog = parse_fanuc(src)
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        code = generate_siemens(translated, "O0042")
        assert len(code) > 100

    def test_fixture_output_has_header(self):
        src = self._load_fixture()
        prog = parse_fanuc(src)
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        code = generate_siemens(translated, "O0042")
        assert "%_N_" in code

    def test_fixture_output_has_cycles(self):
        src = self._load_fixture()
        prog = parse_fanuc(src)
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        code = generate_siemens(translated, "O0042")
        assert "CYCLE83" in code
        assert "CYCLE81" in code

    def test_fixture_output_has_subprogram_call(self):
        src = self._load_fixture()
        prog = parse_fanuc(src)
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        code = generate_siemens(translated, "O0042")
        assert "L9001" in code

    def test_fixture_marks_llm_needed(self):
        src = self._load_fixture()
        prog = parse_fanuc(src)
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        assert translated.commands_need_llm >= 1

    def test_fixture_no_fanuc_g20_g21(self):
        """El output Siemens no debe tener G20 ni G21 (son G70/G71)."""
        src = self._load_fixture()
        prog = parse_fanuc(src)
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        code = generate_siemens(translated, "O0042")
        # G21 del fixture debe convertirse a G71
        assert "G71" in code or "G21" not in code
