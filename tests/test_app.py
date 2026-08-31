"""Verifica che l'applicazione web parta e renderizzi senza eccezioni.

`streamlit run` esegue il file come script autonomo, senza contesto di package:
in quella modalita' un import relativo fallisce con "attempted relative import
with no known parent package" e l'errore **non si vede interrogando la porta**,
perche' il server risponde comunque 200 e il messaggio compare solo nel browser.
Questi test riproducono la stessa modalita' di avvio.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import hsmpace

SCRIPT = Path(hsmpace.__file__).parent / "app" / "streamlit_app.py"


@pytest.fixture(scope="module")
def app() -> AppTest:
    at = AppTest.from_file(str(SCRIPT), default_timeout=180)
    at.run()
    return at


def test_l_app_parte_senza_eccezioni(app: AppTest):
    assert not app.exception, [e.value for e in app.exception]


def test_le_metriche_di_sintesi_sono_presenti(app: AppTest):
    etichette = {m.label for m in app.metric}
    assert {
        "Gap minimo",
        "Esito",
        "Pacing minimo ammissibile",
        "Margine sul pacing",
    } <= etichette


def test_i_grafici_principali_sono_disegnati(app: AppTest):
    # diagramma spazio-tempo, gap, curva del pacing e Gantt
    assert len(app.get("plotly_chart")) >= 4


def test_il_pacing_stretto_produce_una_violazione():
    at = AppTest.from_file(str(SCRIPT), default_timeout=180)
    at.run()
    at.sidebar.slider[0].set_value(95.0).run()
    assert not at.exception, [e.value for e in at.exception]
    esito = next(m for m in at.metric if m.label == "Esito")
    assert esito.value == "violazione"
