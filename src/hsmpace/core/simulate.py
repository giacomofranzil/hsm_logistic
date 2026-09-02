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

Every commanded speed change is **anticipated**: the ramp starts early enough
for the new speed to be reached exactly at the position requested. The same
rule governs the stop before a reversal and the deceleration towards the
coiler, so there is a single semantics to remember: what you write in the input
is the point where the target is met, not where the ramp begins.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kinematics import EPS_T, Segment, Trajectory, _quad_roots, solve_crossing
from .model import FWD, Case, Line, ModelError, Product, RollingPass, SpeedEvent

_MAX_ITER = 200_000
_HORIZON = 2_000.0
_V_EPS = 1e-9
_X_EPS = 1e-6


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


def braking_distance(v_from: float, v_to: float, accel: float) -> float:
    """Distance needed to go from one speed to another at a given acceleration."""
    if accel <= 0.0:
        return 0.0
    return abs(v_from * v_from - v_to * v_to) / (2.0 * accel)


def _ramp_start_time(
    gap0: float,
    v_now: float,
    a_now: float,
    v_target: float,
    a_ramp: float,
    horizon: float,
) -> float | None:
    """When the remaining distance to the target point equals the ramp distance.

    ``gap0`` is the distance still to run in the direction of travel. Both the
    remaining distance and the required ramp distance are quadratic in time, so
    the instant at which they meet is found in closed form. Returns ``None``
    when it does not happen within ``horizon``, and 0.0 when it has already
    passed, meaning the ramp has to start immediately.
    """
    if a_ramp <= 0.0:
        return None
    sign = 1.0 if v_now > v_target else -1.0
    k = sign / (2.0 * a_ramp)

    c0 = gap0 - k * (v_now * v_now - v_target * v_target)
    c1 = -v_now * (1.0 + sign * a_now / a_ramp)
    c2 = -0.5 * a_now * (1.0 + sign * a_now / a_ramp)

    if c0 <= 0.0:
        return 0.0
    roots = [r for r in _quad_roots(c0, c1, c2, 0.0, horizon) if r >= 0.0]
    return roots[0] if roots else None


def simulate_piece(
    case: Case,
    product: Product,
    t_release: float = 0.0,
    piece_id: str = "P1",
) -> PieceResult:
    line: Line = case.line
    settings = case.settings
    passes: list[RollingPass] = list(product.passes)
    if not passes:
        raise ModelError(f"product {product.id}: no pass defined")

    coilers = line.coilers
    coiler = min(coilers, key=lambda e: e.x) if coilers else None
    x_coiler = coiler.x if coiler is not None else None
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

    first = passes[0]
    nominal_target = first.approach_v if first.approach_v is not None else first.v_entry
    zoom_factor = 1.0
    ramp_accel: float | None = None
    stand_accel = line.start.accel
    armed_id: str | None = None
    armed_target = 0.0
    deferred: SpeedEvent | None = None
    reversing = False
    braking = False
    stop_target = 0.0
    stop_stand_x = 0.0
    stop_stand_id = ""
    stop_pass_no = 0
    stop_clearance = 0.0
    coiler_braking = False
    waiting_until: float | None = None
    fired: dict[str, float] = {}

    active_events: list[SpeedEvent] = list(line.all_events())

    events.append(
        SimEvent(t, "release", line.start.id, x_head, f"slab {product.slab_len:.1f} m")
    )

    t_max = t_release + settings.max_time
    iterations = 0
    done = False

    def table_accel(x: float) -> float:
        section = line.section_at(x)
        if section is not None and section.accel:
            return section.accel
        return settings.table_accel

    while not done:
        iterations += 1
        if iterations > _MAX_ITER:
            raise ModelError(f"{piece_id}: simulation does not converge (too many events)")
        if t > t_max:
            raise ModelError(
                f"{piece_id}: exceeded the maximum time of {settings.max_time:.0f} s. "
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
            stand_accel = line.get(nxt.equipment_id).accel
            ramp_accel = None
            reversing = False
            braking = False
            events.append(
                SimEvent(
                    t, "reverse_end", nxt.equipment_id, x_head, f"heading to pass {nxt.pass_no}"
                )
            )
            continue

        # the stand commands while the piece is gripped, the roller table when it is free
        lead_x_now = x_head if direction == FWD else x_tail
        prevailing = stand_accel if engaged else table_accel(lead_x_now)
        accel = ramp_accel if ramp_accel is not None else prevailing

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

        # reversal: the piece must come to rest with the extremity closest to the
        # stand at `reversing_clearance` metres from it
        if reversing and not braking:
            d_brake = braking_distance(v_lead, 0.0, accel)
            x_brake = stop_target - direction * d_brake
            if direction * (x_brake - trail_x) <= 1e-9:
                if stop_clearance > 1e-9 and direction * (trail_x - x_brake) > _X_EPS:
                    achieved = abs(trail_x + direction * d_brake - stop_stand_x)
                    warnings.append(
                        f"pass {stop_pass_no}: {stop_clearance:.1f} m of clearance requested "
                        f"from {stop_stand_id}, {achieved:.1f} m achievable. At {v_lead:.2f} m/s "
                        f"with {accel:.2f} m/s2 the piece cannot stop any earlier."
                    )
                braking = True
                nominal_target = 0.0
                continue
            t_hit = solve_crossing(
                t, trail_x, trail_v, trail_a, x_brake, t, horizon, direction
            )
            if t_hit is not None:
                candidates.append((t_hit, "brake", None))

        # deceleration towards the coiler: the tail must get there at the final speed
        free_run = not engaged and next_idx >= len(passes) and not reversing
        if (
            x_coiler is not None
            and coiler is not None
            and free_run
            and not coiler_braking
            and direction == FWD
            and v_lead > settings.coiler_v_final + _V_EPS
        ):
            d_brake = braking_distance(v_lead, settings.coiler_v_final, coiler.accel)
            x_brake = x_coiler - d_brake
            if trail_x >= x_brake - 1e-9:
                if trail_x > x_brake + _X_EPS:
                    reachable = max(
                        settings.coiler_v_final,
                        (v_lead * v_lead - 2.0 * coiler.accel * (x_coiler - trail_x)) ** 0.5
                        if v_lead * v_lead > 2.0 * coiler.accel * (x_coiler - trail_x)
                        else settings.coiler_v_final,
                    )
                    warnings.append(
                        f"coiler: the tail cannot slow down to {settings.coiler_v_final:.1f} m/s "
                        f"within the run-out table. At {coiler.accel:.2f} m/s2 it arrives at "
                        f"{reachable:.1f} m/s; "
                        f"{braking_distance(v_lead, settings.coiler_v_final, coiler.accel):.0f} m "
                        f"would be needed against the {x_coiler - trail_x:.0f} m available."
                    )
                coiler_braking = True
                ramp_accel = coiler.accel
                zoom_factor = 1.0
                nominal_target = settings.coiler_v_final
                events.append(
                    SimEvent(
                        t,
                        "coiler_slowdown",
                        coiler.id,
                        trail_x,
                        f"target {settings.coiler_v_final:.1f} m/s at the mandrel",
                    )
                )
                continue
            t_hit = solve_crossing(t, trail_x, trail_v, trail_a, x_brake, t, horizon, FWD)
            if t_hit is not None:
                candidates.append((t_hit, "coiler_brake", None))

        # speed events: the target must be met AT the requested position, so the
        # ramp is anticipated. Only the nearest event ahead is armed.
        # zoom rolling keeps the opposite convention on purpose: its trigger is the
        # position where the acceleration STARTS, as in the offline model
        pending = _next_event(active_events, lead_x, direction, armed_id)
        if pending is not None and pending.rel_pct:
            pending = None
        if pending is not None and not reversing and not coiler_braking:
            gap0 = direction * (pending.x_trigger - lead_x)
            target = pending.v_target
            a_ramp = pending.accel or prevailing
            # a ramp cannot be planned across a rolling pass: the bite would reset
            # the speed anyway, so the event is left to its normal handling
            blocked = any(
                0.0 < direction * (line.get(p.equipment_id).x - lead_x)
                < direction * (pending.x_trigger - lead_x)
                for p in passes[next_idx:]
                if p.direction == direction
            )
            deferrable = not pending.during_pass and (
                blocked
                or (
                    bool(engaged)
                    and _still_engaged_at(
                        t, lead_x, lead_v, lead_a, trail_x, trail_v, trail_a,
                        pending.x_trigger, engaged, direction, horizon,
                    )
                )
            )
            if not deferrable and abs(target - v_lead) > _V_EPS:
                dt_ramp = _ramp_start_time(gap0, v_lead, a_lead, target, a_ramp, horizon - t)
                if dt_ramp is not None:
                    candidates.append((t + dt_ramp, "arm", pending))

        if a_lead != 0.0:
            candidates.append((t + (v_target - v_lead) / a_lead, "ramp", None))

        if next_idx < len(passes):
            nxt = passes[next_idx]
            x_stand = line.get(nxt.equipment_id).x
            # the stand must still be ahead: without this guard, right after a bite
            # the leading extremity sits exactly on the stand and a second pass on
            # the same stand would bite at the very same instant
            ahead = direction * (x_stand - lead_x) > _X_EPS
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
            candidates.append((t_hit, "trigger", ev))

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

        if action == "coiler_brake":
            coiler_braking = True
            ramp_accel = coiler.accel  # type: ignore[union-attr]
            zoom_factor = 1.0
            nominal_target = settings.coiler_v_final
            events.append(
                SimEvent(
                    t,
                    "coiler_slowdown",
                    coiler.id,  # type: ignore[union-attr]
                    x_tail,
                    f"target {settings.coiler_v_final:.1f} m/s at the mandrel",
                )
            )
            continue

        if action == "arm":
            ev: SpeedEvent = payload  # type: ignore[assignment]
            armed_id = ev.id
            nominal_target = ev.v_target
            zoom_factor = 1.0
            armed_target = nominal_target
            ramp_accel = ev.accel
            if engaged:
                warnings.append(
                    f"section event {ev.id}: to reach {armed_target:.2f} m/s at "
                    f"x={ev.x_trigger:.1f} m the ramp has to start while the piece is still "
                    "being rolled, so the mill speed changes during the pass."
                )
            continue

        if action == "ramp":
            v_lead = v_target
            ramp_accel = None
            if braking and v_target <= _V_EPS:
                rp_prev = _last_completed_pass(passes, next_idx)
                waiting_until = t + (rp_prev.reversing_delay if rp_prev else 0.0)
                events.append(
                    SimEvent(
                        t,
                        "reverse_wait",
                        stop_stand_id,
                        x_head,
                        f"reversing delay {rp_prev.reversing_delay:.1f} s" if rp_prev else "",
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
            stand_accel = eq.accel
            ramp_accel = None
            armed_id = None
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
                active_events.append(
                    SpeedEvent(
                        id=f"zoom-{product.id}-{rp.pass_no}",
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
                    pendingev, deferred = deferred, None
                    if pendingev.rel_pct:
                        zoom_factor *= 1.0 + pendingev.rel_pct / 100.0
                    else:
                        nominal_target = pendingev.v_target
                    ramp_accel = pendingev.accel
                    events.append(
                        SimEvent(
                            t,
                            "speed_change",
                            pendingev.section_id,
                            x_head,
                            f"{pendingev.v_target:.2f} m/s (deferred to disengagement)",
                        )
                    )
                if next_idx < len(passes) and passes[next_idx].direction != direction:
                    reversing = True
                    braking = False
                    zoom_factor = 1.0
                    ramp_accel = None
                    armed_id = None
                    # the clearance belongs to the pass the reversal comes after
                    stop_stand_x = x_stand
                    stop_stand_id = rp.equipment_id
                    stop_pass_no = rp.pass_no
                    stop_clearance = rp.reversing_clearance
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
                        waiting_until = t + rp.reversing_delay
            continue

        if action == "trigger":
            trig: SpeedEvent = payload  # type: ignore[assignment]
            fired[trig.id] = t
            if engaged and not trig.during_pass:
                deferred = trig
                armed_id = None
                continue
            anticipated = armed_id == trig.id
            if anticipated:
                armed_id = None
                if abs(v_lead - armed_target) > max(0.02 * max(armed_target, 1.0), 0.05):
                    warnings.append(
                        f"section event {trig.id}: {armed_target:.2f} m/s requested at "
                        f"x={trig.x_trigger:.1f} m, {v_lead:.2f} m/s reached. Not enough "
                        "distance to complete the ramp."
                    )
            else:
                # never armed, for example because the piece was already at speed
                if trig.rel_pct:
                    zoom_factor *= 1.0 + trig.rel_pct / 100.0
                else:
                    nominal_target = trig.v_target
                    zoom_factor = 1.0
                if trig.accel is not None:
                    ramp_accel = trig.accel
            kind = "zoom" if trig.rel_pct else "speed_change"
            if trig.rel_pct:
                detail = f"zoom {trig.rel_pct:+.1f}% on the virtual head"
            elif anticipated:
                detail = f"{trig.v_target:.2f} m/s reached here as requested"
            else:
                detail = f"{trig.v_target:.2f} m/s commanded from here"
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
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _next_event(
    active_events: list[SpeedEvent],
    lead_x: float,
    direction: int,
    armed_id: str | None,
) -> SpeedEvent | None:
    """Nearest event still ahead in the current direction of travel."""
    best: SpeedEvent | None = None
    best_gap = float("inf")
    for ev in active_events:
        if ev.direction != direction or ev.id == armed_id:
            continue
        gap = direction * (ev.x_trigger - lead_x)
        if gap > _X_EPS and gap < best_gap:
            best, best_gap = ev, gap
    return best


def _still_engaged_at(
    t: float,
    lead_x: float,
    lead_v: float,
    lead_a: float,
    trail_x: float,
    trail_v: float,
    trail_a: float,
    x_trigger: float,
    engaged: list[tuple[RollingPass, float, float]],
    direction: int,
    horizon: float,
) -> bool:
    """Whether the piece will still be rolling when the target position is reached.

    Anticipating a ramp that ends inside the rolling zone would let a roller
    table setpoint override the pass speed halfway through the pass, so in that
    case the event stays deferred to disengagement as usual. The estimate uses
    the current law of motion, which is enough to tell the two situations apart.
    """
    t_trigger = solve_crossing(t, lead_x, lead_v, lead_a, x_trigger, t, horizon, direction)
    if t_trigger is None:
        return True
    for _rp, x_stand, _t_in in engaged:
        t_out = solve_crossing(t, trail_x, trail_v, trail_a, x_stand, t, horizon, direction)
        if t_out is None or t_out > t_trigger:
            return True
    return False


def _last_completed_pass(passes: list[RollingPass], next_idx: int) -> RollingPass | None:
    return passes[next_idx - 1] if 0 < next_idx <= len(passes) else None


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
