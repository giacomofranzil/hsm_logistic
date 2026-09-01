"""Checks of the Excel layer, of the JSON contract and of the tracking import."""

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


def test_excel_round_trip_preserves_the_case(tmp_path):
    original = example_case()
    path = write_case(original, tmp_path / "case.xlsx")
    loaded = read_case(path)

    assert loaded.line.equipment == original.line.equipment
    assert loaded.line.sections == original.line.sections
    assert loaded.products == original.products
    assert loaded.settings == original.settings


def test_the_empty_template_has_the_sheets_and_headers(tmp_path):
    path = write_case(example_case(), tmp_path / "template.xlsx", include_data=False)
    wb = load_workbook(path)
    assert {"Guide", "Info", "Layout", "Sections", "Products", "PassSchedule", "Simulation"} <= set(
        wb.sheetnames
    )
    assert wb["Layout"]["A1"].value == "equipment_id"
    assert wb["Sections"]["H1"].value == "d1_m"
    assert wb["Layout"].max_row == 1, "the template must contain no data"


def test_json_round_trip_preserves_the_case():
    original = example_case()
    payload = json.loads(json.dumps(case_to_dict(original)))
    loaded = case_from_dict(payload)

    assert loaded.line.equipment == original.line.equipment
    assert loaded.products == original.products
    assert loaded.settings == original.settings


def test_parsing_errors_point_at_sheet_and_cell(tmp_path):
    path = write_case(example_case(), tmp_path / "broken.xlsx")
    wb = load_workbook(path)
    wb["Layout"]["C5"] = "twenty five"
    wb.save(path)

    with pytest.raises(ValidationError) as exc:
        read_case(path)
    issue = exc.value.issues[0]
    assert issue.sheet == "Layout"
    assert issue.cell == "C5"
    assert "is not a number" in issue.message


def test_model_errors_trace_back_to_the_pass_row(tmp_path):
    path = write_case(example_case(), tmp_path / "broken2.xlsx")
    wb = load_workbook(path)
    wb["PassSchedule"]["F4"] = 200.0  # h_out larger than h_in
    wb.save(path)

    with pytest.raises(ValidationError) as exc:
        read_case(path)
    reduction = [i for i in exc.value.issues if "invalid reduction" in i.message]
    assert reduction and reduction[0].sheet == "PassSchedule"
    assert reduction[0].cell == "B4"


def test_an_unsupported_schema_version_is_rejected(tmp_path):
    path = write_case(example_case(), tmp_path / "old.xlsx")
    wb = load_workbook(path)
    wb["Info"]["B2"] = "0"
    wb.save(path)

    with pytest.raises(ValidationError, match="schema_version"):
        read_case(path)


def test_a_section_event_beyond_the_length_is_rejected(tmp_path):
    path = write_case(example_case(), tmp_path / "section.xlsx")
    wb = load_workbook(path)
    wb["Sections"]["H4"] = 999.0
    wb.save(path)

    with pytest.raises(ValidationError, match="beyond the section length"):
        read_case(path)


def test_an_older_workbook_without_optional_columns_still_loads(tmp_path):
    """Columns added after the first schema version must not break existing files."""
    path = write_case(example_case(), tmp_path / "older.xlsx")
    wb = load_workbook(path)
    ws = wb["PassSchedule"]
    header = [c.value for c in ws[1]]
    ws.delete_cols(header.index("reversing_clearance_m") + 1)
    wb.save(path)

    loaded = read_case(path)
    assert all(p.reversing_clearance == 0.0 for p in loaded.products[0].passes)


def test_writing_the_results(tmp_path):
    case, deviations = harmonise_tandem_speeds(example_case())
    base = base_results(case)
    results = sequence(case, base, case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)
    curve = gap_vs_pacing(case, base)
    best = min_feasible_pacing(case, base, curve)

    path = write_results(tmp_path / "out.xlsx", case, results, analyses, deviations, curve, best)
    wb = load_workbook(path)
    assert {"Summary", "Events", "Occupancy", "Gap", "PacingCurve", "MassBalance"} <= set(
        wb.sheetnames
    )
    assert wb["Events"].max_row > 10


def test_the_json_report_carries_segments_and_outcomes():
    case, deviations = harmonise_tandem_speeds(example_case())
    base = base_results(case)
    results = sequence(case, base, case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)

    report = report_to_dict(case, results, analyses, deviations)
    json.dumps(report)  # must be serialisable

    assert report["pieces"][0]["head_segments"][0]["t0_s"] == 0.0
    assert report["pieces"][0]["length_kinematic_m"] == pytest.approx(
        report["pieces"][0]["length_geometric_m"], rel=1e-6
    )
    assert report["gaps"][0]["ok"] is True


def test_tracking_csv_import():
    rows = [
        "piece_id,time_s,head_m,tail_m",
        "A1,0.0,0.0,-10.5",
        "A1,1.0,1.2,-9.3",
        "A2,0.0,0.0,-10.5",
    ]
    series = parse_tracking(rows)
    assert len(series) == 2
    first = next(s for s in series if s.piece_id == "A1")
    assert first.t == [0.0, 1.0]
    assert first.head == [0.0, 1.2]
    assert first.shift(10.0).t == [10.0, 11.0]


def test_tracking_without_the_tail_column():
    series = parse_tracking(["piece_id,time_s,head_m", "A1,0.0,5.0"])
    assert series[0].tail == [5.0]


def test_tracking_with_missing_columns():
    with pytest.raises(ValueError, match="missing columns"):
        parse_tracking(["piece,time", "A1,0"])
