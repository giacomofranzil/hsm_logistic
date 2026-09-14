"""Compatibility shim: Excel I/O now lives in ``hsmpace.io.excel``."""

from hsmpace.io.excel import (
    ValidationError,
    ValidationIssue,
    read_case,
    write_case,
    write_results,
)

__all__ = [
    "ValidationError",
    "ValidationIssue",
    "read_case",
    "write_case",
    "write_results",
]
