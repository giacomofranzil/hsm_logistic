"""Analisi del gap fra pezzi consecutivi, in modalita' open-loop.

I pezzi seguono i profili nominali senza interblocchi: il tool riporta dove e
quando il gap scende sotto soglia, non simula l'attesa che la logica di
impianto imporrebbe.
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
    """Distanza fra la coda del pezzo che precede e la testa di quello che segue.

    L'estremita' posteriore di un pezzo e' ``min(testa, coda)`` e quella
    anteriore ``max(testa, coda)``. Poiche' la testa materiale resta sempre
    l'estremita' geometricamente piu' a valle, anche durante le passate
    inverse, le due espressioni si riducono rispettivamente alla coda del pezzo
    davanti e alla testa di quello dietro. L'invariante e' verificato da
    ``check_extremities``.
    """
    t_lo = max(front.t_start, rear.t_start)
    t_hi = min(front.t_end, rear.t_end)
    return subtract(front.tail, rear.head, t_lo, t_hi)


def check_extremities(result: PieceResult) -> list[str]:
    """Verifica che la testa resti a valle della coda per tutta la simulazione."""
    problems: list[str] = []
    knots = {s.t0 for s in result.head.segments} | {s.t1 for s in result.head.segments}
    for t in sorted(knots):
        if result.head.x_at(t) < result.tail.x_at(t) - 1e-6:
            problems.append(
                f"{result.piece_id}: a t={t:.2f} s la testa e' dietro la coda "
                "(errore di modello, non condizione fisica)"
            )
            break
    return problems


def headway_at(front: PieceResult, rear: PieceResult, t_star: float) -> float | None:
    """Distanza temporale al punto critico.

    Tempo fra il passaggio della coda del pezzo davanti e l'arrivo della testa
    di quello dietro nella stessa posizione: e' il "gap in secondi" con cui si
    ragiona in reparto.
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
    """Analizza tutte le coppie adiacenti della sequenza.

    Con lo sbozzatore reversibile il vincolo puo' cadere fra il pezzo N e
    N+2, quindi vengono valutate anche le coppie non adiacenti che si
    sovrappongono nel tempo.
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
    """Confronto fra lunghezza integrata dalle velocita' e lunghezza geometrica.

    Con il modello a catena di bilancio di massa le due coincidono per
    costruzione: uno scostamento segnala un errore nell'input o nel modello.
    """
    seen: set[str] = set()
    out: list[MassBalanceCheck] = []
    for r in results:
        if r.product_id in seen:
            continue
        seen.add(r.product_id)
        out.append(MassBalanceCheck(r.product_id, r.length_kinematic, r.length_geometric))
    return out
