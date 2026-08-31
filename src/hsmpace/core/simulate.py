"""Simulatore a eventi del moto di un pezzo lungo la linea.

Principio: **la testa comanda, la coda si deduce**.

L'utente descrive la velocita' dell'estremita' che guida nel verso corrente
(la testa materiale nelle passate dirette, la coda in quelle inverse). La
velocita' dell'altra estremita' discende dal bilancio di massa delle gabbie
ingaggiate fra le due:

    v_trascinata = v_guida / prod(lambda_i),  lambda_i = (h_in*w_in)/(h_out*w_out)

Discontinuita' ai cambi di ingaggio, entrambe fisicamente corrette:

* al **bite** e' l'estremita' trascinata a restare continua (il corpo del bar
  ha massa e non puo' cambiare velocita' di colpo): l'estremita' guida salta
  di un fattore lambda perche' viene presa dai cilindri;
* al **tail-out** e' l'estremita' guida a restare continua e quella trascinata
  a saltare, perche' viene rilasciata dai cilindri.

Con una schedule coerente col bilancio di massa il salto al bite cade esatto
sulla velocita' di passata e non genera rampe spurie.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kinematics import EPS_T, Segment, Trajectory, solve_crossing
from .model import FWD, REV, Case, ModelError, Product, RollingPass, SpeedEvent

_MAX_ITER = 200_000
_HORIZON = 2_000.0
_V_EPS = 1e-9


@dataclass(frozen=True)
class SimEvent:
    t: float
    kind: str
    equipment_id: str = ""
    x: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class Occupancy:
    equipment_id: str
    pass_no: int
    t_in: float
    t_out: float

    @property
    def duration(self) -> float:
        return self.t_out - self.t_in


@dataclass
class PieceResult:
    """Esito della simulazione di un pezzo.

    ``head`` e ``tail`` sono le traiettorie **fisiche**, con la testa bloccata
    all'avvolgitore. ``head_virtual`` e' la testa non vincolata, che continua ad
    avanzare oltre l'avvolgitore: e' quella che comanda il trigger dello zoom
    rolling, secondo la convenzione del modello offline.
    """

    piece_id: str
    product_id: str
    t_release: float
    head: Trajectory
    tail: Trajectory
    head_virtual: Trajectory
    events: tuple[SimEvent, ...] = ()
    occupancy: tuple[Occupancy, ...] = ()
    length_kinematic: float = 0.0
    length_geometric: float = 0.0
    x_coiler: float | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def t_start(self) -> float:
        return self.head.t_start

    @property
    def t_end(self) -> float:
        return self.head.t_end

    @property
    def length_error(self) -> float:
        if self.length_geometric == 0.0:
            return 0.0
        return 100.0 * (self.length_kinematic - self.length_geometric) / self.length_geometric

    def length_at(self, t: float) -> float:
        return self.head.x_at(t) - self.tail.x_at(t)


def simulate_piece(
    case: Case,
    product: Product,
    t_release: float = 0.0,
    piece_id: str = "P1",
) -> PieceResult:
    line = case.line
    passes: list[RollingPass] = list(product.passes)
    if not passes:
        raise ModelError(f"prodotto {product.id}: nessuna passata definita")

    coilers = line.coilers
    x_coiler = min(e.x for e in coilers) if coilers else None
    x_finish = x_coiler if x_coiler is not None else line.x_max

    head = Trajectory()
    tail = Trajectory()
    events: list[SimEvent] = []
    occupancy: list[Occupancy] = []
    warnings: list[str] = []

    t = t_release
    x_head = line.start.x
    x_tail = x_head - product.slab_len
    direction = FWD
    v_lead = 0.0
    lam = 1.0
    engaged: list[tuple[RollingPass, float, float]] = []
    next_idx = 0

    accel = line.start.accel
    first = passes[0]
    nominal_target = first.approach_v if first.approach_v is not None else first.v_entry
    zoom_factor = 1.0
    deferred: SpeedEvent | None = None
    reversing = False
    waiting_until: float | None = None
    fired: dict[str, float] = {}

    active_events: list[SpeedEvent] = list(line.all_events())

    events.append(
        SimEvent(t, "release", line.start.id, x_head, f"bramma {product.slab_len:.1f} m")
    )

    t_max = t_release + case.settings.max_time
    iterations = 0
    done = False

    while not done:
        iterations += 1
        if iterations > _MAX_ITER:
            raise ModelError(f"{piece_id}: simulazione non convergente (troppi eventi)")
        if t > t_max:
            raise ModelError(
                f"{piece_id}: superato il tempo massimo di {case.settings.max_time:.0f} s. "
                "Verificare che ogni passata sia raggiungibile nel verso indicato."
            )

        if waiting_until is not None:
            dt = waiting_until - t
            if dt > EPS_T:
                head.append(Segment(t, waiting_until, x_head, 0.0, 0.0))
                tail.append(Segment(t, waiting_until, x_tail, 0.0, 0.0))
            t = waiting_until
            waiting_until = None
            nxt = passes[next_idx]
            direction = nxt.direction
            nominal_target = nxt.approach_v if nxt.approach_v is not None else nxt.v_entry
            accel = line.get(nxt.equipment_id).accel
            reversing = False
            events.append(
                SimEvent(t, "reverse_end", nxt.equipment_id, x_head, f"verso passata {nxt.pass_no}")
            )
            continue

        v_target = nominal_target * zoom_factor
        a_lead = 0.0
        if abs(v_target - v_lead) > _V_EPS:
            a_lead = accel if v_target > v_lead else -accel

        if direction == FWD:
            v_h, a_h = v_lead, a_lead
            v_t, a_t = v_lead / lam, a_lead / lam
            lead_x, lead_v, lead_a = x_head, v_h, a_h
            trail_x, trail_v, trail_a = x_tail, v_t, a_t
        else:
            v_h, a_h = -(v_lead / lam), -(a_lead / lam)
            v_t, a_t = -v_lead, -a_lead
            lead_x, lead_v, lead_a = x_tail, v_t, a_t
            trail_x, trail_v, trail_a = x_head, v_h, a_h

        horizon = min(t + _HORIZON, t_max)
        candidates: list[tuple[float, str, object]] = []

        if a_lead != 0.0:
            candidates.append((t + (v_target - v_lead) / a_lead, "ramp", None))

        if next_idx < len(passes):
            nxt = passes[next_idx]
            x_stand = line.get(nxt.equipment_id).x
            # la gabbia deve essere ancora davanti: senza questa guardia, appena
            # dopo un bite l'estremita' guida si trova esattamente sulla gabbia e
            # una seconda passata sullo stesso stand morderebbe nello stesso istante
            ahead = direction * (x_stand - lead_x) > 1e-6
            if nxt.direction == direction and not reversing and ahead:
                t_hit = solve_crossing(
                    t, lead_x, lead_v, lead_a, x_stand, t, horizon, direction
                )
                if t_hit is not None:
                    candidates.append((t_hit, "bite", None))

        for i, (rp, x_stand, _t_in) in enumerate(engaged):
            t_hit = solve_crossing(
                t, trail_x, trail_v, trail_a, x_stand, t, horizon, direction
            )
            if t_hit is not None:
                candidates.append((t_hit, "tailout", i))

        for ev in active_events:
            if ev.direction != direction:
                continue
            if reversing and ev.origin == "section":
                continue
            last = fired.get(ev.id)
            t_hit = solve_crossing(
                t, lead_x, lead_v, lead_a, ev.x_trigger, t, horizon, direction
            )
            if t_hit is None:
                continue
            if last is not None and abs(t_hit - last) < 1e-6:
                continue
            candidates.append((t_hit, "event", ev))

        if direction == FWD and not engaged and next_idx >= len(passes):
            t_hit = solve_crossing(t, trail_x, trail_v, trail_a, x_finish, t, horizon, FWD)
            if t_hit is not None:
                candidates.append((t_hit, "finish", None))

        if not candidates:
            if next_idx < len(passes):
                nxt = passes[next_idx]
                verso = "fwd" if nxt.direction == FWD else "rev"
                raise ModelError(
                    f"{piece_id}: la passata {nxt.pass_no} su {nxt.equipment_id} non e' "
                    f"raggiungibile in verso {verso}. A t={t:.1f} s il pezzo occupa "
                    f"[{x_tail:.1f}, {x_head:.1f}] m e la gabbia sta a "
                    f"{line.get(nxt.equipment_id).x:.1f} m."
                )
            raise ModelError(
                f"{piece_id}: il pezzo si e' fermato a x={x_head:.1f} m senza eventi "
                "successivi. Manca un comando di velocita' in coda al percorso."
            )

        t_next, action, payload = min(candidates, key=lambda c: (c[0], c[1]))
        dt = max(t_next - t, 0.0)

        if dt > EPS_T:
            head.append(Segment(t, t_next, x_head, v_h, a_h))
            tail.append(Segment(t, t_next, x_tail, v_t, a_t))
            x_head = x_head + v_h * dt + 0.5 * a_h * dt * dt
            x_tail = x_tail + v_t * dt + 0.5 * a_t * dt * dt
            v_lead = max(v_lead + a_lead * dt, 0.0)
            t = t_next

        if action == "ramp":
            v_lead = v_target
            if reversing and v_target <= _V_EPS:
                nxt = passes[next_idx]
                waiting_until = t + nxt.reversing_delay
                events.append(
                    SimEvent(
                        t,
                        "reverse_wait",
                        nxt.equipment_id,
                        x_head,
                        f"reversing delay {nxt.reversing_delay:.1f} s",
                    )
                )
            continue

        if action == "bite":
            rp = passes[next_idx]
            eq = line.get(rp.equipment_id)
            lam *= rp.elongation
            v_lead *= rp.elongation
            engaged.append((rp, eq.x, t))
            nominal_target = rp.v_exit
            accel = eq.accel
            next_idx += 1
            events.append(
                SimEvent(
                    t,
                    "bite",
                    eq.id,
                    eq.x,
                    f"passata {rp.pass_no}: {rp.h_in:.1f} -> {rp.h_out:.1f} mm, "
                    f"lambda {rp.elongation:.3f}, v_usc {rp.v_exit:.2f} m/s",
                )
            )
            if rp.zoom_pct:
                zid = f"zoom-{product.id}-{rp.pass_no}"
                active_events.append(
                    SpeedEvent(
                        id=zid,
                        section_id="",
                        x_trigger=eq.x + rp.zoom_trigger,
                        accel=rp.zoom_accel,
                        direction=FWD,
                        during_pass=True,
                        origin="zoom",
                        rel_pct=rp.zoom_pct,
                    )
                )
            continue

        if action == "tailout":
            idx = int(payload)  # type: ignore[arg-type]
            rp, x_stand, t_in = engaged.pop(idx)
            lam /= rp.elongation
            occupancy.append(Occupancy(rp.equipment_id, rp.pass_no, t_in, t))
            events.append(
                SimEvent(t, "tail_out", rp.equipment_id, x_stand, f"passata {rp.pass_no}")
            )
            if not engaged:
                if deferred is not None:
                    pending, deferred = deferred, None
                    if pending.rel_pct:
                        zoom_factor *= 1.0 + pending.rel_pct / 100.0
                    else:
                        nominal_target = pending.v_target
                    if pending.accel is not None:
                        accel = pending.accel
                    events.append(
                        SimEvent(
                            t,
                            "speed_change",
                            pending.section_id,
                            x_head,
                            f"{pending.v_target:.2f} m/s (differito al disingaggio)",
                        )
                    )
                if next_idx < len(passes) and passes[next_idx].direction != direction:
                    reversing = True
                    nominal_target = 0.0
                    zoom_factor = 1.0
                    accel = line.get(rp.equipment_id).accel
                    events.append(
                        SimEvent(t, "reverse_start", rp.equipment_id, x_stand, "decelerazione")
                    )
                    if v_lead <= _V_EPS:
                        nxt = passes[next_idx]
                        waiting_until = t + nxt.reversing_delay
            continue

        if action == "event":
            trig: SpeedEvent = payload  # type: ignore[assignment]
            fired[trig.id] = t
            if engaged and not trig.during_pass:
                deferred = trig
                continue
            if trig.rel_pct:
                zoom_factor *= 1.0 + trig.rel_pct / 100.0
                detail = f"zoom {trig.rel_pct:+.1f}% su testa virtuale"
                kind = "zoom"
            else:
                nominal_target = trig.v_target
                detail = f"{trig.v_target:.2f} m/s"
                kind = "speed_change"
            if trig.accel is not None:
                accel = trig.accel
            events.append(SimEvent(t, kind, trig.section_id, trig.x_trigger, detail))
            continue

        if action == "finish":
            events.append(SimEvent(t, "coiling_end", "", x_finish, "coda al coiler"))
            done = True
            continue

        raise ModelError(f"azione sconosciuta: {action}")

    head_virtual = head
    if x_coiler is not None:
        head_phys = head.clamp_max(x_coiler)
        tail_phys = tail.clamp_max(x_coiler)
        t_coil = head.crossing_times(x_coiler, direction=FWD)
        if t_coil:
            events.append(SimEvent(t_coil[0], "coiling_start", "", x_coiler, "presa al mandrino"))
    else:
        head_phys = head
        tail_phys = tail

    length_kin = head_virtual.x_at(head_virtual.t_end) - tail.x_at(tail.t_end)
    length_geo = product.final_length
    if abs(length_kin - length_geo) > max(0.01 * length_geo, 0.05):
        warnings.append(
            f"lunghezza cinematica {length_kin:.1f} m contro {length_geo:.1f} m geometrici: "
            "bilancio di massa non conservato"
        )

    events.sort(key=lambda e: e.t)
    return PieceResult(
        piece_id=piece_id,
        product_id=product.id,
        t_release=t_release,
        head=head_phys,
        tail=tail_phys,
        head_virtual=head_virtual,
        events=tuple(events),
        occupancy=tuple(sorted(occupancy, key=lambda o: o.t_in)),
        length_kinematic=length_kin,
        length_geometric=length_geo,
        x_coiler=x_coiler,
        warnings=tuple(warnings),
    )


def simulate_case(case: Case) -> list[PieceResult]:
    """Simula la sequenza di pezzi definita nelle impostazioni.

    In modalita' open-loop i pezzi sono indipendenti: ogni prodotto viene
    simulato una sola volta e le copie sono traslate nel tempo.
    """
    pacing = case.settings.pacing
    cache: dict[str, PieceResult] = {}
    out: list[PieceResult] = []
    for i, product_id in enumerate(case.piece_products):
        base = cache.get(product_id)
        if base is None:
            base = simulate_piece(case, case.product(product_id), 0.0, product_id)
            cache[product_id] = base
        out.append(shift_result(base, i * pacing, f"#{i + 1}"))
    return out


def shift_result(result: PieceResult, dt: float, piece_id: str | None = None) -> PieceResult:
    return PieceResult(
        piece_id=piece_id or result.piece_id,
        product_id=result.product_id,
        t_release=result.t_release + dt,
        head=result.head.shift(dt),
        tail=result.tail.shift(dt),
        head_virtual=result.head_virtual.shift(dt),
        events=tuple(
            SimEvent(e.t + dt, e.kind, e.equipment_id, e.x, e.detail) for e in result.events
        ),
        occupancy=tuple(
            Occupancy(o.equipment_id, o.pass_no, o.t_in + dt, o.t_out + dt)
            for o in result.occupancy
        ),
        length_kinematic=result.length_kinematic,
        length_geometric=result.length_geometric,
        x_coiler=result.x_coiler,
        warnings=result.warnings,
    )
