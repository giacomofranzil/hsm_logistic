"""Verifiche del motore cinematico su casi con soluzione analitica nota."""

from __future__ import annotations

import math

from hsmpace.core.kinematics import (
    QuadPiece,
    Segment,
    Trajectory,
    solve_crossing,
    subtract,
)


def test_segmento_uniformemente_accelerato():
    seg = Segment(t0=2.0, t1=6.0, x0=10.0, v0=3.0, a=2.0)
    # x(6) = 10 + 3*4 + 0.5*2*16 = 38
    assert seg.x_at(6.0) == 38.0
    assert seg.v_at(6.0) == 11.0
    assert seg.x1 == 38.0


def test_crossing_prende_la_prima_radice_utile():
    # x(t) = 0 + 10 t - 0.5 * 2 * t^2, tocca 25 salendo a t=5 (vertice)
    t = solve_crossing(0.0, 0.0, 10.0, -2.0, 21.0, 0.0, 20.0)
    assert t is not None and math.isclose(t, 3.0, abs_tol=1e-9)


def test_crossing_filtra_il_verso():
    # parabola che sale e ridiscende: il passaggio per x=16 avviene due volte
    salita = solve_crossing(0.0, 0.0, 10.0, -2.0, 16.0, 0.0, 20.0, direction=1)
    discesa = solve_crossing(0.0, 0.0, 10.0, -2.0, 16.0, 0.0, 20.0, direction=-1)
    assert math.isclose(salita, 2.0, abs_tol=1e-9)
    assert math.isclose(discesa, 8.0, abs_tol=1e-9)


def test_traiettoria_continua_e_valutabile():
    traj = Trajectory(
        [
            Segment(0.0, 4.0, 0.0, 0.0, 1.0),
            Segment(4.0, 10.0, 8.0, 4.0, 0.0),
        ]
    )
    assert traj.x_at(4.0) == 8.0
    assert traj.x_at(10.0) == 32.0
    assert traj.v_at(2.0) == 2.0


def test_clamp_al_coiler_blocca_la_testa():
    traj = Trajectory([Segment(0.0, 10.0, 0.0, 5.0, 0.0)])
    clamped = traj.clamp_max(20.0)
    assert math.isclose(clamped.x_at(4.0), 20.0)
    assert math.isclose(clamped.x_at(10.0), 20.0)
    assert math.isclose(clamped.x_at(3.0), 15.0)


def test_differenza_di_traiettorie_e_quadratica_a_tratti():
    a = Trajectory([Segment(0.0, 10.0, 100.0, 2.0, 0.0)])
    b = Trajectory([Segment(0.0, 10.0, 0.0, 0.0, 2.0)])
    gap = subtract(a, b, 0.0, 10.0)
    # gap(t) = 100 + 2t - t^2, minimo agli estremi: a t=10 vale 20
    t_min, value = gap.minimum()
    assert math.isclose(t_min, 10.0, abs_tol=1e-9)
    assert math.isclose(value, 20.0, abs_tol=1e-9)
    assert math.isclose(gap.value_at(0.0), 100.0)


def test_prima_discesa_sotto_soglia_e_esatta():
    # gap(t) = 50 - 5t, scende sotto 20 esattamente a t = 6
    a = Trajectory([Segment(0.0, 20.0, 50.0, 0.0, 0.0)])
    b = Trajectory([Segment(0.0, 20.0, 0.0, 5.0, 0.0)])
    gap = subtract(a, b, 0.0, 20.0)
    t = gap.first_crossing_below(20.0)
    assert t is not None and math.isclose(t, 6.0, abs_tol=1e-9)


def test_minimo_nel_vertice_della_parabola():
    piece = QuadPiece(t0=0.0, t1=10.0, c0=10.0, c1=-4.0, c2=0.5)
    t, value = piece.minimum()
    assert math.isclose(t, 4.0, abs_tol=1e-9)
    assert math.isclose(value, 2.0, abs_tol=1e-9)


def test_polyline_non_suddivide_i_tratti_rettilinei():
    traj = Trajectory([Segment(0.0, 100.0, 0.0, 1.0, 0.0)])
    ts, xs = traj.polyline()
    assert len(ts) == 2
    assert xs == [0.0, 100.0]


def test_shift_trasla_solo_il_tempo():
    traj = Trajectory([Segment(0.0, 5.0, 3.0, 2.0, 0.0)])
    moved = traj.shift(100.0)
    assert moved.t_start == 100.0
    assert moved.x_at(102.0) == traj.x_at(2.0)
