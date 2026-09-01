"""Domain model: layout, sections, speed events, pass schedule.

Internal units, fixed and not negotiable in the core:

* positions and lengths in metres
* thicknesses and widths in millimetres
* speeds in m/s, accelerations in m/s2, times in seconds
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
    """Inconsistency in the model that prevents the simulation from running."""


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
    """Commanded speed change, anchored to a position along the line.

    It fires when the extremity leading in the current direction of travel
    crosses ``x_trigger`` moving in direction ``direction``. If it fires while a
    pass is engaged and ``during_pass`` is false, it is deferred to the moment
    the piece is free again: while rolling it is the mill that commands, not the
    roller table.
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
    """When non zero the event is relative: it multiplies the commanded speed
    instead of replacing it. Used by zoom rolling, which is defined in per cent."""


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
    reversing_clearance: float = 0.0
    """Distance between the stand and the closest extremity of the piece when it
    comes to rest to reverse, ahead of this pass. With zero the piece stops as
    soon as the deceleration allows, that is at `v^2/(2a)` from the stand."""
    approach_v: float | None = None
    master: bool = False
    zoom_pct: float = 0.0
    zoom_trigger: float = 0.0
    zoom_accel: float | None = None
    v_exit_input: float | None = None

    @property
    def elongation(self) -> float:
        """lambda = (h_in * w_in) / (h_out * w_out): elongation ratio."""
        return (self.h_in * self.w_in) / (self.h_out * self.w_out)

    @property
    def v_entry(self) -> float:
        return self.v_exit / self.elongation

    @property
    def mass_flux(self) -> float:
        """Specific mass flow at exit, mm2*m/s."""
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
        """Geometric final length, by volume conservation."""
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
            raise ModelError(f"unknown equipment: {equipment_id!r}") from exc

    @property
    def start(self) -> Equipment:
        for e in self.equipment:
            if e.kind == KIND_START:
                return e
        raise ModelError("no equipment of kind 'start' in the layout")

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
    """Complete case: line, products and simulation settings."""

    line: Line
    products: tuple[Product, ...]
    settings: SimSettings = field(default_factory=SimSettings)
    info: dict[str, str] = field(default_factory=dict)

    def product(self, product_id: str) -> Product:
        for p in self.products:
            if p.id == product_id:
                return p
        raise ModelError(f"unknown product: {product_id!r}")

    @property
    def piece_products(self) -> tuple[str, ...]:
        seq = self.settings.piece_products
        if seq:
            return seq
        if not self.products:
            raise ModelError("no product defined")
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
    """Enforce the mass flow balance in tandem groups from the master stand.

    In a tandem mill the strip between two stands has a fixed length, so the
    mass flow balance is not a check but a physical constraint: inconsistent
    input speeds would describe an impossible motion. Group speeds are therefore
    recomputed from the master and the deviations reported.
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
                    f"product {product.id}: more than one master stand in group {group!r}"
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
    """Model inconsistency, with a locator that the Excel layer translates into
    the originating cell."""

    locator: str
    message: str

    def __str__(self) -> str:
        return self.message


def validate_case(case: Case) -> list[Problem]:
    """Consistency checks that do not depend on the simulation."""
    problems: list[Problem] = []

    def add(locator: str, message: str) -> None:
        problems.append(Problem(locator, message))

    line = case.line
    if not line.equipment:
        add("", "empty layout")
        return problems

    try:
        line.start
    except ModelError as exc:
        add("", str(exc))

    ids = [e.id for e in line.equipment]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        add(f"equipment:{dup}", f"duplicated equipment identifier: {dup!r}")

    for e in line.equipment:
        if e.kind not in EQUIPMENT_KINDS:
            add(f"equipment:{e.id}", f"{e.id}: kind {e.kind!r} is not valid")
        if e.accel <= 0.0:
            add(f"equipment:{e.id}", f"{e.id}: acceleration must be positive")

    for s in line.sections:
        if s.length <= 0.0:
            add(f"section:{s.id}", f"section {s.id}: length must be positive")
        for ev in s.events:
            if ev.v_target < 0.0:
                add(
                    f"section:{s.id}",
                    f"section {s.id}: negative speed not allowed, the direction comes "
                    "from the pass",
                )
            if not s.contains(ev.x_trigger):
                add(
                    f"section:{s.id}",
                    f"section {s.id}: event at x={ev.x_trigger:.2f} m outside the section "
                    f"[{s.x_start:.2f}, {s.x_end:.2f}]",
                )

    if not case.products:
        add("", "no product defined")

    for product in case.products:
        tag = f"product:{product.id}"
        if product.slab_len <= 0 or product.slab_thk <= 0 or product.slab_wid <= 0:
            add(tag, f"product {product.id}: invalid slab dimensions")
        if not product.passes:
            add(tag, f"product {product.id}: no pass defined")
            continue

        if product.passes[0].direction != FWD:
            add(
                f"pass:{product.id}:{product.passes[0].pass_no}",
                f"product {product.id}: the first pass must be in direction 'fwd', "
                "the piece leaves the furnace moving forward",
            )
        if product.passes[-1].direction != FWD:
            add(
                f"pass:{product.id}:{product.passes[-1].pass_no}",
                f"product {product.id}: the last pass must be in direction 'fwd', "
                "otherwise the piece keeps moving backwards and never reaches the coiler",
            )

        h_prev = product.slab_thk
        w_prev = product.slab_wid
        prev: RollingPass | None = None
        for rp in product.passes:
            ptag = f"pass:{product.id}:{rp.pass_no}"
            head = f"product {product.id} pass {rp.pass_no}"
            try:
                eq = line.get(rp.equipment_id)
            except ModelError as exc:
                add(ptag, f"{head}: {exc}")
                eq = None
            if eq is not None and eq.kind != KIND_STAND:
                add(ptag, f"{head}: {eq.id} is not a stand")
            if rp.h_out <= 0 or rp.h_out > rp.h_in:
                add(ptag, f"{head}: invalid reduction ({rp.h_in} -> {rp.h_out} mm)")
            if abs(rp.h_in - h_prev) > 1e-6:
                add(
                    ptag,
                    f"{head}: h_in {rp.h_in} mm does not match the exit thickness of the "
                    f"previous pass ({h_prev} mm)",
                )
            if abs(rp.w_in - w_prev) > 1e-6:
                add(
                    ptag,
                    f"{head}: w_in {rp.w_in} mm does not match the previous width "
                    f"({w_prev} mm)",
                )
            if rp.v_exit <= 0:
                add(ptag, f"{head}: speed is not positive")
            if rp.reversing_clearance < 0:
                add(ptag, f"{head}: the reversing clearance cannot be negative")
            if (
                prev is not None
                and prev.equipment_id == rp.equipment_id
                and prev.direction == rp.direction
            ):
                add(
                    ptag,
                    f"{head}: two consecutive passes on {rp.equipment_id} in the same direction",
                )
            h_prev, w_prev = rp.h_out, rp.w_out
            prev = rp

    for pid in case.piece_products:
        if all(p.id != pid for p in case.products):
            add("setting:piece_products", f"piece sequence: unknown product {pid!r}")

    if case.settings.pacing <= 0:
        add("setting:pacing_s", "pacing must be positive")
    if case.settings.gap_min < 0:
        add("setting:gap_min_m", "the minimum gap cannot be negative")
    if case.settings.n_pieces < 1 and not case.settings.piece_products:
        add("setting:n_pieces", "at least one piece is required")

    return problems
