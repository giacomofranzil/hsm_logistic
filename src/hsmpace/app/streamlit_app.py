"""Interfaccia web del tool di pacing.

Gira indifferentemente in locale sul PC di chi la usa (127.0.0.1, nessun
server, nessuna porta da aprire) o pubblicata su un server d'ufficio.
"""

from __future__ import annotations

import io
import tempfile
from dataclasses import replace
from pathlib import Path

import streamlit as st

from hsmpace.core.analysis import analyse_sequence, mass_balance
from hsmpace.core.model import Case, harmonise_tandem_speeds
from hsmpace.core.simulate import PieceResult
from hsmpace.core.studies import (
    base_results,
    gap_vs_pacing,
    min_feasible_pacing,
    monte_carlo,
    sequence,
)
from hsmpace.core.tracking import parse_tracking
from hsmpace.example import example_case
from hsmpace.io_excel import ValidationError, read_case, write_case, write_results
from hsmpace.viz import (
    gantt_figure,
    gap_figure,
    monte_carlo_figure,
    pacing_curve_figure,
    space_time_figure,
)

PLOT_CONFIG = {
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "scale": 3, "filename": "hsmpace"},
}


@st.cache_data(show_spinner=False)
def _load_from_bytes(payload: bytes, name: str):
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        handle.write(payload)
        path = Path(handle.name)
    try:
        case = read_case(path)
    finally:
        path.unlink(missing_ok=True)
    return _prepare(case)


@st.cache_data(show_spinner=False)
def _load_example():
    return _prepare(example_case())


def _prepare(case: Case):
    harmonised, deviations = harmonise_tandem_speeds(case)
    base = base_results(harmonised)
    return harmonised, deviations, base


@st.cache_data(show_spinner=False)
def _template_bytes(with_data: bool) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        path = Path(handle.name)
    write_case(example_case(), path, include_data=with_data)
    payload = path.read_bytes()
    path.unlink(missing_ok=True)
    return payload


def _results_bytes(case, results, analyses, deviations, curve, min_pacing, mc) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        path = Path(handle.name)
    write_results(path, case, results, analyses, deviations, curve, min_pacing, mc)
    payload = path.read_bytes()
    path.unlink(missing_ok=True)
    return payload


def _events_csv(results: list[PieceResult]) -> str:
    buffer = io.StringIO()
    buffer.write("pezzo,t_s,evento,apparecchiatura,x_m,dettaglio\n")
    for res in results:
        for e in res.events:
            buffer.write(
                f"{res.piece_id},{e.t:.3f},{e.kind},{e.equipment_id},{e.x:.2f},\"{e.detail}\"\n"
            )
    return buffer.getvalue()


def main() -> None:
    st.set_page_config(page_title="HSM pacing", page_icon="~", layout="wide")
    st.title("Diagramma spazio-tempo e pacing di un Hot Strip Mill")

    with st.sidebar:
        st.header("Input")
        uploaded = st.file_uploader("Workbook di input (.xlsx)", type=["xlsx"])
        st.caption(
            "Senza file caricato viene usato l'impianto di esempio incluso, "
            "con dati inventati ma plausibili."
        )
        st.download_button(
            "Scarica il template vuoto",
            data=_template_bytes(False),
            file_name="hsm_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
        st.download_button(
            "Scarica l'esempio compilato",
            data=_template_bytes(True),
            file_name="hsm_esempio.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

    try:
        if uploaded is not None:
            case, deviations, base = _load_from_bytes(uploaded.getvalue(), uploaded.name)
            source = uploaded.name
        else:
            case, deviations, base = _load_example()
            source = "impianto di esempio"
    except ValidationError as exc:
        st.error("Il workbook non e' valido: correggere le celle indicate e ricaricare.")
        for issue in exc.issues:
            st.write(f"- **{issue.sheet}!{issue.cell}** {issue.message}" if issue.cell else f"- {issue.message}")
        st.stop()
    except Exception as exc:  # noqa: BLE001 - messaggio leggibile invece del traceback
        st.error(f"Errore nella lettura del file: {exc}")
        st.stop()

    with st.sidebar:
        st.header("Scenario")
        settings = case.settings
        pacing = st.slider(
            "Pacing [s]",
            min_value=float(settings.pacing_scan_min),
            max_value=float(settings.pacing_scan_max),
            value=float(settings.pacing),
            step=1.0,
            help="Cadenza con cui i pezzi entrano nel processo.",
        )
        gap_min = st.number_input(
            "Gap minimo richiesto [m]", min_value=0.0, value=float(settings.gap_min), step=1.0
        )
        n_pieces = st.slider(
            "Pezzi in sequenza", min_value=2, max_value=8, value=max(2, settings.n_pieces)
        )
        time_down = st.checkbox("Tempo crescente verso il basso", value=settings.time_axis_down)
        show_virtual = st.checkbox(
            "Mostra la testa virtuale",
            value=False,
            help="La testa non vincolata, che prosegue oltre l'avvolgitore e comanda "
            "il trigger dello zoom rolling.",
        )
        st.header("Robustezza")
        run_mc = st.checkbox("Calcola il Monte Carlo", value=False)
        mc_runs = st.number_input(
            "Run", min_value=50, max_value=20000, value=int(settings.mc_runs), step=50
        )

    case = replace(
        case,
        settings=replace(
            settings,
            pacing=pacing,
            gap_min=gap_min,
            n_pieces=n_pieces,
            piece_products=settings.piece_products[:n_pieces] if settings.piece_products else (),
            mc_runs=int(mc_runs),
            time_axis_down=time_down,
        ),
    )

    results = sequence(case, base, pacing)
    analyses = analyse_sequence(results, gap_min, case.line)
    worst = min(analyses, key=lambda a: a.min_gap) if analyses else None

    with st.spinner("Scansione del pacing..."):
        curve = gap_vs_pacing(case, base)
        min_pacing = min_feasible_pacing(case, base, curve)

    mc = None
    if run_mc:
        with st.spinner(f"Monte Carlo su {int(mc_runs)} run..."):
            mc = monte_carlo(case, pacing=pacing, runs=int(mc_runs))

    cols = st.columns(4)
    cols[0].metric("Gap minimo", f"{worst.min_gap:.1f} m" if worst else "nessuna interazione")
    cols[1].metric(
        "Esito",
        "ammissibile" if (worst is None or worst.ok) else "violazione",
        delta=None if worst is None else f"{worst.min_gap - gap_min:+.1f} m di margine",
        delta_color="normal" if (worst is None or worst.ok) else "inverse",
    )
    cols[2].metric(
        "Pacing minimo ammissibile",
        f"{min_pacing.pacing:.0f} s" if min_pacing else "non trovato",
    )
    cols[3].metric(
        "Margine sul pacing",
        f"{pacing - min_pacing.pacing:+.0f} s" if min_pacing else "-",
    )

    if worst and worst.critical:
        where = worst.critical.section or "linea"
        near = f", vicino a {worst.critical.equipment}" if worst.critical.equipment else ""
        st.caption(
            f"Fonte: {source}. Punto critico fra {worst.front_id} e {worst.rear_id} a "
            f"x = {worst.critical.x:.1f} m ({where}{near}) all'istante {worst.critical.t:.1f} s"
            + (f", pari a {worst.headway:.1f} s di distanza temporale." if worst.headway else ".")
        )

    tabs = st.tabs(
        ["Diagramma", "Gap", "Pacing", "Occupazione", "Eventi", "Dati e controlli", "Misure"]
    )

    with tabs[0]:
        st.plotly_chart(
            space_time_figure(case, results, analyses, time_down, show_virtual_head=show_virtual),
            width="stretch",
            config=PLOT_CONFIG,
        )
        st.caption(
            "Ogni pezzo e' la banda fra testa e coda. La banda si allarga dove il pezzo "
            "viene laminato e si stringe quando la testa e' presa dall'avvolgitore. "
            "Per esportare l'immagine usare l'icona della macchina fotografica: il PNG "
            "esce a tripla risoluzione."
        )

    with tabs[1]:
        st.plotly_chart(
            gap_figure(analyses, gap_min), width="stretch", config=PLOT_CONFIG
        )
        if analyses:
            st.dataframe(
                [
                    {
                        "coppia": f"{a.front_id} / {a.rear_id}",
                        "gap minimo [m]": round(a.min_gap, 2),
                        "t [s]": round(a.critical.t, 1) if a.critical else None,
                        "x [m]": round(a.critical.x, 1) if a.critical else None,
                        "sezione": a.critical.section if a.critical else "",
                        "gap temporale [s]": round(a.headway, 1) if a.headway else None,
                        "esito": "ok" if a.ok else "violazione",
                    }
                    for a in analyses
                ],
                width="stretch",
                hide_index=True,
            )

    with tabs[2]:
        st.plotly_chart(
            pacing_curve_figure(curve, gap_min, pacing, min_pacing),
            width="stretch",
            config=PLOT_CONFIG,
        )
        st.caption(
            "Il pacing minimo si legge dove la curva incrocia la soglia. La distanza "
            "verticale dalla soglia e' il margine con cui si sta lavorando."
        )
        if mc is not None:
            st.plotly_chart(
                monte_carlo_figure(mc, gap_min), width="stretch", config=PLOT_CONFIG
            )
            st.write(
                f"Su {mc.runs} run con velocita' entro "
                f"{case.settings.mc_speed_tol_pct:g}% e tempi morti dispersi di "
                f"{case.settings.mc_delay_sigma:g} s: **{mc.violations} violazioni** "
                f"({100 * mc.violation_rate:.1f}%), gap medio {mc.mean:.1f} m, "
                f"quinto percentile {mc.percentile(0.05):.1f} m."
            )
        else:
            st.info("Attivare il Monte Carlo nella barra laterale per la stima di robustezza.")

    with tabs[3]:
        st.plotly_chart(
            gantt_figure(case, results), width="stretch", config=PLOT_CONFIG
        )

    with tabs[4]:
        piece_ids = [r.piece_id for r in results]
        selected = st.selectbox("Pezzo", piece_ids)
        chosen = next(r for r in results if r.piece_id == selected)
        st.dataframe(
            [
                {
                    "t [s]": round(e.t, 2),
                    "evento": e.kind,
                    "apparecchiatura": e.equipment_id,
                    "x [m]": round(e.x, 1),
                    "dettaglio": e.detail,
                }
                for e in chosen.events
            ],
            width="stretch",
            hide_index=True,
            height=460,
        )
        st.download_button(
            "Scarica gli eventi in CSV",
            data=_events_csv(results),
            file_name="eventi.csv",
            mime="text/csv",
        )

    with tabs[5]:
        st.subheader("Bilancio di massa")
        st.dataframe(
            [
                {
                    "prodotto": c.piece_id,
                    "lunghezza cinematica [m]": round(c.length_kinematic, 2),
                    "lunghezza geometrica [m]": round(c.length_geometric, 2),
                    "scarto [%]": round(c.error_pct, 4),
                    "esito": "ok" if c.ok else "attenzione",
                }
                for c in mass_balance(results)
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Le due lunghezze coincidono per costruzione: uno scarto segnala un errore "
            "nell'input o nel modello."
        )

        st.subheader("Velocita' del tandem ricalcolate dalla gabbia master")
        if deviations:
            st.dataframe(
                [
                    {
                        "prodotto": d.product_id,
                        "passata": d.pass_no,
                        "gabbia": d.equipment_id,
                        "v inserita [m/s]": round(d.v_input, 3),
                        "v da bilancio [m/s]": round(d.v_massflow, 3),
                        "scarto [%]": round(d.deviation_pct, 2),
                    }
                    for d in deviations
                ],
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Nel tandem il nastro fra due gabbie ha lunghezza fissa, quindi il bilancio "
                "di massa e' un vincolo fisico e non una verifica: le velocita' vengono "
                "ricalcolate dalla master e qui si vede quanto si discostano da quelle inserite."
            )
        else:
            st.success("Le velocita' inserite nel tandem sono gia' coerenti con il bilancio di massa.")

        for res in results[:1]:
            if res.warnings:
                for warning in res.warnings:
                    st.warning(warning)

        st.subheader("Esporta")
        st.download_button(
            "Scarica i risultati in Excel",
            data=_results_bytes(case, results, analyses, deviations, curve, min_pacing, mc),
            file_name="hsmpace_risultati.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tabs[6]:
        st.subheader("Confronto con il tracking reale")
        st.write(
            "Formato CSV: `piece_id,time_s,head_m,tail_m` con `tail_m` facoltativa e "
            "posizioni riferite alla stessa origine del layout."
        )
        measured = st.file_uploader("Tracking misurato (.csv)", type=["csv"], key="tracking")
        if measured is not None:
            try:
                series = parse_tracking(measured.getvalue().decode("utf-8-sig").splitlines())
            except ValueError as exc:
                st.error(str(exc))
            else:
                offset = st.number_input(
                    "Sfasamento temporale da applicare alle misure [s]", value=0.0, step=1.0
                )
                shifted = [s.shift(offset) for s in series]
                st.plotly_chart(
                    space_time_figure(case, results, analyses, time_down, tracking=shifted),
                    width="stretch",
                    config=PLOT_CONFIG,
                )
        else:
            st.info(
                "Nessun file caricato. Il confronto simulato contro misurato e' il modo piu' "
                "rapido per far accettare in reparto i numeri che escono dal tool."
            )


if __name__ == "__main__":
    main()
