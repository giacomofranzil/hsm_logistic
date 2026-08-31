"""Motore cinematico a segmenti analitici.

Ogni tratto di moto e' uniformemente accelerato:

    x(t) = x0 + v0 * (t - t0) + 0.5 * a * (t - t0)**2

Le traiettorie sono quindi esatte e rappresentate da poche decine di segmenti
invece che da centinaia di migliaia di campioni. La differenza fra due
traiettorie e' una funzione quadratica a tratti, per cui gli istanti in cui il
gap fra due pezzi tocca una soglia si trovano risolvendo equazioni di secondo
grado, senza campionamento e senza errore di integrazione.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EPS_T = 1e-9
EPS_X = 1e-9


@dataclass(frozen=True)
class Segment:
    """Tratto di moto uniformemente accelerato valido su [t0, t1]."""

    t0: float
    t1: float
    x0: float
    v0: float
    a: float = 0.0

    def x_at(self, t: float) -> float:
        dt = t - self.t0
        return self.x0 + self.v0 * dt + 0.5 * self.a * dt * dt

    def v_at(self, t: float) -> float:
        return self.v0 + self.a * (t - self.t0)

    @property
    def x1(self) -> float:
        return self.x_at(self.t1)

    @property
    def v1(self) -> float:
        return self.v_at(self.t1)

    @property
    def duration(self) -> float:
        return self.t1 - self.t0


def solve_crossing(
    seg_t0: float,
    x0: float,
    v0: float,
    a: float,
    target: float,
    t_from: float,
    t_to: float,
    direction: int = 0,
) -> float | None:
    """Primo istante in [t_from, t_to] in cui x(t) raggiunge ``target``.

    ``direction`` filtra il verso di attraversamento: +1 accetta solo passaggi
    con velocita' positiva, -1 solo con velocita' negativa, 0 accetta entrambi.
    Restituisce ``None`` se l'attraversamento non avviene nella finestra.
    """
    # x(tau) - target = 0 con tau = t - seg_t0
    c = x0 - target
    b = v0
    a2 = 0.5 * a

    roots: list[float] = []
    if abs(a2) < 1e-15:
        if abs(b) > 1e-15:
            roots.append(-c / b)
        elif abs(c) < EPS_X:
            roots.append(0.0)
    else:
        disc = b * b - 4.0 * a2 * c
        if disc >= 0.0:
            sq = math.sqrt(disc)
            roots.append((-b - sq) / (2.0 * a2))
            roots.append((-b + sq) / (2.0 * a2))

    best: float | None = None
    for tau in sorted(roots):
        t = seg_t0 + tau
        if t < t_from - EPS_T or t > t_to + EPS_T:
            continue
        t = min(max(t, t_from), t_to)
        if direction != 0:
            v = v0 + a * (t - seg_t0)
            if direction > 0 and v < -EPS_X:
                continue
            if direction < 0 and v > EPS_X:
                continue
        if best is None or t < best:
            best = t
    return best


class Trajectory:
    """Sequenza contigua di segmenti.

    La posizione e' continua fra segmenti consecutivi; la velocita' puo' essere
    discontinua, cosa fisicamente corretta ai bite e ai tail-out.
    """

    __slots__ = ("segments",)

    def __init__(self, segments: list[Segment] | None = None) -> None:
        self.segments: list[Segment] = list(segments or [])

    def __len__(self) -> int:
        return len(self.segments)

    def __bool__(self) -> bool:
        return bool(self.segments)

    def append(self, seg: Segment) -> None:
        if seg.t1 < seg.t0 - EPS_T:
            raise ValueError("segmento con durata negativa")
        if seg.duration <= EPS_T and self.segments:
            return
        self.segments.append(seg)

    @property
    def t_start(self) -> float:
        return self.segments[0].t0

    @property
    def t_end(self) -> float:
        return self.segments[-1].t1

    def _find(self, t: float) -> Segment:
        segs = self.segments
        if t <= segs[0].t0:
            return segs[0]
        if t >= segs[-1].t1:
            return segs[-1]
        lo, hi = 0, len(segs) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if t < segs[mid].t1:
                hi = mid
            else:
                lo = mid + 1
        return segs[lo]

    def x_at(self, t: float) -> float:
        seg = self._find(t)
        t = min(max(t, seg.t0), seg.t1)
        return seg.x_at(t)

    def v_at(self, t: float) -> float:
        seg = self._find(t)
        t = min(max(t, seg.t0), seg.t1)
        return seg.v_at(t)

    def shift(self, dt: float) -> "Trajectory":
        return Trajectory(
            [Segment(s.t0 + dt, s.t1 + dt, s.x0, s.v0, s.a) for s in self.segments]
        )

    def clamp_max(self, x_max: float) -> "Trajectory":
        """Blocca la traiettoria a ``x_max`` (presa della testa all'avvolgitore)."""
        out: list[Segment] = []
        clamped = False
        for s in self.segments:
            if clamped:
                out.append(Segment(s.t0, s.t1, x_max, 0.0, 0.0))
                continue
            if s.x0 >= x_max - EPS_X:
                clamped = True
                out.append(Segment(s.t0, s.t1, x_max, 0.0, 0.0))
                continue
            t_hit = solve_crossing(s.t0, s.x0, s.v0, s.a, x_max, s.t0, s.t1, direction=1)
            if t_hit is None:
                out.append(s)
                continue
            if t_hit > s.t0 + EPS_T:
                out.append(Segment(s.t0, t_hit, s.x0, s.v0, s.a))
            if t_hit < s.t1 - EPS_T:
                out.append(Segment(t_hit, s.t1, x_max, 0.0, 0.0))
            clamped = True
        return Trajectory(out)

    def truncate(self, t_end: float) -> "Trajectory":
        out: list[Segment] = []
        for s in self.segments:
            if s.t0 >= t_end - EPS_T:
                break
            if s.t1 <= t_end:
                out.append(s)
            else:
                out.append(Segment(s.t0, t_end, s.x0, s.v0, s.a))
                break
        return Trajectory(out)

    def polyline(self, curve_points: int = 8) -> tuple[list[float], list[float]]:
        """Vertici per il disegno: i tratti a velocita' costante sono esatti con
        due punti, quelli accelerati vengono suddivisi per rendere la parabola."""
        ts: list[float] = []
        xs: list[float] = []
        for s in self.segments:
            n = 1 if abs(s.a) < 1e-12 or s.duration <= EPS_T else curve_points
            for i in range(n + 1):
                t = s.t0 + s.duration * i / n
                if ts and abs(t - ts[-1]) < EPS_T:
                    continue
                ts.append(t)
                xs.append(s.x_at(t))
        return ts, xs

    def crossing_times(self, target: float, direction: int = 0) -> list[float]:
        """Istanti in cui la traiettoria attraversa ``target``."""
        hits: list[float] = []
        for s in self.segments:
            t = solve_crossing(s.t0, s.x0, s.v0, s.a, target, s.t0, s.t1, direction)
            if t is not None and (not hits or abs(t - hits[-1]) > 1e-6):
                hits.append(t)
        return hits


@dataclass(frozen=True)
class QuadPiece:
    """f(t) = c0 + c1*(t-t0) + c2*(t-t0)**2 valida su [t0, t1]."""

    t0: float
    t1: float
    c0: float
    c1: float
    c2: float

    def value_at(self, t: float) -> float:
        dt = t - self.t0
        return self.c0 + self.c1 * dt + self.c2 * dt * dt

    def minimum(self) -> tuple[float, float]:
        """(istante, valore) del minimo sul tratto, vertice incluso."""
        best_t = self.t0
        best_v = self.value_at(self.t0)
        v_end = self.value_at(self.t1)
        if v_end < best_v:
            best_t, best_v = self.t1, v_end
        if self.c2 > 1e-15:
            t_vertex = self.t0 - self.c1 / (2.0 * self.c2)
            if self.t0 < t_vertex < self.t1:
                v_vertex = self.value_at(t_vertex)
                if v_vertex < best_v:
                    best_t, best_v = t_vertex, v_vertex
        return best_t, best_v

    def crossings(self, level: float) -> list[float]:
        return _quad_roots(self.c0 - level, self.c1, self.c2, self.t0, self.t1)


def _quad_roots(c0: float, c1: float, c2: float, t0: float, t1: float) -> list[float]:
    out: list[float] = []
    if abs(c2) < 1e-15:
        if abs(c1) > 1e-15:
            out.append(t0 - c0 / c1)
    else:
        disc = c1 * c1 - 4.0 * c2 * c0
        if disc >= 0.0:
            sq = math.sqrt(disc)
            out.append(t0 + (-c1 - sq) / (2.0 * c2))
            out.append(t0 + (-c1 + sq) / (2.0 * c2))
    return sorted(t for t in out if t0 - EPS_T <= t <= t1 + EPS_T)


class PiecewiseQuad:
    """Funzione quadratica a tratti, tipicamente il gap fra due pezzi."""

    __slots__ = ("pieces",)

    def __init__(self, pieces: list[QuadPiece]) -> None:
        self.pieces = pieces

    def __bool__(self) -> bool:
        return bool(self.pieces)

    @property
    def t_start(self) -> float:
        return self.pieces[0].t0

    @property
    def t_end(self) -> float:
        return self.pieces[-1].t1

    def value_at(self, t: float) -> float:
        for p in self.pieces:
            if p.t0 - EPS_T <= t <= p.t1 + EPS_T:
                return p.value_at(t)
        if t < self.pieces[0].t0:
            return self.pieces[0].value_at(self.pieces[0].t0)
        return self.pieces[-1].value_at(self.pieces[-1].t1)

    def minimum(self) -> tuple[float, float]:
        best_t, best_v = self.pieces[0].minimum()
        for p in self.pieces[1:]:
            t, v = p.minimum()
            if v < best_v:
                best_t, best_v = t, v
        return best_t, best_v

    def first_crossing_below(self, level: float) -> float | None:
        """Primo istante in cui la funzione scende sotto ``level``."""
        for p in self.pieces:
            if p.value_at(p.t0) < level:
                return p.t0
            for t in p.crossings(level):
                if t > p.t0 + EPS_T:
                    return t
        return None

    def polyline(self, curve_points: int = 8) -> tuple[list[float], list[float]]:
        ts: list[float] = []
        vs: list[float] = []
        for p in self.pieces:
            n = 1 if abs(p.c2) < 1e-12 else curve_points
            span = p.t1 - p.t0
            for i in range(n + 1):
                t = p.t0 + span * i / n
                if ts and abs(t - ts[-1]) < EPS_T:
                    continue
                ts.append(t)
                vs.append(p.value_at(t))
        return ts, vs


def subtract(a: Trajectory, b: Trajectory, t_lo: float, t_hi: float) -> PiecewiseQuad:
    """a(t) - b(t) come funzione quadratica a tratti su [t_lo, t_hi].

    La finestra viene comunque ristretta all'intervallo in cui entrambe le
    traiettorie sono definite: fuori da li' i pezzi non coesistono in linea.
    """
    t_lo = max(t_lo, a.t_start, b.t_start)
    t_hi = min(t_hi, a.t_end, b.t_end)
    if t_hi <= t_lo + EPS_T:
        return PiecewiseQuad([])

    bounds = {t_lo, t_hi}
    for traj in (a, b):
        for s in traj.segments:
            for t in (s.t0, s.t1):
                if t_lo < t < t_hi:
                    bounds.add(t)
    knots = sorted(bounds)

    pieces: list[QuadPiece] = []
    for lo, hi in zip(knots[:-1], knots[1:]):
        if hi - lo <= EPS_T:
            continue
        mid = 0.5 * (lo + hi)
        sa = a._find(mid)
        sb = b._find(mid)
        c0 = sa.x_at(lo) - sb.x_at(lo)
        c1 = sa.v_at(lo) - sb.v_at(lo)
        c2 = 0.5 * (sa.a - sb.a)
        pieces.append(QuadPiece(lo, hi, c0, c1, c2))
    return PiecewiseQuad(pieces)
