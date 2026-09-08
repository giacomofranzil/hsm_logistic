"""Checks of the simulator: kinematics, mass balance, reversals, zoom."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from hsmpace.core.model import (
    FWD,
    REV,
    MAX_COILERS,
    Case,
    Equipment,
    Line,
    ModelError,
    Product,
    RollingPass,
    Section,
    SimSettings,
    SpeedEvent,
    harmonise_tandem_speeds,
    validate_case,
)
from hsmpace.core.simulate import simulate_case, simulate_piece
from hsmpace.core.studies import base_results


def _line(stands: list[tuple[str, float]], coiler_x: float = 200.0, v_start: float = 2.0) -> Line:
    equipment = [Equipment("ST", "start", 0.0, accel=1.0)]
    equipment += [Equipment(name, "stand", x, accel=1.0) for name, x in stands]
    equipment.append(Equipment("DC", "coiler", coiler_x, accel=1.0))
    section = Section(
        "S1",
        x_start=0.0,
        length=coiler_x,
        events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=v_start, direction=FWD),),
    )
    return Line(tuple(equipment), (section,))


def _case(line: Line, passes: list[RollingPass], slab_len: float = 10.0) -> Case:
    product = Product(
        id="P", slab_thk=100.0, slab_wid=1000.0, slab_len=slab_len, passes=tuple(passes)
    )
    return Case(line=line, products=(product,), settings=SimSettings(n_pieces=2))


def _pass(no: int, stand: str, direction: int, h_in: float, h_out: float, v_exit: float, **kw):
    return RollingPass(
        product_id="P",
        pass_no=no,
        equipment_id=stand,
        direction=direction,
        h_in=h_in,
        h_out=h_out,
        w_in=1000.0,
        w_out=1000.0,
        v_exit=v_exit,
        **kw,
    )


def test_single_pass_exact_timings():
    """Hand computed case: ramp 0 to 2 m/s, run to the stand, roll, then coil."""
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    bite = next(e for e in res.events if e.kind == "bite")
    tail_out = next(e for e in res.events if e.kind == "tail_out")
    # 2 s of ramp at 1 m/s2 cover 2 m, the remaining 48 m at 2 m/s
    assert math.isclose(bite.t, 26.0, abs_tol=1e-6)
    # lambda = 2, so the tail moves at 2 m/s and takes 5 s to clear the stand
    assert math.isclose(tail_out.t, 31.0, abs_tol=1e-6)
    assert math.isclose(res.head.x_at(31.0), 70.0, abs_tol=1e-6)
    assert math.isclose(res.tail.x_at(31.0), 50.0, abs_tol=1e-6)
    # the tail then runs to the coiler slowing down to the final speed: braking from
    # 4 to 1 m/s at 1 m/s2 takes 7.5 m, so 142.5 m at 4 m/s plus 3 s of deceleration
    assert math.isclose(res.t_end, 69.625, abs_tol=1e-6)
    assert res.tail.v_at(res.t_end) == pytest.approx(1.0, abs=1e-6)


def test_mass_balance_is_exact():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])
    assert math.isclose(res.length_geometric, 20.0, abs_tol=1e-9)
    assert math.isclose(res.length_kinematic, 20.0, abs_tol=1e-6)
    assert abs(res.length_error) < 1e-6
    assert res.warnings == ()


def test_the_tail_is_slower_than_the_head_only_while_rolling():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    # while rolling: head 4 m/s, tail 2 m/s
    assert math.isclose(res.head.v_at(28.0), 4.0, abs_tol=1e-9)
    assert math.isclose(res.tail.v_at(28.0), 2.0, abs_tol=1e-9)
    # after tail-out the piece is rigid
    assert math.isclose(res.head.v_at(40.0), res.tail.v_at(40.0), abs_tol=1e-9)


def test_mass_flow_chain_in_the_tandem():
    line = _line([("F1", 50.0), ("F2", 60.0)], coiler_x=300.0)
    case = _case(
        line,
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    bites = [e for e in res.events if e.kind == "bite"]
    assert len(bites) == 2

    t = 0.5 * (bites[1].t + min(e.t for e in res.events if e.kind == "tail_out"))
    # with two stands engaged the overall lambda is 4
    assert math.isclose(res.head.v_at(t) / res.tail.v_at(t), 4.0, rel_tol=1e-9)
    assert math.isclose(res.length_geometric, 40.0, abs_tol=1e-9)
    assert math.isclose(res.length_kinematic, 40.0, abs_tol=1e-6)


def test_the_reversal_honours_the_reversing_delay():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=7.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=7.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])

    kinds = [e.kind for e in res.events]
    assert kinds.count("bite") == 3
    assert kinds.count("reverse_start") == 2

    wait = next(e for e in res.events if e.kind == "reverse_wait")
    resume = next(e for e in res.events if e.kind == "reverse_end")
    assert math.isclose(resume.t - wait.t, 7.0, abs_tol=1e-6)

    # the piece stands still while waiting
    assert math.isclose(res.head.v_at(0.5 * (wait.t + resume.t)), 0.0, abs_tol=1e-9)


def test_the_reversing_clearance_is_honoured():
    """The piece stops with its closest extremity at the requested distance."""
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=4.0, reversing_clearance=12.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0, reversing_clearance=12.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    assert res.warnings == ()

    wait = next(e for e in res.events if e.kind == "reverse_wait")
    # after a direct pass the extremity closest to the stand is the tail
    assert res.tail.x_at(wait.t) == pytest.approx(92.0, abs=1e-6)

    # after the reverse pass the piece sits upstream: the closest one is the head
    second = [e for e in res.events if e.kind == "reverse_wait"][1]
    assert res.head.x_at(second.t) == pytest.approx(68.0, abs=1e-6)


def test_an_unreachable_clearance_slows_the_mill_to_v_star():
    """Braking at 1 m/s2 from 3 m/s needs 4.5 m; C = 2 m so v* = 2 m/s at tail-out."""
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=4.0, reversing_clearance=2.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0, reversing_clearance=2.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    assert res.warnings == ()
    slow = next(e for e in res.events if e.kind == "reverse_slowdown")
    assert "v* 2.00" in slow.detail
    wait = next(e for e in res.events if e.kind == "reverse_wait")
    assert res.tail.x_at(wait.t) == pytest.approx(82.0, abs=1e-5)
    tail_out = next(e for e in res.events if e.kind == "tail_out")
    assert "v* 2.00" in tail_out.detail
    assert res.tail.v_at(tail_out.t) == pytest.approx(2.0, abs=1e-3)


def test_without_clearance_the_stop_is_at_the_braking_distance():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=4.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    wait = next(e for e in res.events if e.kind == "reverse_wait")
    assert res.tail.x_at(wait.t) == pytest.approx(84.5, abs=1e-6)
    assert res.warnings == ()


def test_on_a_reverse_pass_the_piece_travels_back():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=5.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=5.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    second_bite = [e for e in res.events if e.kind == "bite"][1]
    third_bite = [e for e in res.events if e.kind == "bite"][2]

    # between the second and third bite the piece sits upstream of the stand
    t_mid = 0.5 * (second_bite.t + third_bite.t)
    assert res.tail.x_at(t_mid) < 80.0
    # the head still is the extremity furthest downstream
    assert res.head.x_at(t_mid) >= res.tail.x_at(t_mid) - 1e-9


def test_head_pinned_at_the_coiler_and_virtual_head_free():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])
    assert res.x_coiler == 200.0
    assert max(s.x1 for s in res.head.segments) <= 200.0 + 1e-9
    assert res.head_virtual.x_at(res.t_end) > 200.0
    assert math.isclose(res.head.x_at(res.t_end), 200.0, abs_tol=1e-6)


def test_zoom_fires_on_the_virtual_head_beyond_the_coiler():
    """The trigger lies past the coiler: without a virtual head it would never fire."""
    # the virtual head passes the coiler by at most the final strip length, so a
    # long slab is needed for the trigger to be reachable
    case = _case(
        _line([("R", 50.0)]),
        [_pass(1, "R", FWD, 100.0, 50.0, 4.0, zoom_pct=10.0, zoom_trigger=200.0)],
        slab_len=60.0,
    )
    res = simulate_piece(case, case.products[0])
    zoom = [e for e in res.events if e.kind == "zoom"]
    assert len(zoom) == 1
    assert zoom[0].x == pytest.approx(250.0)
    # the tail speeds up by 10%, until the coiler slowdown takes over
    slowdown = next(e for e in res.events if e.kind == "coiler_slowdown")
    assert res.tail.v_at(0.5 * (zoom[0].t + slowdown.t)) == pytest.approx(4.4, rel=1e-6)
    assert res.tail.v_at(res.t_end) == pytest.approx(1.0, abs=1e-6)


def test_section_event_deferred_to_disengagement():
    line = Line(
        (
            Equipment("ST", "start", 0.0, accel=1.0),
            Equipment("R", "stand", 50.0, accel=1.0),
            Equipment("DC", "coiler", 300.0, accel=1.0),
        ),
        (
            Section(
                "S1",
                x_start=0.0,
                length=300.0,
                events=(
                    SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=2.0),
                    # fires while the stand is rolling: must be deferred to tail-out
                    SpeedEvent("S1-2", "S1", x_trigger=60.0, v_target=6.0),
                ),
            ),
        ),
    )
    case = _case(line, [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    tail_out = next(e for e in res.events if e.kind == "tail_out")
    change = next(e for e in res.events if e.kind == "speed_change" and e.t > 0)
    assert change.t == pytest.approx(tail_out.t)
    assert "deferred" in change.detail
    # before disengagement the mill commands, not the roller table
    assert res.head.v_at(tail_out.t - 0.5) == pytest.approx(4.0)


def test_master_enforces_the_mass_balance_in_the_tandem():
    equipment = (
        Equipment("ST", "start", 0.0, accel=1.0),
        Equipment("F1", "stand", 50.0, accel=1.0, group="FM"),
        Equipment("F2", "stand", 60.0, accel=1.0, group="FM"),
        Equipment("DC", "coiler", 300.0, accel=1.0),
    )
    line = Line(
        equipment,
        (
            Section(
                "S1",
                x_start=0.0,
                length=300.0,
                events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=2.0),),
            ),
        ),
    )
    case = _case(
        line,
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 3.0),  # inconsistent on purpose
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0, master=True),
        ],
    )
    harmonised, deviations = harmonise_tandem_speeds(case)
    speeds = {p.equipment_id: p.v_exit for p in harmonised.products[0].passes}
    assert speeds["F2"] == pytest.approx(8.0)
    assert speeds["F1"] == pytest.approx(4.0)
    assert len(deviations) == 1
    assert deviations[0].equipment_id == "F1"
    assert deviations[0].deviation_pct == pytest.approx(-33.333, abs=1e-3)


def test_an_unreachable_pass_gives_a_readable_error():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", FWD, 100.0, 50.0, 4.0), _pass(2, "R", FWD, 50.0, 25.0, 8.0)])
    case = Case(
        line=case.line,
        products=case.products,
        settings=SimSettings(max_time=200.0),
    )
    with pytest.raises(ModelError, match="not reachable"):
        simulate_piece(case, case.products[0])


def test_validation_catches_the_broken_thickness_chain():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", FWD, 90.0, 50.0, 4.0)])
    problems = [p.message for p in validate_case(case)]
    assert any("does not match" in p for p in problems)


def test_a_reverse_first_pass_is_rejected():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", REV, 100.0, 50.0, 4.0)])
    problems = [p.message for p in validate_case(case)]
    assert any("first pass" in p for p in problems)


def test_a_reverse_last_pass_is_rejected():
    """Closing backwards, the piece would never reach the coiler."""
    line = _line([("R", 50.0)])
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0),
        ],
    )
    problems = [p.message for p in validate_case(case)]
    assert any("last pass" in p for p in problems)


def test_the_coiler_slowdown_starts_while_the_mill_is_still_rolling():
    """Short run-out: the tandem must brake before the last tail-out."""
    line = _line([("F1", 50.0), ("F2", 60.0)], coiler_x=80.0)
    case = _case(
        line,
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    last_tail = max(e.t for e in res.events if e.kind == "tail_out")
    slow = next(e for e in res.events if e.kind == "coiler_slowdown")
    assert slow.t < last_tail
    assert res.tail.v_at(res.t_end) == pytest.approx(1.0, abs=1e-3)


def _two_coilers(
    stands: list[tuple[str, float]],
    dc1: float = 200.0,
    dc2: float = 230.0,
    extra: list[Equipment] | None = None,
) -> Line:
    equipment = [Equipment("ST", "start", 0.0, accel=1.0)]
    equipment += [Equipment(name, "stand", x, accel=1.0) for name, x in stands]
    equipment.append(Equipment("DC1", "coiler", dc1, accel=1.0))
    equipment.append(Equipment("DC2", "coiler", dc2, accel=1.0))
    if extra:
        equipment.extend(extra)
    x_end = max(e.x for e in equipment if e.kind == "coiler")
    section = Section(
        "S1",
        x_start=0.0,
        length=x_end,
        events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=2.0, direction=FWD),),
    )
    return Line(tuple(equipment), (section,))


def test_alternate_coilers_pin_at_their_own_position():
    case = replace(
        _case(_two_coilers([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)]),
        settings=SimSettings(n_pieces=4, coiler_pattern=("DC1", "DC2")),
    )
    results = simulate_case(case)
    assert [r.coiler_id for r in results] == ["DC1", "DC2", "DC1", "DC2"]
    assert results[0].x_coiler == pytest.approx(200.0)
    assert results[1].x_coiler == pytest.approx(230.0)
    assert max(s.x1 for s in results[0].head.segments) <= 200.0 + 1e-6
    assert max(s.x1 for s in results[1].head.segments) > 200.0 + 1e-3
    assert max(s.x1 for s in results[1].head.segments) <= 230.0 + 1e-6


def test_two_coilers_without_a_pattern_are_rejected():
    case = _case(_two_coilers([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any("coiler_pattern is required" in m for m in messages)


def test_the_cache_does_not_mix_coilers():
    case = replace(
        _case(_two_coilers([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)]),
        settings=SimSettings(n_pieces=4, coiler_pattern=("DC1", "DC2")),
    )
    base = base_results(case)
    assert ("P", "DC1") in base and ("P", "DC2") in base
    assert base[("P", "DC1")].x_coiler == pytest.approx(200.0)
    assert base[("P", "DC2")].x_coiler == pytest.approx(230.0)


def test_zoom_trigger_is_the_same_on_both_coilers():
    line = _two_coilers([("R", 50.0)], dc1=120.0, dc2=180.0)
    case = replace(
        _case(
            line,
            [_pass(1, "R", FWD, 100.0, 50.0, 4.0, zoom_pct=10.0, zoom_trigger=80.0)],
            slab_len=40.0,
        ),
        settings=SimSettings(n_pieces=2, coiler_pattern=("DC1", "DC2")),
    )
    near = simulate_piece(case, case.products[0], coiler=case.line.get("DC1"))
    far = simulate_piece(case, case.products[0], coiler=case.line.get("DC2"))
    zoom_near = next(e for e in near.events if e.kind == "zoom")
    zoom_far = next(e for e in far.events if e.kind == "zoom")
    assert zoom_near.x == pytest.approx(130.0)
    assert zoom_far.x == pytest.approx(zoom_near.x)


def test_more_than_three_coilers_are_rejected():
    extra = [
        Equipment("DC3", "coiler", 260.0, accel=1.0),
        Equipment("DC4", "coiler", 280.0, accel=1.0),
    ]
    case = replace(
        _case(
            _two_coilers([("R", 50.0)], extra=extra),
            [_pass(1, "R", FWD, 100.0, 50.0, 4.0)],
        ),
        settings=SimSettings(n_pieces=2, coiler_pattern=("DC1", "DC2")),
    )
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any(f"at most {MAX_COILERS} coilers" in m for m in messages)
