"""Mill-type adapters: layout limits and extra equipment kinds.

The kinematic engine in ``core`` is shared. Each mill type adds validation and,
later, event rules that do not belong on every plant.
"""

from __future__ import annotations

from ..core.model import MILL_HSM, MILL_TYPES, Case, Problem
from .hsm import validate as validate_hsm

_VALIDATORS = {
    MILL_HSM: validate_hsm,
}


def validate_plant(case: Case) -> list[Problem]:
    fn = _VALIDATORS.get(case.mill_type)
    if fn is None:
        allowed = ", ".join(sorted(MILL_TYPES))
        return [
            Problem(
                "",
                f"mill_type {case.mill_type!r} is not valid: use {allowed}",
            )
        ]
    return fn(case)
