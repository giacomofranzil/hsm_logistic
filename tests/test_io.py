"""Verifiche del layer Excel, del contratto JSON e dell'import del tracking."""

from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook

from hsmpace.core.analysis import analyse_sequence
from hsmpace.core.contract import case_from_dict, case_to_dict, report_to_dict
from hsmpace.core.model import harmonise_tandem_speeds
from hsmpace.core.studies import base_results, gap_vs_pacing, min_feasible_pacing, sequence
from hsmpace.core.tracking import parse_tracking
from hsmpace.example import example_case
from hsmpace.io_excel import ValidationError, read_case, write_case, write_results


def test_round_trip_excel_conserva_il_caso(tmp_path):
    original = example_case()
    path = write_case(original, tmp_path / "caso.xlsx")
    letto = read_case(path)

    assert letto.line.equipment == original.line.equipment
    assert letto.line.sections == original.line.sections
    assert letto.products == original.products
    assert letto.settings == original.settings


def test_template_vuoto_ha_i_fogli_e_le_intestazioni(tmp_path):
    path = write_case(example_case(), tmp_path / "template.xlsx", include_data=False)
    wb = load_workbook(path)
    assert {"Guida", "Info", "Layout", "Sections", "Products", "PassSchedule", "Simulation"} <= set(
        wb.sheetnames
    )
    assert wb["Layout"]["A1"].value == "equipment_id"
    assert wb["Sections"]["H1"].value == "d1_m"
    assert wb["Layout"].max_row == 1, "il template non deve contenere dati"


def test_round_trip_json_conserva_il_caso():
    original = example_case()
    payload = json.loads(json.dumps(case_to_dict(original)))
    letto = case_from_dict(payload)

    assert letto.line.equipment == original.line.equipment
    assert letto.products == original.products
    assert letto.settings == original.settings


def test_errori_di_parsing_indicano_foglio_e_cella(tmp_path):
    path = write_case(example_case(), tmp_path / "rotto.xlsx")
    wb = load_workbook(path)
    wb["Layout"]["C5"] = "venticinque"
    wb.save(path)

    with pytest.raises(ValidationError) as exc:
        read_case(path)
    issue = exc.value.issues[0]
    assert issue.sheet == "Layout"
    assert issue.cell == "C5"
    assert "non e' un numero" in issue.message


def test_errori_di_modello_risalgono_alla_riga_della_passata(tmp_path):
    path = write_case(example_case(), tmp_path / "rotto2.xlsx")
    wb = load_workbook(path)
    wb["PassSchedule"]["F4"] = 200.0  # h_out maggiore di h_in
    wb.save(path)

    with pytest.raises(ValidationError) as exc:
        read_case(path)
    riduzione = [i for i in exc.value.issues if "riduzione non valida" in i.message]
    assert riduzione and riduzione[0].sheet == "PassSchedule"
    assert riduzione[0].cell == "B4"


def test_schema_version_non_supportata_viene_rifiutata(tmp_path):
    path = write_case(example_case(), tmp_path / "vecchio.xlsx")
    wb = load_workbook(path)
    wb["Info"]["B2"] = "0"
    wb.save(path)

    with pytest.raises(ValidationError, match="schema_version"):
        read_case(path)


def test_evento_di_sezione_oltre_la_lunghezza_viene_rifiutato(tmp_path):
    path = write_case(example_case(), tmp_path / "sezione.xlsx")
    wb = load_workbook(path)
    wb["Sections"]["H4"] = 999.0
    wb.save(path)

    with pytest.raises(ValidationError, match="oltre la lunghezza della sezione"):
        read_case(path)


def test_scrittura_dei_risultati(tmp_path):
    case, deviations = harmonise_tandem_speeds(example_case())
    base = base_results(case)
    results = sequence(case, base, case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)
    curve = gap_vs_pacing(case, base)
    best = min_feasible_pacing(case, base, curve)

    path = write_results(tmp_path / "out.xlsx", case, results, analyses, deviations, curve, best)
    wb = load_workbook(path)
    assert {"Riepilogo", "Eventi", "Occupazione", "Gap", "PacingCurve", "BilancioMassa"} <= set(
        wb.sheetnames
    )
    assert wb["Eventi"].max_row > 10


def test_report_json_contiene_i_segmenti_e_gli_esiti():
    case, deviations = harmonise_tandem_speeds(example_case())
    base = base_results(case)
    results = sequence(case, base, case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)

    report = report_to_dict(case, results, analyses, deviations)
    json.dumps(report)  # deve essere serializzabile

    assert report["pieces"][0]["head_segments"][0]["t0_s"] == 0.0
    assert report["pieces"][0]["length_kinematic_m"] == pytest.approx(
        report["pieces"][0]["length_geometric_m"], rel=1e-6
    )
    assert report["gaps"][0]["ok"] is True


def test_import_tracking_csv():
    righe = [
        "piece_id,time_s,head_m,tail_m",
        "A1,0.0,0.0,-10.5",
        "A1,1.0,1.2,-9.3",
        "A2,0.0,0.0,-10.5",
    ]
    serie = parse_tracking(righe)
    assert len(serie) == 2
    prima = next(s for s in serie if s.piece_id == "A1")
    assert prima.t == [0.0, 1.0]
    assert prima.head == [0.0, 1.2]
    assert prima.shift(10.0).t == [10.0, 11.0]


def test_tracking_senza_colonna_coda():
    serie = parse_tracking(["piece_id,time_s,head_m", "A1,0.0,5.0"])
    assert serie[0].tail == [5.0]


def test_tracking_con_colonne_mancanti():
    with pytest.raises(ValueError, match="colonne mancanti"):
        parse_tracking(["piece,tempo", "A1,0"])
