"""Verifiche dell'analisi del gap e degli studi sul pacing."""

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


def test_gap_coincide_con_la_differenza_delle_traiettorie(case, base):
    first = base["P1"]
    second = shift_result(first, 120.0, "#2")
    series = gap_series(first, second)

    span = series.t_end - series.t_start
    for frac in (0.05, 0.25, 0.5, 0.75, 0.95):
        t = series.t_start + frac * span
        atteso = first.tail.x_at(t) - second.head.x_at(t)
        assert series.value_at(t) == pytest.approx(atteso, abs=1e-9)


def test_la_testa_resta_sempre_a_valle_della_coda(case, base):
    assert check_extremities(base["P1"]) == []


def test_prima_violazione_cade_esattamente_sulla_soglia(case, base):
    first = base["P1"]
    second = shift_result(first, 95.0, "#2")
    analysis = analyse_pair(first, second, gap_min=5.0, line=case.line)

    assert analysis.t_first_violation is not None
    assert analysis.series.value_at(analysis.t_first_violation) == pytest.approx(5.0, abs=1e-6)
    assert analysis.min_gap < 5.0
    assert not analysis.ok


def test_gap_temporale_e_coerente_con_la_posizione_critica(case, base):
    first = base["P1"]
    second = shift_result(first, 110.0, "#2")
    analysis = analyse_pair(first, second, gap_min=5.0, line=case.line)

    critical = analysis.critical
    assert critical is not None
    assert analysis.headway is not None
    quando = critical.t - analysis.headway
    assert first.tail.x_at(quando) == pytest.approx(critical.x, abs=1e-3)


def test_pacing_ampio_non_produce_interazione(case, base):
    results = sequence(case, base, 400.0)
    assert analyse_sequence(results, case.settings.gap_min, case.line) == []


def test_confronta_anche_le_coppie_non_adiacenti(case, base):
    """Con lo sbozzatore reversibile il vincolo puo' cadere fra il pezzo N e N+2."""
    stretto = replace(case, settings=replace(case.settings, n_pieces=3))
    results = sequence(stretto, base, 60.0)
    coppie = {(a.front_id, a.rear_id) for a in analyse_sequence(results, 5.0, case.line)}
    assert ("#1", "#3") in coppie


def test_curva_del_pacing_e_il_pacing_minimo(case, base):
    curve = gap_vs_pacing(case, base)
    assert len(curve) == case.settings.pacing_scan_steps
    assert not curve[0].feasible, "il pacing piu' stretto della scansione deve violare"

    best = min_feasible_pacing(case, base, curve)
    assert best is not None and best.feasible

    poco_meno = sequence(case, base, best.pacing - 1.0)
    analisi = analyse_sequence(poco_meno, case.settings.gap_min, case.line)
    assert min(a.min_gap for a in analisi) < case.settings.gap_min


def test_il_vincolo_attivo_e_riportato(case, base):
    best = min_feasible_pacing(case, base)
    assert best is not None
    assert best.section or best.equipment


def test_monte_carlo_riproducibile_e_conservativo(case, base):
    stretto = replace(case, settings=replace(case.settings, pacing=112.0))
    uno = monte_carlo(stretto, runs=120, seed=7)
    due = monte_carlo(stretto, runs=120, seed=7)
    assert uno.min_gaps == due.min_gaps
    assert uno.errors == 0

    largo = monte_carlo(replace(case, settings=replace(case.settings, pacing=170.0)), runs=120, seed=7)
    assert largo.violation_rate <= uno.violation_rate


def test_il_punto_critico_e_a_monte_dello_sbozzatore(case, base):
    """Il gap si chiude dove lo sbozzatore reversibile riporta il bar verso il forno.

    Al pacing minimo del caso di esempio il punto critico cade a monte di R1,
    posizione che la coda del pezzo davanti puo' occupare solo per effetto delle
    passate inverse: senza inversioni il bar non tornerebbe mai cosi' indietro e
    il pezzo che segue avrebbe la linea libera.
    """
    best = min_feasible_pacing(case, base)
    assert best is not None

    results = sequence(case, base, best.pacing - 2.0)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)
    worst = min(analyses, key=lambda a: a.min_gap)
    assert worst.min_gap < case.settings.gap_min

    x_r1 = case.line.get("R1").x
    assert worst.critical.x < x_r1

    davanti = next(r for r in results if r.piece_id == worst.front_id)
    assert any(s.v0 < 0 for s in davanti.tail.segments), "il bar deve risalire la linea"
    assert min(s.x1 for s in davanti.tail.segments) < x_r1


def test_la_testa_fisica_non_supera_mai_l_avvolgitore(case, base):
    for res in sequence(case, base, case.settings.pacing):
        assert res.x_coiler is not None
        assert max(s.x1 for s in res.head.segments) <= res.x_coiler + 1e-6
        assert res.head_virtual.x_at(res.t_end) > res.x_coiler


def test_bilancio_di_massa_sul_caso_di_esempio(case, base):
    results = sequence(case, base, case.settings.pacing)
    checks = mass_balance(results)
    assert checks and all(c.ok for c in checks)


def test_prodotti_diversi_nella_stessa_sequenza(case):
    sottile = replace(
        case.products[0],
        id="P2",
        passes=tuple(
            replace(p, product_id="P2", v_exit=p.v_exit * 1.1) for p in case.products[0].passes
        ),
    )
    misto = replace(
        case,
        products=(case.products[0], sottile),
        settings=replace(case.settings, piece_products=("P1", "P2", "P1")),
    )
    misto, _ = harmonise_tandem_speeds(misto)
    base_misto = base_results(misto)
    assert set(base_misto) == {"P1", "P2"}

    results = sequence(misto, base_misto, 150.0)
    assert [r.product_id for r in results] == ["P1", "P2", "P1"]
    assert results[1].t_end != results[0].t_end + 150.0


def test_simulazione_diretta_e_traslazione_coincidono(case):
    diretta = simulate_piece(case, case.products[0], t_release=137.0, piece_id="#2")
    traslata = shift_result(simulate_piece(case, case.products[0]), 137.0, "#2")
    assert diretta.t_end == pytest.approx(traslata.t_end)
    for t in (150.0, 200.0, 300.0):
        assert diretta.head.x_at(t) == pytest.approx(traslata.head.x_at(t), abs=1e-9)
        assert diretta.tail.x_at(t) == pytest.approx(traslata.tail.x_at(t), abs=1e-9)
