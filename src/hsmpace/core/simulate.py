"""Event-driven simulator of a piece travelling along the line.

Governing principle: **the head commands, the tail follows**.

The user describes the speed of the extremity that leads in the current
direction of travel (the material head on direct passes, the tail on reverse
passes). The speed of the other extremity follows from the mass flow balance of
the stands engaged between the two:

    v_trailing = v_leading / prod(lambda_i),  lambda_i = (h_in*w_in)/(h_out*w_out)

The discontinuities at engagement changes are both physically correct:

* at **bite** it is the trailing extremity that stays continuous (the body of
  the bar has mass and cannot change speed instantly): the leading extremity
  jumps by a factor lambda because it is gripped by the rolls;
* at **tail-out** the opposite happens, the leading extremity stays continuous
  and the trailing one jumps, because it is released by the rolls.

With a schedule consistent with the mass flow balance, the jump at bite lands
exactly on the pass speed and produces no spurious ramps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kinematics import EPS_T, Segment, Trajectory, solve_crossing
from .model import FWD, Case, ModelError, Product, RollingPass, SpeedEvent

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
    """Outcome of the simulation of a single piece.

    ``head`` and ``tail`` are the **physical** trajectories, with the head
    pinned at the coiler. ``head_virtual`` is the unconstrained head, which
    keeps advancing beyond the coiler: that is the one driving the zoom rolling
    trigger, following the convention of the offline model.
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
        raise ModelError(f"product {product.id}: no pass defined")

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
    braking = False
    stop_target = 0.0
    stop_stand_x = 0.0
    stop_stand_id = ""
    stop_pass_no = 0
    stop_clearance = 0.0
    waiting_until: float | None = None
    fired: dict[str, float] = {}

    active_events: list[SpeedEvent] = list(line.all_events())

    events.append(
        SimEvent(t, "release", line.start.id, x_head, f"slab {product.slab_len:.1f} m")
    )

    t_max = t_release + case.settings.max_time
    iterations = 0
    done = False

    while not done:
        iterations += 1
        if iterations > _MAX_ITER:
            raise ModelError(f"{piece_id}: simulation does not converge (too many events)")
        if t > t_max:
            raise ModelError(
                f"{piece_id}: exceeded the maximum time of {case.settings.max_time:.0f} s. "
                "Check that every pass is reachable in the direction given."
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
            braking = False
            events.append(
                SimEvent(
                    t, "reverse_end", nxt.equipment_id, x_head, f"heading to pass {nxt.pass_no}"
                )
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

        # reversal: the piece must come to rest with the extremity closest to the
        # stand at `reversing_clearance` metres from it. It keeps a constant speed
        # up to the point where the available deceleration lands exactly there,
        # then brakes.
        if reversing and not braking:
            d_brake = v_lead * v_lead / (2.0 * accel) if accel > 0 else 0.0
            x_brake = stop_target - direction * d_brake
            if direction * (x_brake - trail_x) <= 1e-9:
                # a zero clearance means "stop as soon as possible", so the braking
                # distance is not a deviation worth reporting
                if stop_clearance > 1e-9 and direction * (trail_x - x_brake) > 1e-6:
                    achieved = abs(trail_x + direction * d_brake - stop_stand_x)
                    warnings.append(
                        f"pass {stop_pass_no}: {stop_clearance:.1f} m of clearance requested from "
                        f"{stop_stand_id}, {achieved:.1f} m achievable. At {v_lead:.2f} m/s with "
                        f"{accel:.2f} m/s2 the piece cannot stop any earlier."
                    )
                braking = True
                nominal_target = 0.0
                continue

        horizon = min(t + _HORIZON, t_max)
        candidates: list[tuple[float, str, object]] = []

        if reversing and not braking:
            t_hit = solve_crossing(
                t, trail_x, trail_v, trail_a, x_brake, t, horizon, direction
            )
            if t_hit is not None:
                candidates.append((t_hit, "brake", None))

        if a_lead != 0.0:
            candidates.append((t + (v_target - v_lead) / a_lead, "ramp", None))

        if next_idx < len(passes):
            nxt = passes[next_idx]
            x_stand = line.get(nxt.equipment_id).x
            # the stand must still be ahead: without this guard, right after a bite
            # the leading extremity sits exactly on the stand and a second pass on
            # the same stand would bite at the very same instant
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
                heading = "fwd" if nxt.direction == FWD else "rev"
                raise ModelError(
                    f"{piece_id}: pass {nxt.pass_no} on {nxt.equipment_id} is not reachable "
                    f"in direction {heading}. At t={t:.1f} s the piece spans "
                    f"[{x_tail:.1f}, {x_head:.1f}] m and the stand is at "
                    f"{line.get(nxt.equipment_id).x:.1f} m."
                )
            raise ModelError(
                f"{piece_id}: the piece stopped at x={x_head:.1f} m with no further events. "
                "A speed command is missing at the end of the route."
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

        if action == "brake":
            braking = True
            nominal_target = 0.0
            continue

        if action == "ramp":
            v_lead = v_target
            if braking and v_target <= _V_EPS:
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
                    f"pass {rp.pass_no}: {rp.h_in:.1f} -> {rp.h_out:.1f} mm, "
                    f"lambda {rp.elongation:.3f}, v_exit {rp.v_exit:.2f} m/s",
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
                SimEvent(t, "tail_out", rp.equipment_id, x_stand, f"pass {rp.pass_no}")
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
                            f"{pending.v_target:.2f} m/s (deferred to disengagement)",
                        )
                    )
                if next_idx < len(passes) and passes[next_idx].direction != direction:
                    nxt = passes[next_idx]
                    reversing = True
                    braking = False
                    zoom_factor = 1.0
                    accel = line.get(rp.equipment_id).accel
                    # at tail-out the trailing extremity sits exactly on the stand
                    stop_stand_x = x_stand
                    stop_stand_id = rp.equipment_id
                    stop_pass_no = nxt.pass_no
                    stop_clearance = nxt.reversing_clearance
                    stop_target = x_stand + direction * stop_clearance
                    events.append(
                        SimEvent(
                            t,
                            "reverse_start",
                            rp.equipment_id,
                            x_stand,
                            f"clearance requested {stop_clearance:.1f} m"
                            if stop_clearance
                            else "stopping at the shortest braking distance",
                        )
                    )
                    if v_lead <= _V_EPS and stop_clearance <= 1e-9:
                        braking = True
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
                detail = f"zoom {trig.rel_pct:+.1f}% on the virtual head"
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
            events.append(SimEvent(t, "coiling_end", "", x_finish, "tail at the coiler"))
            done = True
            continue

        raise ModelError(f"unknown action: {action}")

    head_virtual = head
    if x_coiler is not None:
        head_phys = head.clamp_max(x_coiler)
        tail_phys = tail.clamp_max(x_coiler)
        t_coil = head.crossing_times(x_coiler, direction=FWD)
        if t_coil:
            events.append(SimEvent(t_coil[0], "coiling_start", "", x_coiler, "gripped by mandrel"))
    else:
        head_phys = head
        tail_phys = tail

    length_kin = head_virtual.x_at(head_virtual.t_end) - tail.x_at(tail.t_end)
    length_geo = product.final_length
    if abs(length_kin - length_geo) > max(0.01 * length_geo, 0.05):
        warnings.append(
            f"kinematic length {length_kin:.1f} m against {length_geo:.1f} m geometric: "
            "mass balance is not conserved"
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
    """Simulate the sequence of pieces defined in the settings.

    In open-loop mode the pieces are independent: every product is simulated
    once and the copies are shifted in time.
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
