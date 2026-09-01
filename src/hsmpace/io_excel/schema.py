"""Schema del workbook di input: nomi dei fogli, colonne e unita'.

Le unita' sono fissate qui e non sono negoziabili nel file: non esiste una
colonna unita' da compilare. Un template rigido e' molto piu' robusto quando il
file passa di mano fra piu' persone.
"""

from __future__ import annotations

SCHEMA_VERSION = "1"

SHEET_INFO = "Info"
SHEET_LAYOUT = "Layout"
SHEET_SECTIONS = "Sections"
SHEET_PRODUCTS = "Products"
SHEET_PASSES = "PassSchedule"
SHEET_SIM = "Simulation"
SHEET_GUIDE = "Guida"

MAX_EVENTS_PER_SECTION = 7

LAYOUT_COLUMNS = [
    ("equipment_id", "Identificativo univoco (R1, F7, DC1)"),
    ("kind", "start | stand | coiler | marker"),
    ("x_m", "Posizione assoluta lungo la linea, in metri"),
    ("accel_mps2", "Accelerazione = decelerazione dell'asse, m/s2"),
    ("group", "Gruppo tandem, es. FM per le gabbie finitrici"),
    ("label", "Descrizione mostrata sui grafici"),
]

SECTION_COLUMNS = [
    ("section_id", "Identificativo univoco della sezione"),
    ("label", "Descrizione mostrata sui grafici"),
    ("start_ref", "Apparecchiatura di riferimento, 'prev' o vuoto per assoluto"),
    ("start_offset_m", "Distanza dal riferimento all'inizio della sezione, m"),
    ("length_m", "Lunghezza della sezione, m"),
    ("direction", "fwd | rev: verso di moto in cui gli eventi sono validi"),
    ("during_pass", "SI se l'evento vale anche in laminazione, NO per differirlo"),
]

SECTION_EVENT_COLUMNS = [
    ("d{}_m", "Distanza dall'inizio sezione del cambio di velocita' {}, m"),
    ("v{}_mps", "Nuova velocita' comandata {}, m/s"),
    ("a{}_mps2", "Accelerazione del cambio {}, m/s2 (vuoto = quella dell'asse)"),
]

PRODUCT_COLUMNS = [
    ("product_id", "Identificativo univoco del prodotto"),
    ("label", "Descrizione"),
    ("grade", "Qualita' acciaio"),
    ("slab_thk_mm", "Spessore bramma, mm"),
    ("slab_wid_mm", "Larghezza bramma, mm"),
    ("slab_len_m", "Lunghezza bramma, m"),
]

PASS_COLUMNS = [
    ("product_id", "Prodotto a cui appartiene la passata"),
    ("pass_no", "Numero d'ordine della passata"),
    ("equipment_id", "Gabbia su cui avviene la passata"),
    ("direction", "fwd | rev"),
    ("h_in_mm", "Spessore in ingresso, mm"),
    ("h_out_mm", "Spessore in uscita, mm"),
    ("w_in_mm", "Larghezza in ingresso, mm"),
    ("w_out_mm", "Larghezza in uscita, mm"),
    ("v_exit_mps", "Velocita' del materiale in uscita gabbia, m/s"),
    ("reversing_delay_s", "Tempo morto prima di questa passata se cambia il verso, s"),
    ("reversing_clearance_m", "Distanza fra gabbia ed estremita' piu' vicina alla fermata "
     "per invertire, m (vuoto = minima distanza di frenata)"),
    ("approach_v_mps", "Velocita' di avvicinamento dopo l'inversione (vuoto = v_ingresso)"),
    ("master", "SI sulla gabbia che detta il bilancio di massa del gruppo tandem"),
    ("zoom_pct", "Zoom rolling: incremento di velocita' in %"),
    ("zoom_trigger_m", "Zoom: avanzamento della testa virtuale oltre questa gabbia, m"),
    ("zoom_accel_mps2", "Zoom: accelerazione, m/s2 (vuoto = quella dell'asse)"),
]

# colonne introdotte dopo la prima versione dello schema: la loro assenza non
# invalida un workbook gia' in circolazione
OPTIONAL_COLUMNS = {"reversing_clearance_m"}

SIM_KEYS = [
    ("pacing_s", 170.0, "Cadenza nominale fra un pezzo e il successivo, s"),
    ("n_pieces", 3, "Numero di pezzi simulati"),
    ("piece_products", "", "Sequenza prodotti separata da virgole (vuoto = ripete il primo)"),
    ("gap_min_m", 5.0, "Distanza minima ammessa fra coda e testa successiva, m"),
    ("pacing_scan_min_s", 90.0, "Estremo inferiore della scansione del pacing, s"),
    ("pacing_scan_max_s", 300.0, "Estremo superiore della scansione del pacing, s"),
    ("pacing_scan_steps", 106, "Numero di punti della scansione"),
    ("mc_runs", 600, "Numero di run Monte Carlo per la robustezza"),
    ("mc_speed_tol_pct", 2.0, "Tolleranza sulle velocita' di passata, +/- %"),
    ("mc_delay_sigma_s", 1.0, "Deviazione standard sui tempi morti, s"),
    ("mc_release_sigma_s", 2.0, "Deviazione standard sull'istante di rilascio, s"),
    ("mc_seed", 20260831, "Seme del generatore casuale, per risultati riproducibili"),
    ("max_time_s", 1800.0, "Tempo massimo di simulazione di un pezzo, s"),
    ("time_axis_down", "SI", "SI per tempo crescente verso il basso nel diagramma"),
]

GUIDE_TEXT = [
    ("Come e' fatto il modello", True),
    ("", False),
    (
        "La testa comanda, la coda si deduce. Si descrivono i cambi di velocita' "
        "dell'estremita' che guida nel verso corrente; la velocita' dell'altra "
        "estremita' discende dal bilancio di massa delle gabbie ingaggiate:",
        False,
    ),
    ("    v_trascinata = v_guida / prodotto dei lambda,   lambda = (h_in*w_in)/(h_out*w_out)", False),
    ("", False),
    ("Unita' fissate nel file, nessuna colonna unita' da compilare:", True),
    ("    posizioni e lunghezze in m, spessori e larghezze in mm,", False),
    ("    velocita' in m/s, tempi in s, accelerazioni in m/s2.", False),
    ("", False),
    ("Sezioni ed eventi di velocita'", True),
    (
        "Le vie a rulli non hanno un setpoint proprio: la linea e' divisa in sezioni "
        "definite da chi compila, anche piu' corte dell'interasse fra due gabbie. "
        "Ogni sezione ammette fino a 7 cambi di velocita', dati come distanza "
        "dall'inizio della sezione piu' velocita' obiettivo.",
        False,
    ),
    (
        "Un evento che scatta mentre una passata e' ingaggiata viene differito al "
        "disingaggio, perche' in laminazione comanda il mill e non la via a rulli. "
        "Mettere SI in during_pass per farlo valere comunque.",
        False,
    ),
    ("", False),
    ("Sbozzatura reversibile", True),
    (
        "Dopo il tail-out il pezzo prosegue fino a portare l'estremita' piu' vicina "
        "alla gabbia a reversing_clearance_m metri da essa, dove si ferma, attende il "
        "reversing delay della passata successiva e riparte nel verso opposto. Il "
        "reversing delay deve gia' comprendere screwdown e centraggio sideguides, e la "
        "quota di sgombero va misurata dalla gabbia, quindi va aumentata se il vincolo "
        "vero e' l'edger che sta qualche metro prima.",
        False,
    ),
    (
        "Lasciando vuota la quota di sgombero il pezzo si ferma appena la "
        "decelerazione lo consente, cioe' a v^2/(2a) dalla gabbia. Se la quota "
        "richiesta e' piu' corta di quella distanza il tool lo segnala invece di "
        "fingere una frenata impossibile.",
        False,
    ),
    ("", False),
    ("Zoom rolling", True),
    (
        "Definito come incremento percentuale di velocita' che parte quando la testa "
        "ha superato di zoom_trigger_m la gabbia indicata. Il trigger usa la testa "
        "virtuale, cioe' ignora il fatto che la testa si ferma all'avvolgitore: se il "
        "trigger cade oltre l'avvolgitore lo zoom parte dopo qualche avvolgimento, "
        "come nel modello offline.",
        False,
    ),
    ("", False),
    ("Cosa il modello non fa", True),
    (
        "Nessun interblocco e nessun hold point: i pezzi seguono i profili nominali "
        "e il tool riporta dove il gap scende sotto soglia, senza fermare il pezzo "
        "che segue. Slittamento sui rulli trascurato, jerk infinito, nessun modello "
        "termico, nessun vincolo di forno o di ciclo avvolgitore.",
        False,
    ),
]
