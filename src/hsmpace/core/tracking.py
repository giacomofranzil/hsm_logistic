"""Import del tracking reale per il confronto simulato vs misurato.

Formato CSV minimo, deliberatamente povero perche' sia facile da produrre da
un export IBA PDA, da un trend HMI o da una query sul database di Livello 2:

    piece_id,time_s,head_m,tail_m
    A1234,0.00,0.0,-10.5
    A1234,0.50,0.6,-9.9

* ``piece_id``  identificativo del pezzo, una serie per ogni valore distinto
* ``time_s``    tempo in secondi, crescente, origine libera
* ``head_m``    posizione della testa lungo la linea, in metri
* ``tail_m``    posizione della coda; colonna facoltativa

Le posizioni devono essere riferite alla stessa origine del layout.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class TrackingSeries:
    piece_id: str
    t: list[float]
    head: list[float]
    tail: list[float]

    def shift(self, dt: float) -> "TrackingSeries":
        return TrackingSeries(self.piece_id, [x + dt for x in self.t], self.head, self.tail)

    @property
    def has_tail(self) -> bool:
        return any(v is not None for v in self.tail)


def parse_tracking(lines: Iterable[str]) -> list[TrackingSeries]:
    reader = csv.DictReader(line for line in lines if line.strip())
    if reader.fieldnames is None:
        return []
    fields = {name.strip().lower(): name for name in reader.fieldnames}
    required = ("piece_id", "time_s", "head_m")
    missing = [name for name in required if name not in fields]
    if missing:
        raise ValueError(
            "CSV di tracking: colonne mancanti " + ", ".join(missing) +
            ". Attese: piece_id, time_s, head_m, tail_m (facoltativa)."
        )

    series: dict[str, TrackingSeries] = {}
    for row_no, row in enumerate(reader, start=2):
        piece = str(row[fields["piece_id"]]).strip()
        try:
            t = float(str(row[fields["time_s"]]).replace(",", "."))
            head = float(str(row[fields["head_m"]]).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"CSV di tracking, riga {row_no}: valore non numerico") from exc
        tail = head
        if "tail_m" in fields and row.get(fields["tail_m"]) not in (None, ""):
            tail = float(str(row[fields["tail_m"]]).replace(",", "."))

        entry = series.setdefault(piece, TrackingSeries(piece, [], [], []))
        entry.t.append(t)
        entry.head.append(head)
        entry.tail.append(tail)

    return list(series.values())


def read_tracking_csv(path: str | Path) -> list[TrackingSeries]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return parse_tracking(handle)
