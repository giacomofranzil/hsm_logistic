"""Modello di dominio: layout, sezioni, eventi di velocita', pass schedule.

Unita' interne, fissate e non negoziabili nel core:

* posizioni e lunghezze in metri
* spessori e larghezze in millimetri
* velocita' in m/s, accelerazioni in m/s2, tempi in secondi
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

FWD = 1
REV = -1

KIND_START = "start"
KIND_STAND = "stand"
KIND_COILER = "coiler"
KIND_MARKER = "marker"
EQUIPMENT_KINDS = (KIND_START, KIND_STAND, KIND_COILER, KIND_MARKER)


class ModelError(ValueError):
    """Incoerenza nel modello che impedisce la simulazione."""


@dataclass(frozen=True)
class Equipment:
    id: str
    kind: str
    x: float
    accel: float = 1.0
    group: str = ""
    label: str = ""

    @property
    def display(self) -> str:
        return self.label or self.id


@dataclass(frozen=True)
class SpeedEvent:
    """Cambio di velocita' comandato, ancorato a una posizione della linea.

    Scatta quando l'estremita' che guida nel verso corrente attraversa
    ``x_trigger`` muovendosi nel verso ``direction``. Se scatta mentre una
    passata e' ingaggiata e ``during_pass`` e' falso, viene differito al
    momento in cui il pezzo torna libero: in laminazione comanda il mill, non
    la via a rulli.
    """

    id: str
    section_id: str
    x_trigger: float
    v_target: float = 0.0
    accel: float | None = None
    direction: int = FWD
    during_pass: bool = False
    origin: str = "section"
    rel_pct: float = 0.0
    """Se diverso da zero l'evento e' relativo: moltiplica la velocita' comandata
    invece di sostituirla. Usato dallo zoom rolling, che e' definito in %."""


@dataclass(frozen=True)
class Section:
    id: str
    x_start: float
    length: float
    label: str = ""
    events: tuple[SpeedEvent, ...] = ()

    @property
    def x_end(self) -> float:
        return self.x_start + self.length

    @property
    def display(self) -> str:
        return self.label or self.id

    def contains(self, x: float) -> bool:
        return self.x_start - 1e-9 <= x <= self.x_end + 1e-9


@dataclass(frozen=True)
class RollingPass:
    product_id: str
    pass_no: int
    equipment_id: str
    direction: int
    h_in: float
    h_out: float
    w_in: float
    w_out: float
    v_exit: float
    reversing_delay: float = 0.0
    approach_v: float | None = None
    master: bool = False
    zoom_pct: float = 0.0
    zoom_trigger: float = 0.0
    zoom_accel: float | None = None
    v_exit_input: float | None = None

    @property
    def elongation(self) -> float:
        """lambda = (h_in * w_in) / (h_out * w_out): rapporto di allungamento."""
        return (self.h_in * self.w_in) / (self.h_out * self.w_out)

    @property
    def v_entry(self) -> float:
        return self.v_exit / self.elongation

    @property
    def mass_flux(self) -> float:
        """Flusso di massa specifico in uscita, mm2*m/s."""
        return self.v_exit * self.h_out * self.w_out


@dataclass(frozen=True)
class Product:
    id: str
    slab_thk: float
    slab_wid: float
    slab_len: float
    label: str = ""
    grade: str = ""
    passes: tuple[RollingPass, ...] = ()

    @property
    def display(self) -> str:
        return self.label or self.id

    @property
    def final_length(self) -> float:
        """Lunghezza finale geometrica, per conservazione del volume."""
        if not self.passes:
            return self.slab_len
        last = self.passes[-1]
        return self.slab_len * (self.slab_thk * self.slab_wid) / (last.h_out * last.w_out)


@dataclass(frozen=True)
class SimSettings:
    pacing: float = 180.0
    n_pieces: int = 3
    piece_products: tuple[str, ...] = ()
    gap_min: float = 5.0
    pacing_scan_min: float = 60.0
    pacing_scan_max: float = 360.0
    pacing_scan_steps: int = 121
    mc_runs: int = 1000
    mc_speed_tol_pct: float = 2.0
    mc_delay_sigma: float = 1.0
    mc_release_sigma: float = 2.0
    mc_seed: int = 20260831
    max_time: float = 1800.0
    time_axis_down: bool = True


@dataclass(frozen=True)
class Line:
    equipment: tuple[Equipment, ...]
    sections: tuple[Section, ...]

    _by_id: dict[str, Equipment] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_id", {e.id: e for e in self.equipment})

    def get(self, equipment_id: str) -> Equipment:
        try:
            return self._by_id[equipment_id]
        except KeyError as exc:
            raise ModelError(f"apparecchiatura sconosciuta: {equipment_id!r}") from exc

    @property
    def start(self) -> Equipment:
        for e in self.equipment:
            if e.kind == KIND_START:
                return e
        raise ModelError("nessuna apparecchiatura di tipo 'start' nel layout")

    @property
    def coilers(self) -> tuple[Equipment, ...]:
        return tuple(e for e in self.equipment if e.kind == KIND_COILER)

    @property
    def x_min(self) -> float:
        return min(e.x for e in self.equipment)

    @property
    def x_max(self) -> float:
        return max(e.x for e in self.equipment)

    def section_at(self, x: float) -> Section | None:
        for s in self.sections:
            if s.contains(x):
                return s
        return None

    def all_events(self) -> tuple[SpeedEvent, ...]:
        out: list[SpeedEvent] = []
        for s in self.sections:
            out.extend(s.events)
        return tuple(out)


@dataclass(frozen=True)
class Case:
    """Caso completo: linea, prodotti e impostazioni di simulazione."""

    line: Line
    products: tuple[Product, ...]
    settings: SimSettings = field(default_factory=SimSettings)
    info: dict[str, str] = field(default_factory=dict)

    def product(self, product_id: str) -> Product:
        for p in self.products:
            if p.id == product_id:
                return p
        raise ModelError(f"prodotto sconosciuto: {product_id!r}")

    @property
    def piece_products(self) -> tuple[str, ...]:
        seq = self.settings.piece_products
        if seq:
            return seq
        if not self.products:
            raise ModelError("nessun prodotto definito")
        return tuple([self.products[0].id] * self.settings.n_pieces)


@dataclass(frozen=True)
class MassFlowDeviation:
    product_id: str
    pass_no: int
    equipment_id: str
    v_input: float
    v_massflow: float

    @property
    def deviation_pct(self) -> float:
        if self.v_input == 0.0:
            return 0.0
        return 100.0 * (self.v_input - self.v_massflow) / self.v_input


def harmonise_tandem_speeds(
    case: Case,
) -> tuple[Case, tuple[MassFlowDeviation, ...]]:
    """Impone il bilancio di massa nei gruppi tandem a partire dalla gabbia master.

    Nel tandem il nastro fra due gabbie ha lunghezza fissa, quindi il bilancio
    di massa non e' una verifica ma un vincolo fisico: velocita' inserite
    incoerenti descriverebbero un moto impossibile. Le velocita' del gruppo
    vengono percio' ricalcolate dalla master e gli scostamenti riportati.
    """
    deviations: list[MassFlowDeviation] = []
    new_products: list[Product] = []

    for product in case.products:
        groups: dict[str, list[int]] = {}
        for idx, rp in enumerate(product.passes):
            group = case.line.get(rp.equipment_id).group
            if group:
                groups.setdefault(group, []).append(idx)

        passes = list(product.passes)
        for group, indices in groups.items():
            masters = [i for i in indices if passes[i].master]
            if not masters:
                continue
            if len(masters) > 1:
                raise ModelError(
                    f"prodotto {product.id}: piu' di una gabbia master nel gruppo {group!r}"
                )
            master = passes[masters[0]]
            flux = master.mass_flux
            for i in indices:
                rp = passes[i]
                v_mf = flux / (rp.h_out * rp.w_out)
                if abs(v_mf - rp.v_exit) > 1e-9:
                    deviations.append(
                        MassFlowDeviation(product.id, rp.pass_no, rp.equipment_id, rp.v_exit, v_mf)
                    )
                passes[i] = replace(rp, v_exit=v_mf, v_exit_input=rp.v_exit)

        new_products.append(replace(product, passes=tuple(passes)))

    return replace(case, products=tuple(new_products)), tuple(deviations)


@dataclass(frozen=True)
class Problem:
    """Incoerenza del modello, con un localizzatore che il layer Excel
    traduce nella cella di origine."""

    locator: str
    message: str

    def __str__(self) -> str:
        return self.message


def validate_case(case: Case) -> list[Problem]:
    """Controlli di coerenza che non dipendono dalla simulazione."""
    problems: list[Problem] = []

    def add(locator: str, message: str) -> None:
        problems.append(Problem(locator, message))

    line = case.line
    if not line.equipment:
        add("", "layout vuoto")
        return problems

    try:
        line.start
    except ModelError as exc:
        add("", str(exc))

    ids = [e.id for e in line.equipment]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        add(f"equipment:{dup}", f"identificativo apparecchiatura duplicato: {dup!r}")

    for e in line.equipment:
        if e.kind not in EQUIPMENT_KINDS:
            add(f"equipment:{e.id}", f"{e.id}: tipo {e.kind!r} non valido")
        if e.accel <= 0.0:
            add(f"equipment:{e.id}", f"{e.id}: accelerazione deve essere positiva")

    for s in line.sections:
        if s.length <= 0.0:
            add(f"section:{s.id}", f"sezione {s.id}: lunghezza deve essere positiva")
        for ev in s.events:
            if ev.v_target < 0.0:
                add(
                    f"section:{s.id}",
                    f"sezione {s.id}: velocita' negativa non ammessa, il verso lo da' la passata",
                )
            if not s.contains(ev.x_trigger):
                add(
                    f"section:{s.id}",
                    f"sezione {s.id}: evento a x={ev.x_trigger:.2f} m fuori dalla sezione "
                    f"[{s.x_start:.2f}, {s.x_end:.2f}]",
                )

    if not case.products:
        add("", "nessun prodotto definito")

    for product in case.products:
        tag = f"product:{product.id}"
        if product.slab_len <= 0 or product.slab_thk <= 0 or product.slab_wid <= 0:
            add(tag, f"prodotto {product.id}: dimensioni bramma non valide")
        if not product.passes:
            add(tag, f"prodotto {product.id}: nessuna passata definita")
            continue

        if product.passes[0].direction != FWD:
            add(
                f"pass:{product.id}:{product.passes[0].pass_no}",
                f"prodotto {product.id}: la prima passata deve essere in verso 'fwd', "
                "il pezzo lascia il forno andando avanti",
            )

        h_prev = product.slab_thk
        w_prev = product.slab_wid
        prev: RollingPass | None = None
        for rp in product.passes:
            ptag = f"pass:{product.id}:{rp.pass_no}"
            head = f"prodotto {product.id} passata {rp.pass_no}"
            try:
                eq = line.get(rp.equipment_id)
            except ModelError as exc:
                add(ptag, f"{head}: {exc}")
                eq = None
            if eq is not None and eq.kind != KIND_STAND:
                add(ptag, f"{head}: {eq.id} non e' una gabbia")
            if rp.h_out <= 0 or rp.h_out > rp.h_in:
                add(ptag, f"{head}: riduzione non valida ({rp.h_in} -> {rp.h_out} mm)")
            if abs(rp.h_in - h_prev) > 1e-6:
                add(
                    ptag,
                    f"{head}: h_in {rp.h_in} mm non coincide con lo spessore in uscita "
                    f"dalla passata precedente ({h_prev} mm)",
                )
            if abs(rp.w_in - w_prev) > 1e-6:
                add(
                    ptag,
                    f"{head}: w_in {rp.w_in} mm non coincide con la larghezza precedente "
                    f"({w_prev} mm)",
                )
            if rp.v_exit <= 0:
                add(ptag, f"{head}: velocita' non positiva")
            if (
                prev is not None
                and prev.equipment_id == rp.equipment_id
                and prev.direction == rp.direction
            ):
                add(
                    ptag,
                    f"{head}: due passate consecutive su {rp.equipment_id} nello stesso verso",
                )
            h_prev, w_prev = rp.h_out, rp.w_out
            prev = rp

    for pid in case.piece_products:
        if all(p.id != pid for p in case.products):
            add("setting:piece_products", f"sequenza pezzi: prodotto sconosciuto {pid!r}")

    if case.settings.pacing <= 0:
        add("setting:pacing_s", "pacing deve essere positivo")
    if case.settings.gap_min < 0:
        add("setting:gap_min_m", "gap minimo non puo' essere negativo")
    if case.settings.n_pieces < 1 and not case.settings.piece_products:
        add("setting:n_pieces", "serve almeno un pezzo")

    return problems
