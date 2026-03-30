"""
Tests del simulador de toolpath y comparador.
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from gcode_parser.fanuc_parser import parse_fanuc
from translator.deterministic import translate_ir, load_equivalences
from simulator.toolpath import simulate_toolpath
from simulator.comparator import compare_toolpaths, is_within_tolerance


# ─── Helpers ─────────────────────────────────────────────────────────────────

def toolpath(nc: str):
    prog = parse_fanuc(nc)
    return simulate_toolpath(prog)


def toolpath_translated(nc: str):
    prog = parse_fanuc(nc)
    eq = load_equivalences()
    t = translate_ir(prog, eq)
    return simulate_toolpath(t)


# ─── Movimientos lineales ────────────────────────────────────────────────────

class TestLinearMoves:
    def test_g0_moves_to_point(self):
        pts = toolpath("G0 X10 Y20 Z-5")
        assert (10.0, 20.0, -5.0) in pts

    def test_g1_sequence(self):
        pts = toolpath("G0 X0 Y0 Z0\nG1 X50 Y0 F100\nG1 X50 Y50")
        assert (50.0, 0.0, 0.0) in pts
        assert (50.0, 50.0, 0.0) in pts

    def test_negative_z(self):
        pts = toolpath("G1 Z-25 F80")
        assert any(p[2] == -25.0 for p in pts)

    def test_g91_incremental(self):
        pts = toolpath("G0 X10 Y10 Z0\nG91\nG1 X5 Y5")
        # Con G91, X5 Y5 desde (10,10) → (15,15)
        assert (15.0, 15.0, 0.0) in pts

    def test_g90_after_g91(self):
        pts = toolpath("G91\nG1 X5\nG90\nG1 X20")
        assert (20.0, 0.0, 0.0) in pts


# ─── Arcos ───────────────────────────────────────────────────────────────────

class TestArcs:
    def test_g2_endpoint_reached(self):
        """El arco debe terminar en el punto programado."""
        pts = toolpath("G0 X10 Y0 Z0\nG2 X0 Y10 I-10 J0")
        last = pts[-1]
        assert abs(last[0] - 0.0) < 0.01
        assert abs(last[1] - 10.0) < 0.01

    def test_g3_endpoint_reached(self):
        pts = toolpath("G0 X0 Y10 Z0\nG3 X10 Y0 I0 J-10")
        last = pts[-1]
        assert abs(last[0] - 10.0) < 0.01
        assert abs(last[1] - 0.0) < 0.01

    def test_g2_generates_multiple_points(self):
        """Un arco debe generar más de 2 puntos."""
        pts = toolpath("G0 X10 Y0\nG2 X-10 Y0 I-10 J0")
        assert len(pts) > 5

    def test_arc_points_on_circle(self):
        """Todos los puntos del arco deben estar sobre el círculo."""
        # Semicírculo radio 10 centrado en origen, de (10,0) a (-10,0) CW
        pts = toolpath("G0 X10 Y0 Z0\nG2 X-10 Y0 I-10 J0")
        # El centro está en (0,0), radio=10
        for p in pts[1:]:  # skip punto inicial
            r = math.hypot(p[0], p[1])
            assert abs(r - 10.0) < 0.5, f"Punto {p} no está en el círculo (r={r:.3f})"

    def test_arc_with_radius_r(self):
        """Arco definido con R positivo → arco corto."""
        pts = toolpath("G0 X0 Y0\nG2 X10 Y0 R5")
        assert len(pts) > 2
        last = pts[-1]
        assert abs(last[0] - 10.0) < 0.1
        assert abs(last[1] - 0.0) < 0.1


# ─── Ciclos de taladrado ──────────────────────────────────────────────────────

class TestDrillCycles:
    def test_g81_reaches_depth(self):
        pts = toolpath("G0 X10 Y10 Z5\nG81 X10 Y10 Z-10 R2 F150")
        z_values = [p[2] for p in pts]
        assert min(z_values) <= -10.0

    def test_g83_peck_returns_to_r_plane(self):
        """Peck drilling sube al plano R entre pecks."""
        pts = toolpath("G0 X0 Y0 Z5\nG83 X0 Y0 Z-15 R2 Q5 F100")
        z_values = [p[2] for p in pts]
        # Entre el inicio y la profundidad final debe haber retracks al plano R
        assert 2.0 in z_values or any(abs(z - 2.0) < 0.01 for z in z_values)

    def test_g83_reaches_final_depth(self):
        pts = toolpath("G0 X0 Y0 Z5\nG83 X0 Y0 Z-25 R2 Q5 F100")
        z_values = [p[2] for p in pts]
        assert min(z_values) <= -25.0

    def test_drill_positions_xy_correct(self):
        pts = toolpath("G0 X0 Y0 Z5\nG83 X30 Y40 Z-10 R2 Q5 F100")
        xy_at_hole = [(p[0], p[1]) for p in pts if abs(p[2] - 2.0) < 0.1]
        assert any(abs(p[0] - 30.0) < 0.1 and abs(p[1] - 40.0) < 0.1
                   for p in xy_at_hole)

    def test_g98_retracts_to_initial_z(self):
        """G98: retract a la Z inicial (antes del ciclo)."""
        pts = toolpath("G0 X0 Y0 Z5\nG98\nG81 X0 Y0 Z-10 R2 F100")
        z_values = [p[2] for p in pts]
        assert 5.0 in z_values or any(abs(z - 5.0) < 0.1 for z in z_values)

    def test_g99_retracts_to_r_plane(self):
        """G99: retract al plano R."""
        pts = toolpath("G0 X0 Y0 Z10\nG99\nG81 X0 Y0 Z-10 R2 F100")
        z_values = [p[2] for p in pts]
        assert any(abs(z - 2.0) < 0.1 for z in z_values)


# ─── Comparador ──────────────────────────────────────────────────────────────

class TestComparator:
    def test_identical_toolpaths_zero_deviation(self):
        pts = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
        result = compare_toolpaths(pts, pts)
        assert result.max_deviation_mm == pytest.approx(0.0)
        assert result.avg_deviation_mm == pytest.approx(0.0)
        assert result.points_exceeding == 0

    def test_small_offset_detected(self):
        orig = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
        trans = [(0.0, 0.0, 0.0), (10.005, 0.0, 0.0)]  # 0.005mm offset
        result = compare_toolpaths(orig, trans, threshold_mm=0.01)
        assert result.max_deviation_mm == pytest.approx(0.005, abs=0.001)
        assert is_within_tolerance(result)

    def test_large_offset_exceeds_threshold(self):
        orig  = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
        trans = [(0.0, 0.0, 0.0), (10.05, 0.0, 0.0)]  # 0.05mm
        result = compare_toolpaths(orig, trans, threshold_mm=0.01)
        assert not is_within_tolerance(result)
        assert result.points_exceeding > 0

    def test_different_point_counts_handled(self):
        """Mismo path muestreado distinto número de veces → desviación ≈ 0."""
        # Línea de X=0 a X=10, muestreada a 10 y a 20 puntos respectivamente
        orig  = [(10.0 * i / 9,  0.0, 0.0) for i in range(10)]   # 10 pts
        trans = [(10.0 * i / 19, 0.0, 0.0) for i in range(20)]   # 20 pts
        result = compare_toolpaths(orig, trans)
        assert result.max_deviation_mm == pytest.approx(0.0, abs=0.01)

    def test_empty_toolpath_handled(self):
        result = compare_toolpaths([], [])
        assert result.max_deviation_mm == 0.0
        assert result.total_points == 0

    def test_exceeding_indices_correct(self):
        orig  = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)]
        trans = [(0.0, 0.0, 0.0), (10.0, 0.5, 0.0), (20.0, 0.0, 0.0)]
        result = compare_toolpaths(orig, trans, threshold_mm=0.01)
        assert len(result.exceeding_indices) > 0


# ─── Programa Fanuc → traducido = misma geometría ────────────────────────────

class TestEndToEndGeometry:
    def test_linear_moves_same_toolpath(self):
        """Movimientos G0/G1 idénticos Fanuc↔Siemens → desviación 0."""
        nc = "G0 X0 Y0 Z0\nG1 X100 F200\nG1 X100 Y80\nG1 X0 Y80\nG1 X0 Y0"
        orig = toolpath(nc)
        tran = toolpath_translated(nc)
        result = compare_toolpaths(orig, tran, threshold_mm=0.01)
        assert result.max_deviation_mm == pytest.approx(0.0, abs=0.001)

    def test_arc_same_toolpath(self):
        nc = "G0 X10 Y0 Z0\nG2 X0 Y10 I-10 J0 F150"
        orig = toolpath(nc)
        tran = toolpath_translated(nc)
        result = compare_toolpaths(orig, tran, threshold_mm=0.01)
        assert result.max_deviation_mm == pytest.approx(0.0, abs=0.001)

    def test_drill_cycle_same_geometry(self):
        """G83 en Fanuc y su traducción Siemens deben tener la misma geometría."""
        nc = "G83 X10 Y10 Z-25 R2 Q5 F100"
        orig = toolpath(nc)
        tran = toolpath_translated(nc)
        result = compare_toolpaths(orig, tran, threshold_mm=0.5)
        assert result.max_deviation_mm < 0.5, (
            f"Desviación del ciclo G83→CYCLE83: {result.max_deviation_mm:.3f}mm"
        )

    def test_fixture_full_program_deviation(self):
        """El fixture completo traducido debe tener desviación mínima."""
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_fanuc.nc')
        with open(fixture) as f:
            src = f.read()

        orig_prog = parse_fanuc(src)
        orig_tp   = simulate_toolpath(orig_prog)

        eq = load_equivalences()
        tran_prog = translate_ir(orig_prog, eq)
        tran_tp   = simulate_toolpath(tran_prog)

        result = compare_toolpaths(orig_tp, tran_tp, threshold_mm=0.5)
        assert result.max_deviation_mm < 1.0, (
            f"Desviación máxima del fixture: {result.max_deviation_mm:.3f}mm"
        )
