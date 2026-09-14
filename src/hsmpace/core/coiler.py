"""Coiler slowdown and reversing stop: waypoint arithmetic on the tail.

The slowdown is planned on the tail and commanded on the leading extremity.
These helpers are pure: they do not own simulation state.
"""

from __future__ import annotations

import math

from .model import RollingPass

_X_EPS = 1e-6


def braking_distance(v_from: float, v_to: float, accel: float) -> float:
    """Distance needed to go from one speed to another at a given acceleration."""
    if accel <= 0.0:
        return 0.0
    return abs(v_from * v_from - v_to * v_to) / (2.0 * accel)


def reversal_tailout_speed(clearance: float, table_accel: float) -> float | None:
    """Lead speed at tail-out that lets the table stop exactly at ``clearance``.

    ``None`` means the cell is empty: stop as soon as possible after tail-out,
    with no mill slowdown.
    """
    if clearance <= 1e-9 or table_accel <= 0.0:
        return None
    return math.sqrt(2.0 * table_accel * clearance)


def _stands_ahead_of_tail(
    x_tail: float,
    engaged: list[tuple[RollingPass, float, float]],
) -> list[tuple[float, float]]:
    """Remaining stands the tail still has to clear, upstream to downstream."""
    stands = [(x, rp.elongation) for rp, x, _ in engaged if x > x_tail + _X_EPS]
    stands.sort(key=lambda item: item[0])
    return stands


def coiler_tail_waypoint(
    x_tail: float,
    x_coiler: float,
    v_final: float,
    accel: float,
    engaged: list[tuple[RollingPass, float, float]],
) -> tuple[float, float]:
    """Next tail target so that, after the remaining tail-outs, it meets ``v_final``.

    Walks backward from the mandrel. At each stand the tail speeds up by that
    pass's lambda, so the speed required just before tail-out is the speed
    required just after it, divided by lambda. Between stands the tail is held
    at deceleration ``accel``. With no stand left the waypoint is the coiler
    itself at ``v_final``.
    """
    x_wp = x_coiler
    v_wp = max(v_final, 0.0)
    for x_stand, lam_i in reversed(_stands_ahead_of_tail(x_tail, engaged)):
        gap = max(x_wp - x_stand, 0.0)
        v_after = (v_wp * v_wp + 2.0 * accel * gap) ** 0.5 if accel > 0.0 else v_wp
        v_wp = v_after / lam_i if lam_i > 0.0 else v_after
        x_wp = x_stand
    return x_wp, v_wp


def tail_arrival_speed(
    x_tail: float,
    v_tail: float,
    x_coiler: float,
    accel: float,
    engaged: list[tuple[RollingPass, float, float]],
) -> float:
    """Speed the tail would have at the coiler if it decelerated at ``accel`` now.

    Includes the jump at every remaining tail-out: the tail speeds up by the
    pass lambda when that stand releases it, then keeps decelerating.
    """
    x = x_tail
    v = max(v_tail, 0.0)
    for x_stand, lam_i in _stands_ahead_of_tail(x_tail, engaged):
        gap = max(x_stand - x, 0.0)
        v2 = v * v - 2.0 * accel * gap
        v = v2 ** 0.5 if v2 > 0.0 else 0.0
        v *= lam_i
        x = x_stand
    gap = max(x_coiler - x, 0.0)
    v2 = v * v - 2.0 * accel * gap
    return v2 ** 0.5 if v2 > 0.0 else 0.0
