"""Scrittura dei risultati su un workbook separato.

Il file di input resta sempre in sola lettura: i risultati non vengono mai
scritti dentro il file che l'utente compila, per non ritrovarsi in giro
workbook con input nuovi e risultati vecchi.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..core.analysis import GapAnalysis, mass_balance
from ..core.model import Case, MassFlowDeviation
from ..core.simulate import PieceResult
from ..core.studies import MonteCarloResult, PacingPoint

_HEADER_FILL = PatternFill("solid", fgColor="1F3864")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def _table(wb: Workbook, title: str, header: list[str], rows: list[list]) -> None:
    ws = wb.create_sheet(title)
    for col, name in enumerate(header, start=1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = max(12, min(34, len(name) + 6))
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=value)
    ws.freeze_panes = "A2"


def write_results(
    path: str | Path,
    case: Case,
    results: list[PieceResult],
    analyses: list[GapAnalysis],
    deviations: tuple[MassFlowDeviation, ...] = (),
    curve: list[PacingPoint] | None = None,
    min_pacing: PacingPoint | None = None,
    mc: MonteCarloResult | None = None,
) -> Path:
    path = Path(path)
    wb = Workbook()
    wb.remove(wb.active)

    summary: list[list] = [
        ["Impianto", case.info.get("mill_name", "")],
        ["Pacing nominale [s]", case.settings.pacing],
        ["Gap minimo richiesto [m]", case.settings.gap_min],
        ["Pezzi simulati", len(results)],
        ["Sequenza prodotti", ", ".join(case.piece_products)],
    ]
    if analyses:
        worst = min(analyses, key=lambda a: a.min_gap)
        summary += [
            ["Gap minimo della sequenza [m]", round(worst.min_gap, 2)],
            ["Coppia critica", f"{worst.front_id} / {worst.rear_id}"],
            ["Posizione critica [m]", round(worst.critical.x, 1) if worst.critical else ""],
            ["Istante critico [s]", round(worst.critical.t, 1) if worst.critical else ""],
            ["Sezione critica", worst.critical.section if worst.critical else ""],
            ["Gap temporale al punto critico [s]", round(worst.headway, 1) if worst.headway else ""],
            ["Esito", "ammissibile" if worst.ok else "VIOLAZIONE"],
        ]
    else:
        summary.append(["Esito", "i pezzi non interagiscono mai"])
    if min_pacing is not None:
        summary += [
            ["Pacing minimo ammissibile [s]", round(min_pacing.pacing, 1)],
            ["Vincolo attivo al pacing minimo", min_pacing.section or min_pacing.equipment],
        ]
    if mc is not None:
        summary += [
            ["Monte Carlo: run", mc.runs],
            ["Monte Carlo: violazioni", mc.violations],
            ["Monte Carlo: tasso di violazione [%]", round(100 * mc.violation_rate, 2)],
            ["Monte Carlo: gap medio [m]", round(mc.mean, 2)],
            ["Monte Carlo: gap 5o percentile [m]", round(mc.percentile(0.05), 2)],
        ]
    _table(wb, "Riepilogo", ["Voce", "Valore"], summary)

    _table(
        wb,
        "Eventi",
        ["pezzo", "t [s]", "evento", "apparecchiatura", "x [m]", "dettaglio"],
        [
            [r.piece_id, round(e.t, 3), e.kind, e.equipment_id, round(e.x, 2), e.detail]
            for r in results
            for e in r.events
        ],
    )

    _table(
        wb,
        "Occupazione",
        ["pezzo", "apparecchiatura", "passata", "ingresso [s]", "uscita [s]", "durata [s]"],
        [
            [r.piece_id, o.equipment_id, o.pass_no, round(o.t_in, 2), round(o.t_out, 2), round(o.duration, 2)]
            for r in results
            for o in r.occupancy
        ],
    )

    _table(
        wb,
        "Gap",
        [
            "pezzo davanti",
            "pezzo dietro",
            "gap minimo [m]",
            "t [s]",
            "x [m]",
            "sezione",
            "apparecchiatura",
            "gap temporale [s]",
            "prima violazione [s]",
            "esito",
        ],
        [
            [
                a.front_id,
                a.rear_id,
                round(a.min_gap, 2),
                round(a.critical.t, 2) if a.critical else "",
                round(a.critical.x, 2) if a.critical else "",
                a.critical.section if a.critical else "",
                a.critical.equipment if a.critical else "",
                round(a.headway, 2) if a.headway is not None else "",
                round(a.t_first_violation, 2) if a.t_first_violation is not None else "",
                "ok" if a.ok else "VIOLAZIONE",
            ]
            for a in analyses
        ],
    )

    if curve:
        _table(
            wb,
            "PacingCurve",
            ["pacing [s]", "gap minimo [m]", "ammissibile", "t critico [s]", "x critico [m]", "sezione", "coppia"],
            [
                [
                    round(p.pacing, 2),
                    round(p.min_gap, 2) if p.min_gap != float("inf") else "nessuna interazione",
                    "si" if p.feasible else "no",
                    round(p.t_critical, 2) if p.t_critical is not None else "",
                    round(p.x_critical, 2) if p.x_critical is not None else "",
                    p.section,
                    p.pair,
                ]
                for p in curve
            ],
        )

    _table(
        wb,
        "BilancioMassa",
        ["prodotto", "lunghezza cinematica [m]", "lunghezza geometrica [m]", "scarto [%]", "esito"],
        [
            [c.piece_id, round(c.length_kinematic, 2), round(c.length_geometric, 2), round(c.error_pct, 4), "ok" if c.ok else "ATTENZIONE"]
            for c in mass_balance(results)
        ],
    )

    if deviations:
        _table(
            wb,
            "MassFlowTandem",
            ["prodotto", "passata", "gabbia", "v inserita [m/s]", "v da bilancio [m/s]", "scarto [%]"],
            [
                [d.product_id, d.pass_no, d.equipment_id, round(d.v_input, 4), round(d.v_massflow, 4), round(d.deviation_pct, 3)]
                for d in deviations
            ],
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
