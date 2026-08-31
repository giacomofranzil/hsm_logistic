"""Interfaccia a riga di comando.

Oltre all'uso interattivo, i comandi ``to-json`` e ``run`` costituiscono il
punto di aggancio per un Livello 2 scritto in altro linguaggio: si passa un
caso in JSON e si riceve un report in JSON, senza dipendere da Excel.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.analysis import analyse_sequence
from .core.contract import case_from_dict, case_to_dict, report_to_dict
from .core.model import harmonise_tandem_speeds
from .core.studies import base_results, gap_vs_pacing, min_feasible_pacing, monte_carlo, sequence
from .example import example_case
from .io_excel import ValidationError, read_case, write_case, write_results

DEFAULT_PORT = 8731


def _load(path: str | None) -> "object":
    if path is None:
        return example_case()
    p = Path(path)
    if p.suffix.lower() == ".json":
        return case_from_dict(json.loads(p.read_text(encoding="utf-8")))
    return read_case(p)


def _cmd_template(args: argparse.Namespace) -> int:
    path = write_case(example_case(), args.output, include_data=args.with_example)
    kind = "l'esempio compilato" if args.with_example else "il template vuoto"
    print(f"Scritto {kind}: {path}")
    return 0


def _cmd_to_json(args: argparse.Namespace) -> int:
    case = _load(args.input)
    payload = json.dumps(case_to_dict(case), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"Scritto {args.output}")
    else:
        print(payload)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    case = _load(args.input)
    case, deviations = harmonise_tandem_speeds(case)
    if args.pacing is not None:
        from dataclasses import replace

        case = replace(case, settings=replace(case.settings, pacing=args.pacing))

    base = base_results(case)
    results = sequence(case, base, case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)

    curve = gap_vs_pacing(case, base) if args.scan else None
    best = min_feasible_pacing(case, base, curve) if args.scan else None
    mc = monte_carlo(case, runs=args.monte_carlo) if args.monte_carlo else None

    if args.json:
        report = report_to_dict(case, results, analyses, deviations, curve, best, mc)
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Report JSON scritto in {args.json}")

    if args.excel:
        write_results(args.excel, case, results, analyses, deviations, curve, best, mc)
        print(f"Risultati Excel scritti in {args.excel}")

    print(f"Pacing simulato: {case.settings.pacing:.1f} s su {len(results)} pezzi")
    if analyses:
        worst = min(analyses, key=lambda a: a.min_gap)
        state = "ammissibile" if worst.ok else "VIOLAZIONE"
        where = worst.critical
        print(
            f"Gap minimo {worst.min_gap:.1f} m fra {worst.front_id} e {worst.rear_id} "
            f"({state})"
        )
        if where:
            print(
                f"  punto critico a x={where.x:.1f} m, t={where.t:.1f} s"
                + (f", sezione {where.section}" if where.section else "")
                + (f", gap temporale {worst.headway:.1f} s" if worst.headway else "")
            )
    else:
        print("I pezzi non sono mai contemporaneamente in linea.")

    if best is not None:
        print(
            f"Pacing minimo ammissibile: {best.pacing:.1f} s"
            + (f" (vincolo in {best.section})" if best.section else "")
        )
    if mc is not None:
        print(
            f"Monte Carlo su {mc.runs} run: {mc.violations} violazioni "
            f"({100 * mc.violation_rate:.1f}%), gap medio {mc.mean:.1f} m, "
            f"quinto percentile {mc.percentile(0.05):.1f} m"
        )

    if analyses and not min(analyses, key=lambda a: a.min_gap).ok:
        return 2
    return 0


def _cmd_app(args: argparse.Namespace) -> int:
    from streamlit.web import cli as stcli

    script = Path(__file__).parent / "app" / "streamlit_app.py"
    sys.argv = [
        "streamlit",
        "run",
        str(script),
        "--server.port",
        str(args.port),
        "--server.address",
        args.address,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    return int(stcli.main() or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hsmpace",
        description="Diagramma spazio-tempo e analisi del pacing per Hot Strip Mill",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("template", help="genera il workbook di input")
    p.add_argument("output", help="percorso del file .xlsx da creare")
    p.add_argument(
        "--with-example",
        action="store_true",
        help="riempie il workbook con l'impianto di esempio",
    )
    p.set_defaults(func=_cmd_template)

    p = sub.add_parser("to-json", help="converte un input in JSON per il Livello 2")
    p.add_argument("input", nargs="?", help="file .xlsx o .json (vuoto = esempio incluso)")
    p.add_argument("-o", "--output", help="file JSON da scrivere")
    p.set_defaults(func=_cmd_to_json)

    p = sub.add_parser("run", help="simula e analizza il gap")
    p.add_argument("input", nargs="?", help="file .xlsx o .json (vuoto = esempio incluso)")
    p.add_argument("--pacing", type=float, help="sovrascrive il pacing del file")
    p.add_argument("--scan", action="store_true", help="calcola la curva gap-vs-pacing")
    p.add_argument(
        "--monte-carlo", type=int, metavar="N", help="esegue N run di robustezza"
    )
    p.add_argument("--json", help="scrive il report in JSON")
    p.add_argument("--excel", help="scrive i risultati in xlsx")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("app", help="avvia l'interfaccia web")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--address", default="127.0.0.1")
    p.set_defaults(func=_cmd_app)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
