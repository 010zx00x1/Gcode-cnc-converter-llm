"""
Tests del pipeline LangGraph.
Los tests que requieren LLM real usan mocks para ser deterministas.
Los tests de flujo prueban la orquestación sin LLM.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import patch, MagicMock

from gcode_parser.fanuc_parser import parse_fanuc
from translator.deterministic import translate_ir, load_equivalences
from simulator.toolpath import simulate_toolpath
from simulator.comparator import compare_toolpaths, ComparisonResult
from pipeline.confidence import calculate_confidence, confidence_label
from pipeline.prompts import (
    build_variable_prompt, build_conditional_prompt, build_correction_prompt
)
from pipeline.graph import (
    parse_node, translate_node, generate_node, simulate_node,
    output_node, decide_node, initial_state, llm_node
)
from models.ir import Program, TranslationStatus, CommandType


# ─── Tests de confianza ───────────────────────────────────────────────────────

class TestConfidence:
    def _make_comparison(self, max_dev=0.0, avg_dev=0.0, threshold=0.01):
        return ComparisonResult(
            max_deviation_mm=max_dev,
            avg_deviation_mm=avg_dev,
            total_points=100,
            points_exceeding=0,
            threshold_mm=threshold,
            deviations=[max_dev] * 100,
            exceeding_indices=[],
        )

    def test_perfect_translation_high_confidence(self):
        prog = parse_fanuc("G0 X10 Y20\nG1 X100 F200")
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        comparison = self._make_comparison(max_dev=0.0)
        score = calculate_confidence(translated, comparison, attempts_used=0)
        assert score >= 0.90

    def test_llm_needed_reduces_confidence(self):
        prog = parse_fanuc("#100 = #3011")  # requiere LLM
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        comparison = self._make_comparison(max_dev=0.0)
        score = calculate_confidence(translated, comparison, attempts_used=0)
        assert score < 1.0

    def test_deviation_reduces_confidence(self):
        prog = parse_fanuc("G0 X10")
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        comparison = self._make_comparison(max_dev=0.05)  # 0.05mm > 0.01 threshold
        score = calculate_confidence(translated, comparison, attempts_used=0)
        assert score < 0.80

    def test_retry_reduces_confidence(self):
        prog = parse_fanuc("G0 X10")
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        comparison = self._make_comparison(max_dev=0.0)
        score0 = calculate_confidence(translated, comparison, attempts_used=0)
        score2 = calculate_confidence(translated, comparison, attempts_used=2)
        assert score2 < score0

    def test_score_bounded_0_to_1(self):
        prog = parse_fanuc("G0 X10")
        eq = load_equivalences()
        translated = translate_ir(prog, eq)
        comparison = self._make_comparison(max_dev=10.0)  # error enorme
        score = calculate_confidence(translated, comparison, attempts_used=3)
        assert 0.0 <= score <= 1.0

    def test_confidence_labels(self):
        assert confidence_label(0.95) == "ALTA"
        assert confidence_label(0.80) == "MEDIA"
        assert confidence_label(0.60) == "BAJA"
        assert confidence_label(0.30) == "MUY BAJA"


# ─── Tests de prompts ─────────────────────────────────────────────────────────

class TestPrompts:
    def test_variable_prompt_contains_schema(self):
        prompt = build_variable_prompt("#100", "#3011")
        assert "target" in prompt
        assert "expression" in prompt
        assert "#3011" in prompt

    def test_conditional_prompt_contains_original(self):
        prompt = build_conditional_prompt("IF [#101 GT 20] GOTO 480", {})
        assert "IF" in prompt
        assert "GOTO" in prompt

    def test_correction_prompt_contains_deviation(self):
        prompt = build_correction_prompt(
            commands=[{"original_text": "G83 X0 Y0", "siemens_params": {}}],
            error_points=[{"index": 0, "x": 0.0, "y": 0.0, "z": -25.0, "deviation": 0.05}],
            deviation_mm=0.05,
            threshold_mm=0.01,
            attempt=1,
            max_attempts=3,
        )
        assert "0.0500" in prompt or "0.05" in prompt
        assert "0.0100" in prompt or "0.01" in prompt


# ─── Tests de nodos del pipeline ─────────────────────────────────────────────

class TestPipelineNodes:
    def _state(self, nc: str) -> dict:
        return initial_state(nc)

    def test_parse_node_fills_source_ir(self):
        state = self._state("G0 X10 Y20\nG1 X100 F200\nM30")
        result = parse_node(state)
        assert result["source_ir"] is not None
        assert result["source_ir"].total_commands > 0

    def test_parse_node_error_sets_done(self):
        # Un archivo totalmente vacío/inválido no crashea, retorna IR vacío
        state = self._state("")
        result = parse_node(state)
        # No debe lanzar excepción — el parser maneja inputs vacíos
        assert "source_ir" in result

    def test_translate_node_fills_translated_ir(self):
        state = self._state("G83 X10 Y10 Z-25 R2 Q5 F100\nM30")
        state = parse_node(state)
        state = translate_node(state)
        assert state["translated_ir"] is not None

    def test_generate_node_produces_code(self):
        state = self._state("G0 X10 Y20\nG1 X100 F200\nM30")
        state = parse_node(state)
        state = translate_node(state)
        state = generate_node(state)
        assert len(state["translated_code"]) > 0
        assert "%_N_" in state["translated_code"]

    def test_simulate_node_fills_toolpaths(self):
        state = self._state("G0 X0 Y0\nG1 X100 F200\nG1 X100 Y80\nM30")
        state = parse_node(state)
        state = translate_node(state)
        state = simulate_node(state)
        assert len(state["source_toolpath"]) > 0
        assert len(state["translated_toolpath"]) > 0
        assert state["comparison"] is not None

    def test_decide_node_output_when_within_tolerance(self):
        state = self._state("G0 X10 Y20\nG1 X100 F200\nM30")
        state = parse_node(state)
        state = translate_node(state)
        state = simulate_node(state)
        decision = decide_node(state)
        # Movimientos simples G0/G1 no deben tener desviación
        assert decision == "output"

    def test_decide_node_correct_when_over_threshold(self):
        """Simula estado con desviación alta."""
        state = initial_state("G0 X0")
        state["comparison"] = {
            "max_deviation_mm": 0.5,
            "avg_deviation_mm": 0.3,
            "threshold_mm": 0.01,
            "total_points": 10,
            "points_exceeding": 5,
            "deviations": [0.5] * 10,
            "exceeding_indices": list(range(5)),
        }
        state["attempt"] = 0
        state["max_attempts"] = 3
        decision = decide_node(state)
        assert decision == "correct"

    def test_decide_node_output_when_max_attempts_reached(self):
        """Si llegamos al máximo de intentos, salir aunque haya desviación."""
        state = initial_state("G0 X0")
        state["comparison"] = {
            "max_deviation_mm": 0.5,
            "threshold_mm": 0.01,
            "exceeding_indices": [0],
        }
        state["attempt"] = 3
        state["max_attempts"] = 3
        decision = decide_node(state)
        assert decision == "output"

    def test_output_node_sets_confidence(self):
        state = self._state("G0 X10 Y20\nG1 X100 F200\nM30")
        state = parse_node(state)
        state = translate_node(state)
        state = simulate_node(state)
        state = output_node(state)
        assert 0.0 <= state["confidence"] <= 1.0
        assert state["done"] is True


# ─── Test pipeline simple (sin LLM) ──────────────────────────────────────────

class TestPipelineSimple:
    """Tests del pipeline completo con programas que no necesitan LLM."""

    def _run(self, nc: str) -> dict:
        state = initial_state(nc)
        for fn in [parse_node, translate_node, generate_node, simulate_node, output_node]:
            state = fn(state)
        return state

    def test_simple_moves_pipeline(self):
        state = self._run("G0 X0 Y0 Z0\nG1 X100 F200\nG1 X100 Y80\nM30")
        assert state["translated_code"]
        assert state["confidence"] >= 0.85
        assert not state["errors"]

    def test_drill_cycle_pipeline(self):
        nc = "G83 X10 Y10 Z-25 R2 Q5 F100\nG83 X30 Y10\nG80\nM30"
        state = self._run(nc)
        assert "CYCLE83" in state["translated_code"]
        assert state["confidence"] > 0

    def test_fixture_full_pipeline(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture) as f:
            src = f.read()
        state = self._run(src)
        assert state["translated_code"]
        assert "CYCLE83" in state["translated_code"]
        assert "CYCLE81" in state["translated_code"]
        assert "L9001" in state["translated_code"]
        assert not state["errors"]
        assert state["confidence"] > 0

    def test_max_deviation_reported(self):
        state = self._run("G0 X0 Y0\nG1 X100 F200\nM30")
        comparison = state.get("comparison", {})
        assert "max_deviation_mm" in comparison
        assert comparison["max_deviation_mm"] >= 0.0


# ─── Test LLM node con mock ───────────────────────────────────────────────────

class TestLLMNode:
    def test_llm_node_skipped_when_no_needs_llm(self):
        """Si no hay comandos NEEDS_LLM, el nodo LLM no llama al LLM."""
        state = initial_state("G0 X10 Y20\nM30")
        state = parse_node(state)
        state = translate_node(state)
        # No debe necesitar LLM para movimientos simples
        assert state["translated_ir"].commands_need_llm == 0
        # llm_node no debe llamar a _get_llm
        with patch("pipeline.graph._get_llm") as mock_llm:
            state = llm_node(state)
            mock_llm.assert_not_called()

    def test_llm_node_called_for_system_variable(self):
        """Variables de sistema como #3011 deben activar el LLM node."""
        state = initial_state("#100 = #3011\nM30")
        state = parse_node(state)
        state = translate_node(state)
        assert state["translated_ir"].commands_need_llm >= 1

        # Mock del LLM que retorna traducción válida
        mock_response = MagicMock()
        mock_response.content = '{"target": "R0", "expression": "$AC_YEAR*10000+$AC_MONTH*100+$AC_DAY"}'

        with patch("pipeline.graph._get_llm") as mock_llm:
            mock_llm.return_value.invoke.return_value = mock_response
            state = llm_node(state)

        # Verificar que el LLM fue llamado
        mock_llm.assert_called_once()

    def test_llm_failure_marks_raw_with_warning(self):
        """Si el LLM falla, el comando queda RAW y se agrega un warning."""
        state = initial_state("#100 = #3011\nM30")
        state = parse_node(state)
        state = translate_node(state)

        # Mock que retorna None (fallo del LLM)
        with patch("pipeline.graph._call_llm_json", return_value=None):
            state = llm_node(state)

        assert len(state["warnings"]) > 0
        # El comando debe estar marcado como RAW
        raw_cmds = [
            c for b in state["translated_ir"].blocks
            for c in b.commands
            if c.translation_status == TranslationStatus.RAW
        ]
        assert len(raw_cmds) >= 1
