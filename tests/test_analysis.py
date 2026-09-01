"""Checks of the gap analysis and of the pacing studies."""

from __future__ import annotations

from dataclasses import replace

import pytest

from hsmpace.core.analysis import (
    analyse_pair,
    analyse_sequence,
    check_extremities,
    gap_series,
    mass_balance,
)
from hsmpace.core.model import harmonise_tandem_speeds
from hsmpace.core.simulate import shift_result, simulate_piece
from hsmpace.core.studies import (
    base_results,
    gap_vs_pacing,
    min_feasible_pacing,
    monte_carlo,
    sequence,
)
from hsmpace.example import example_case


@pytest.fixture(scope="module")
def case():
    prepared, _ = harmonise_tandem_speeds(example_case())
    return prepared


@pytest.fixture(scope="module")
def base(case):
    return base_results(case)


def test_gap_matches_the_difference_of_the_trajectories(case, base):
    first = base["P1"]
    second = shift_result(first, 120.0, "#2")
    series = gap_series(first, second)

    span = series.t_end - series.t_start
    for frac in (0.05, 0.25, 0.5, 0.75, 0.95):
        t = series.t_start + frac * span
        expected = first.tail.x_at(t) - second.head.x_at(t)
        assert series.value_at(t) == pytest.approx(expected, abs=1e-9)


def test_the_head_always_stays_downstream_of_the_tail(case, base):
    assert check_extremities(base["P1"]) == []


def test_the_first_violation_lands_exactly_on_the_threshold(case, base):
    first = base["P1"]
    second = shift_result(first, 95.0, "#2")
    analysis = analyse_pair(first, second, gap_min=5.0, line=case.line)

    assert analysis.t_first_violation is not None
    assert analysis.series.value_at(analysis.t_first_violation) == pytest.approx(5.0, abs=1e-6)
    assert analysis.min_gap < 5.0
    assert not analysis.ok


def test_the_time_gap_is_consistent_with_the_critical_position(case, base):
    first = base["P1"]
    second = shift_result(first, 110.0, "#2")
    analysis = analyse_pair(first, second, gap_min=5.0, line=case.line)

    critical = analysis.critical
    assert critical is not None
    assert analysis.headway is not None
    when = critical.t - analysis.headway
    assert first.tail.x_at(when) == pytest.approx(critical.x, abs=1e-3)


def test_a_wide_pacing_produces_no_interaction(case, base):
    results = sequence(case, base, 400.0)
    assert analyse_sequence(results, case.settings.gap_min, case.line) == []


def test_non_adjacent_pairs_are_compared_too(case, base):
    """With a reversing roughing mill the constraint can fall between N and N+2."""
    tight = replace(case, settings=replace(case.settings, n_pieces=3))
    results = sequence(tight, base, 60.0)
    pairs = {(a.front_id, a.rear_id) for a in analyse_sequence(results, 5.0, case.line)}
    assert ("#1", "#3") in pairs


def test_the_pacing_curve_and_the_minimum_pacing(case, base):
    curve = gap_vs_pacing(case, base)
    assert len(curve) == case.settings.pacing_scan_steps
    assert not curve[0].feasible, "the tightest pacing of the scan must violate"

    best = min_feasible_pacing(case, base, curve)
    assert best is not None and best.feasible

    slightly_less = sequence(case, base, best.pacing - 1.0)
    analyses = analyse_sequence(slightly_less, case.settings.gap_min, case.line)
    assert min(a.min_gap for a in analyses) < case.settings.gap_min


def test_the_binding_constraint_is_reported(case, base):
    best = min_feasible_pacing(case, base)
    assert best is not None
    assert best.section or best.equipment


def test_monte_carlo_is_reproducible_and_conservative(case, base):
    tight = replace(case, settings=replace(case.settings, pacing=112.0))
    one = monte_carlo(tight, runs=120, seed=7)
    two = monte_carlo(tight, runs=120, seed=7)
    assert one.min_gaps == two.min_gaps
    assert one.errors == 0

    wide = monte_carlo(replace(case, settings=replace(case.settings, pacing=170.0)), runs=120, seed=7)
    assert wide.violation_rate <= one.violation_rate


def test_the_critical_point_sits_upstream_of_the_roughing_mill(case, base):
    """The gap closes where the reversing mill brings the bar back towards the furnace.

    At the minimum pacing of the example case the critical point falls upstream
    of R1, a position the tail of the piece in front can only occupy because of
    the reverse passes: without reversals the bar would never travel back that
    far and the piece behind would find the line clear.
    """
    best = min_feasible_pacing(case, base)
    assert best is not None

    results = sequence(case, base, best.pacing - 2.0)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)
    worst = min(analyses, key=lambda a: a.min_gap)
    assert worst.min_gap < case.settings.gap_min

    x_r1 = case.line.get("R1").x
    assert worst.critical.x < x_r1

    front = next(r for r in results if r.piece_id == worst.front_id)
    assert any(s.v0 < 0 for s in front.tail.segments), "the bar must travel back up the line"
    assert min(s.x1 for s in front.tail.segments) < x_r1


def test_the_physical_head_never_passes_the_coiler(case, base):
    for res in sequence(case, base, case.settings.pacing):
        assert res.x_coiler is not None
        assert max(s.x1 for s in res.head.segments) <= res.x_coiler + 1e-6
        assert res.head_virtual.x_at(res.t_end) > res.x_coiler


def test_mass_balance_on_the_example_case(case, base):
    results = sequence(case, base, case.settings.pacing)
    checks = mass_balance(results)
    assert checks and all(c.ok for c in checks)


def test_different_products_in_the_same_sequence(case):
    thinner = replace(
        case.products[0],
        id="P2",
        passes=tuple(
            replace(p, product_id="P2", v_exit=p.v_exit * 1.1) for p in case.products[0].passes
        ),
    )
    mixed = replace(
        case,
        products=(case.products[0], thinner),
        settings=replace(case.settings, piece_products=("P1", "P2", "P1")),
    )
    mixed, _ = harmonise_tandem_speeds(mixed)
    base_mixed = base_results(mixed)
    assert set(base_mixed) == {"P1", "P2"}

    results = sequence(mixed, base_mixed, 150.0)
    assert [r.product_id for r in results] == ["P1", "P2", "P1"]
    assert results[1].t_end != results[0].t_end + 150.0


def test_direct_simulation_and_time_shift_agree(case):
    direct = simulate_piece(case, case.products[0], t_release=137.0, piece_id="#2")
    shifted = shift_result(simulate_piece(case, case.products[0]), 137.0, "#2")
    assert direct.t_end == pytest.approx(shifted.t_end)
    for t in (150.0, 200.0, 300.0):
        assert direct.head.x_at(t) == pytest.approx(shifted.head.x_at(t), abs=1e-9)
        assert direct.tail.x_at(t) == pytest.approx(shifted.tail.x_at(t), abs=1e-9)
