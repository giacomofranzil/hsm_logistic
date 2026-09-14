"""TRoll XML → Case. Boundary for the P1 importer; not implemented yet."""

from __future__ import annotations

from pathlib import Path

from ...core.model import Case


def case_from_troll(path: str | Path) -> Case:
    """Map a TRoll XML dump onto the canonical Case.

    Needs a real dump as a golden file before the parser is written. The
    destination is always ``Case``: TRoll is not the internal schema.
    """
    raise NotImplementedError(
        f"TRoll XML import is not implemented yet ({path}). "
        "Provide a dump to build the mapper onto Case."
    )
