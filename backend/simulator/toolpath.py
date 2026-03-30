"""
Simulador geométrico de toolpath.
Convierte IR (Program) en secuencia de puntos 3D.
Solo geometría pura — sin dinámica de máquina.
"""
from __future__ import annotations
import math
from typing import List, Tuple, Optional
from models.ir import Program, Block, Command, CommandType, ModalState

# Punto 3D como tupla para eficiencia
Point3D = Tuple[float, float, float]


# ─── Interpolación de arcos ───────────────────────────────────────────────────

def _interpolate_arc(
    start: Point3D,
    end: Point3D,
    center_offset: Tuple[Optional[float], Optional[float], Optional[float]],
    radius: Optional[float],
    clockwise: bool,
    plane: str,
    n_points: int = 36,
) -> List[Point3D]:
    """
    Interpola un arco entre start y end.
    Regla de desambiguación R:
      - R positivo → arco corto (≤ 180°)
      - R negativo → arco largo (> 180°)
    Retorna lista de puntos incluyendo el punto final.
    """
    sx, sy, sz = start
    ex, ey, ez = end

    # Determinar ejes del plano
    if plane == "G17":   # XY
        a1, a2, a_fix = 0, 1, 2
    elif plane == "G18": # ZX
        a1, a2, a_fix = 2, 0, 1
    else:                # G19 YZ
        a1, a2, a_fix = 1, 2, 0

    s2d = (start[a1], start[a2])
    e2d = (end[a1],   end[a2])

    # Centro del arco
    if radius is not None:
        cx, cy = _center_from_radius(s2d, e2d, abs(radius), radius < 0)
    else:
        i = center_offset[0] or 0.0
        j = center_offset[1] or 0.0
        k = center_offset[2] or 0.0
        offsets = (i, j, k)
        cx = s2d[0] + offsets[a1]
        cy = s2d[1] + offsets[a2]

    # Ángulos de inicio y fin
    angle_start = math.atan2(s2d[1] - cy, s2d[0] - cx)
    angle_end   = math.atan2(e2d[1] - cy, e2d[0] - cx)
    r_calc      = math.hypot(s2d[0] - cx, s2d[1] - cy)

    # Sentido y ángulo total
    if clockwise:
        if angle_end >= angle_start:
            angle_end -= 2 * math.pi
        sweep = angle_end - angle_start   # negativo
    else:
        if angle_end <= angle_start:
            angle_end += 2 * math.pi
        sweep = angle_end - angle_start   # positivo

    # Número de puntos proporcional al arco
    arc_fraction = abs(sweep) / (2 * math.pi)
    n = max(4, int(n_points * arc_fraction))

    # Interpolación lineal en Z para el eje fijo
    fix_start = start[a_fix]
    fix_end   = end[a_fix]

    points: List[Point3D] = []
    for i in range(1, n + 1):
        t = i / n
        angle = angle_start + sweep * t
        p2d_0 = cx + r_calc * math.cos(angle)
        p2d_1 = cy + r_calc * math.sin(angle)
        p_fix = fix_start + (fix_end - fix_start) * t

        p = [0.0, 0.0, 0.0]
        p[a1]    = p2d_0
        p[a2]    = p2d_1
        p[a_fix] = p_fix
        points.append((p[0], p[1], p[2]))

    return points


def _center_from_radius(
    start: Tuple[float, float],
    end: Tuple[float, float],
    r: float,
    large_arc: bool,
) -> Tuple[float, float]:
    """Calcula centro del arco dado radio. large_arc=True → arco > 180°."""
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    d = math.hypot(dx, dy)

    if d > 2 * r:  # radio demasiado pequeño — usar el mínimo posible
        r = d / 2.0

    h = math.sqrt(max(0.0, r * r - (d / 2) ** 2))
    mx, my = (sx + ex) / 2, (sy + ey) / 2

    # Dos posibles centros
    px, py = -dy / d * h, dx / d * h
    c1 = (mx + px, my + py)
    c2 = (mx - px, my - py)

    # Elegir según large_arc (R negativo)
    # Para arco corto: el centro que genera ángulo menor
    def arc_angle(cx, cy):
        a1 = math.atan2(sy - cy, sx - cx)
        a2 = math.atan2(ey - cy, ex - cx)
        da = a2 - a1
        # normalizar a [0, 2π]
        return da % (2 * math.pi)

    angle1 = arc_angle(*c1)
    # c1 produce arco CCW de angle1. Si es largo → angle1 > π
    if large_arc:
        return c1 if angle1 > math.pi else c2
    else:
        return c1 if angle1 <= math.pi else c2


# ─── Drill cycle points ───────────────────────────────────────────────────────

def _drill_cycle_points(
    pos_xy: Point3D,
    z_depth: float,
    z_retract: float,
    z_r_plane: float,
    peck: Optional[float],
    retract_mode: str,  # "G98" | "G99"
) -> List[Point3D]:
    """
    Genera los puntos de un ciclo de taladrado.
    G98: retract a z_retract (posición inicial Z)
    G99: retract a z_r_plane (plano R)
    """
    x, y, _ = pos_xy
    points: List[Point3D] = []

    # Posicionamiento rápido al plano R
    points.append((x, y, z_r_plane))

    if peck and peck > 0:
        # Peck drilling: baja en incrementos
        current_z = z_r_plane
        while current_z > z_depth:
            next_z = max(z_depth, current_z - peck)
            points.append((x, y, next_z))
            points.append((x, y, z_r_plane))  # retract al plano R entre pecks
            current_z = next_z
    else:
        # Taladrado simple
        points.append((x, y, z_depth))

    # Retract final
    if retract_mode == "G98":
        points.append((x, y, z_retract))
    else:
        points.append((x, y, z_r_plane))

    return points


# ─── Simulador principal ──────────────────────────────────────────────────────

class MachineState:
    """Estado de la máquina durante la simulación."""

    def __init__(self):
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0
        self.positioning: str = "G90"   # G90=abs, G91=inc
        self.plane: str = "G17"
        self.retract: str = "G98"
        self.initial_z: float = 0.0     # para G98 retract

    def pos(self) -> Point3D:
        return (self.x, self.y, self.z)

    def move_to(self, tx: Optional[float], ty: Optional[float], tz: Optional[float]):
        """Actualiza posición absoluta o incremental."""
        if self.positioning == "G90":
            if tx is not None: self.x = tx
            if ty is not None: self.y = ty
            if tz is not None: self.z = tz
        else:  # G91 incremental
            if tx is not None: self.x += tx
            if ty is not None: self.y += ty
            if tz is not None: self.z += tz

    def apply_modal(self, codes: List[str]):
        for code in (codes or []):
            c = code.upper()
            if c == "G90": self.positioning = "G90"
            elif c == "G91": self.positioning = "G91"
            elif c == "G17": self.plane = "G17"
            elif c == "G18": self.plane = "G18"
            elif c == "G19": self.plane = "G19"
            elif c == "G98": self.retract = "G98"
            elif c == "G99": self.retract = "G99"


def simulate_toolpath(program: Program, arc_points: int = 36) -> List[Point3D]:
    """
    Genera la secuencia de puntos 3D que describe el toolpath del programa.

    Args:
        program: IR del programa (Fanuc o Siemens traducido)
        arc_points: puntos por arco completo (36 = cada 10°)

    Returns:
        Lista ordenada de puntos (x, y, z) en mm.
    """
    state = MachineState()
    toolpath: List[Point3D] = [(0.0, 0.0, 0.0)]  # punto inicial

    for block in program.blocks:
        # Sincronizar estado modal del bloque
        ms = block.modal_state
        state.positioning = ms.positioning
        state.plane       = ms.plane
        state.retract     = ms.retract

        for cmd in block.commands:
            _process_command(cmd, state, toolpath, arc_points)

    return toolpath


def _process_command(
    cmd: Command,
    state: MachineState,
    toolpath: List[Point3D],
    arc_points: int,
):
    t = cmd.type

    if t == CommandType.MODAL_CHANGE:
        state.apply_modal(cmd.modal_codes or [])
        return

    if t in (CommandType.RAPID_MOVE, CommandType.LINEAR_MOVE):
        if cmd.target is None:
            return
        prev = state.pos()
        state.move_to(cmd.target.x, cmd.target.y, cmd.target.z)
        curr = state.pos()
        if curr != prev:
            toolpath.append(curr)
        return

    if t in (CommandType.ARC_CW, CommandType.ARC_CCW):
        if cmd.target is None:
            return
        start = state.pos()
        state.move_to(cmd.target.x, cmd.target.y, cmd.target.z)
        end = state.pos()

        arc_offset = (None, None, None)
        radius = None
        if cmd.arc:
            radius = cmd.arc.r
            if radius is None:
                arc_offset = (cmd.arc.i, cmd.arc.j, cmd.arc.k)

        pts = _interpolate_arc(
            start=start,
            end=end,
            center_offset=arc_offset,
            radius=radius,
            clockwise=(t == CommandType.ARC_CW),
            plane=state.plane,
            n_points=arc_points,
        )
        toolpath.extend(pts)
        return

    if t == CommandType.DRILL_CYCLE:
        if cmd.drill is None and cmd.siemens_params is None:
            return

        # Posición XY del agujero
        if cmd.target:
            state.move_to(cmd.target.x, cmd.target.y, None)

        pos_xy = state.pos()

        # Parámetros del ciclo
        if cmd.drill:
            # IR Fanuc
            z_depth   = cmd.drill.z if cmd.drill.z is not None else -10.0
            z_r_plane = cmd.drill.r if cmd.drill.r is not None else 2.0
            peck      = cmd.drill.q
        elif cmd.siemens_params:
            # IR Siemens traducido
            z_depth   = cmd.siemens_params.get("DP", -10.0)
            z_r_plane = cmd.siemens_params.get("RTP", 2.0)
            peck      = cmd.siemens_params.get("FDEP")
        else:
            return

        z_retract = state.z if state.z > z_r_plane else z_r_plane

        pts = _drill_cycle_points(
            pos_xy=pos_xy,
            z_depth=z_depth,
            z_retract=z_retract,
            z_r_plane=z_r_plane,
            peck=peck,
            retract_mode=state.retract,
        )
        toolpath.extend(pts)
        # Actualizar Z al valor de retract tras el ciclo
        if state.retract == "G98":
            state.z = z_retract
        else:
            state.z = z_r_plane
        return

    if t == CommandType.HOME:
        state.x, state.y, state.z = 0.0, 0.0, 0.0
        toolpath.append((0.0, 0.0, 0.0))
        return
