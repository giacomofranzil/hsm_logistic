"""Verifiche del simulatore: cinematica, bilancio di massa, inversioni, zoom."""

from __future__ import annotations

import math

import pytest

from hsmpace.core.model import (
    FWD,
    REV,
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
from hsmpace.core.simulate import simulate_piece


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


def test_passata_singola_tempi_esatti():
    """Caso a mano: rampa 0->2 m/s, corsa fino alla gabbia, laminazione, coiler."""
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    bite = next(e for e in res.events if e.kind == "bite")
    tail_out = next(e for e in res.events if e.kind == "tail_out")
    # 2 s di rampa a 1 m/s2 coprono 2 m, i restanti 48 m a 2 m/s
    assert math.isclose(bite.t, 26.0, abs_tol=1e-6)
    # lambda = 2, quindi la coda avanza a 2 m/s e impiega 5 s a liberare la gabbia
    assert math.isclose(tail_out.t, 31.0, abs_tol=1e-6)
    assert math.isclose(res.head.x_at(31.0), 70.0, abs_tol=1e-6)
    assert math.isclose(res.tail.x_at(31.0), 50.0, abs_tol=1e-6)
    # coda al coiler: 150 m residui a 4 m/s
    assert math.isclose(res.t_end, 68.5, abs_tol=1e-6)


def test_bilancio_di_massa_esatto():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])
    assert math.isclose(res.length_geometric, 20.0, abs_tol=1e-9)
    assert math.isclose(res.length_kinematic, 20.0, abs_tol=1e-6)
    assert abs(res.length_error) < 1e-6
    assert res.warnings == ()


def test_la_coda_e_piu_lenta_della_testa_solo_durante_la_passata():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    # in laminazione: testa 4 m/s, coda 2 m/s
    assert math.isclose(res.head.v_at(28.0), 4.0, abs_tol=1e-9)
    assert math.isclose(res.tail.v_at(28.0), 2.0, abs_tol=1e-9)
    # dopo il tail-out il pezzo e' rigido
    assert math.isclose(res.head.v_at(40.0), res.tail.v_at(40.0), abs_tol=1e-9)


def test_catena_di_bilancio_di_massa_nel_tandem():
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
    # con due gabbie ingaggiate, lambda complessivo 4
    assert math.isclose(res.head.v_at(t) / res.tail.v_at(t), 4.0, rel_tol=1e-9)
    assert math.isclose(res.length_geometric, 40.0, abs_tol=1e-9)
    assert math.isclose(res.length_kinematic, 40.0, abs_tol=1e-6)


def test_inversione_rispetta_il_reversing_delay():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=7.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0, reversing_delay=7.0),
        ],
    )
    res = simulate_piece(case, case.products[0])

    kinds = [e.kind for e in res.events]
    assert kinds.count("bite") == 3
    assert kinds.count("reverse_start") == 2

    wait = next(e for e in res.events if e.kind == "reverse_wait")
    resume = next(e for e in res.events if e.kind == "reverse_end")
    assert math.isclose(resume.t - wait.t, 7.0, abs_tol=1e-6)

    # durante l'attesa il pezzo e' fermo
    assert math.isclose(res.head.v_at(0.5 * (wait.t + resume.t)), 0.0, abs_tol=1e-9)


def test_in_passata_inversa_il_pezzo_torna_indietro():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=5.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0, reversing_delay=5.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    second_bite = [e for e in res.events if e.kind == "bite"][1]
    third_bite = [e for e in res.events if e.kind == "bite"][2]

    # fra la seconda e la terza presa il pezzo sta a monte della gabbia
    t_mid = 0.5 * (second_bite.t + third_bite.t)
    assert res.tail.x_at(t_mid) < 80.0
    # la testa resta comunque l'estremita' geometricamente piu' a valle
    assert res.head.x_at(t_mid) >= res.tail.x_at(t_mid) - 1e-9


def test_testa_bloccata_al_coiler_e_testa_virtuale_libera():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])
    assert res.x_coiler == 200.0
    assert max(s.x1 for s in res.head.segments) <= 200.0 + 1e-9
    assert res.head_virtual.x_at(res.t_end) > 200.0
    assert math.isclose(res.head.x_at(res.t_end), 200.0, abs_tol=1e-6)


def test_zoom_scatta_sulla_testa_virtuale_oltre_il_coiler():
    """Il trigger e' oltre l'avvolgitore: senza testa virtuale non scatterebbe mai."""
    # la testa virtuale supera il coiler al massimo della lunghezza finale del
    # nastro, quindi serve una bramma lunga perche' il trigger sia raggiungibile
    case = _case(
        _line([("R", 50.0)]),
        [_pass(1, "R", FWD, 100.0, 50.0, 4.0, zoom_pct=10.0, zoom_trigger=200.0)],
        slab_len=60.0,
    )
    res = simulate_piece(case, case.products[0])
    zoom = [e for e in res.events if e.kind == "zoom"]
    assert len(zoom) == 1
    assert zoom[0].x == pytest.approx(250.0)
    # la coda accelera del 10% dopo lo zoom
    assert res.tail.v_at(res.t_end) == pytest.approx(4.4, rel=1e-6)


def test_evento_di_sezione_differito_al_disingaggio():
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
                    # scatta mentre la gabbia lamina: va rimandato al tail-out
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
    assert "differito" in change.detail
    # prima del disingaggio comanda il mill, non la via a rulli
    assert res.head.v_at(tail_out.t - 0.5) == pytest.approx(4.0)


def test_master_impone_il_bilancio_di_massa_nel_tandem():
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
            _pass(1, "F1", FWD, 100.0, 50.0, 3.0),  # incoerente di proposito
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


def test_passata_irraggiungibile_da_errore_leggibile():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", FWD, 100.0, 50.0, 4.0), _pass(2, "R", FWD, 50.0, 25.0, 8.0)])
    case = Case(
        line=case.line,
        products=case.products,
        settings=SimSettings(max_time=200.0),
    )
    with pytest.raises(ModelError, match="non e' raggiungibile"):
        simulate_piece(case, case.products[0])


def test_validazione_intercetta_la_catena_di_spessori_rotta():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", FWD, 90.0, 50.0, 4.0)])
    problems = [p.message for p in validate_case(case)]
    assert any("non coincide" in p for p in problems)


def test_prima_passata_inversa_rifiutata():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", REV, 100.0, 50.0, 4.0)])
    problems = [p.message for p in validate_case(case)]
    assert any("prima passata" in p for p in problems)
