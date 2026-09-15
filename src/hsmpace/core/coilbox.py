"""Coilbox commanded speeds. State remains in the event loop of ``simulate_piece``.

Payout of stored metal is in metres of transfer bar at mill entry speed
``v_lead / lambda``, not extra travel of the head. See docs/algorithm-spec.md §4.
"""

from __future__ import annotations

from .model import Product


def commanded_speed(product: Product, x_virt: float, x_cb: float) -> float:
    """Speed the box would like, once it is allowed to command.

    Empty (0) fields keep the speed already in force: the caller ignores a
    non-positive return value.
    """
    entered = x_virt - x_cb
    threading = (
        product.coilbox_thread_length > 1e-9
        and entered < product.coilbox_thread_length - 1e-9
    )
    if threading:
        return product.coilbox_v_thread
    if product.coilbox_v_coil > 1e-9:
        return product.coilbox_v_coil
    return product.coilbox_v_thread
