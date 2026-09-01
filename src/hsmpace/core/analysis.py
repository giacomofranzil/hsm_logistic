"""Gap analysis between pieces, in open-loop mode.

The pieces follow their nominal profiles with no interlocks: the tool reports
where and when the gap drops below the threshold, it does not simulate the wait
that the plant logic would impose.
"""

from __future__ import annotations

from dataclasses import dataclass

from .kinematics import PiecewiseQuad, subtract
from .model import Line
from .simulate import PieceResult


@dataclass(frozen=True)
class GapPoint:
    t: float
    gap: float
    x: float
    section: str = ""
    equipment: str = ""


@dataclass(frozen=True)
class GapAnalysis:
    front_id: str
    rear_id: str
    series: PiecewiseQuad
    critical: GapPoint | None
    t_first_violation: float | None
    headway: float | None
    gap_min: float

    @property
    def interacts(self) -> bool:
        return bool(self.series)

    @property
    def min_gap(self) -> float:
        return self.critical.gap if self.critical else float("inf")

    @property
    def ok(self) -> bool:
        return self.min_gap >= self.gap_min


def gap_series(front: PieceResult, rear: PieceResult) -> PiecewiseQuad:
    """Distance between the tail of the leading piece and the head of the next one.

    The rear extremity of a piece is ``min(head, tail)`` and the front one
    ``max(head, tail)``. Since the material head always remains the extremity
    furthest downstream, including during reverse passes, those two expressions
    reduce respectively to the tail of the piece in front and the head of the
    one behind. The invariant is verified by ``check_extremities``.
    """
    t_lo = max(front.t_start, rear.t_start)
    t_hi = min(front.t_end, rear.t_end)
    return subtract(front.tail, rear.head, t_lo, t_hi)


def check_extremities(result: PieceResult) -> list[str]:
    """Check that the head stays downstream of the tail throughout the run."""
    problems: list[str] = []
    knots = {s.t0 for s in result.head.segments} | {s.t1 for s in result.head.segments}
    for t in sorted(knots):
        if result.head.x_at(t) < result.tail.x_at(t) - 1e-6:
            problems.append(
                f"{result.piece_id}: at t={t:.2f} s the head is behind the tail "
                "(model error, not a physical condition)"
            )
            break
    return problems


def headway_at(front: PieceResult, rear: PieceResult, t_star: float) -> float | None:
    """Time distance at the critical point.

    Time between the tail of the piece in front passing a position and the head
    of the one behind reaching it: this is the "gap in seconds" people reason
    with on the shop floor.
    """
    x_star = rear.head.x_at(t_star)
    crossings = [t for t in front.tail.crossing_times(x_star) if t <= t_star + 1e-9]
    if not crossings:
        return None
    return t_star - crossings[-1]


def analyse_pair(
    front: PieceResult,
    rear: PieceResult,
    gap_min: float,
    line: Line | None = None,
) -> GapAnalysis:
    series = gap_series(front, rear)
    if not series:
        return GapAnalysis(front.piece_id, rear.piece_id, series, None, None, None, gap_min)

    t_star, g_min = series.minimum()
    x_star = rear.head.x_at(t_star)
    section = ""
    equipment = ""
    if line is not None:
        sec = line.section_at(x_star)
        section = sec.display if sec else ""
        nearest = min(line.equipment, key=lambda e: abs(e.x - x_star))
        if abs(nearest.x - x_star) <= 15.0:
            equipment = nearest.display

    critical = GapPoint(t_star, g_min, x_star, section, equipment)
    t_violation = series.first_crossing_below(gap_min)
    return GapAnalysis(
        front_id=front.piece_id,
        rear_id=rear.piece_id,
        series=series,
        critical=critical,
        t_first_violation=t_violation,
        headway=headway_at(front, rear, t_star),
        gap_min=gap_min,
    )


def analyse_sequence(
    results: list[PieceResult],
    gap_min: float,
    line: Line | None = None,
) -> list[GapAnalysis]:
    """Analyse every pair of pieces that coexist on the line.

    With a reversing roughing mill the binding constraint often falls between
    piece N and N+2, so non adjacent pairs are evaluated as well.
    """
    out: list[GapAnalysis] = []
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            analysis = analyse_pair(results[i], results[j], gap_min, line)
            if analysis.interacts:
                out.append(analysis)
    return out


def sequence_min_gap(analyses: list[GapAnalysis]) -> float:
    if not analyses:
        return float("inf")
    return min(a.min_gap for a in analyses)


@dataclass(frozen=True)
class MassBalanceCheck:
    piece_id: str
    length_kinematic: float
    length_geometric: float

    @property
    def error_pct(self) -> float:
        if self.length_geometric == 0.0:
            return 0.0
        return 100.0 * (self.length_kinematic - self.length_geometric) / self.length_geometric

    @property
    def ok(self) -> bool:
        return abs(self.error_pct) < 0.1


def mass_balance(results: list[PieceResult]) -> list[MassBalanceCheck]:
    """Compare the length integrated from the speeds with the geometric length.

    With the mass flow chain model the two coincide by construction: a deviation
    signals an error in the input or in the model.
    """
    seen: set[str] = set()
    out: list[MassBalanceCheck] = []
    for r in results:
        if r.product_id in seen:
            continue
        seen.add(r.product_id)
        out.append(MassBalanceCheck(r.product_id, r.length_kinematic, r.length_geometric))
    return out
