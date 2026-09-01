"""Caso di esempio: Hot Strip Mill convenzionale.

Layout con sbozzatore a due gabbie reversibili con edger, tavolo di
trasferimento, cesoia, finitore a sette gabbie e avvolgitore. I numeri sono
plausibili ma inventati: servono a far girare il tool e a mostrare il formato,
non descrivono un impianto reale.
"""

from __future__ import annotations

from .core.model import (
    FWD,
    REV,
    Case,
    Equipment,
    Line,
    Product,
    RollingPass,
    Section,
    SimSettings,
    SpeedEvent,
)

_EQUIPMENT = [
    Equipment("FURN", "start", 0.0, accel=0.8, label="Uscita forno"),
    Equipment("DS1", "marker", 8.0, label="Descagliatore primario"),
    Equipment("E1", "marker", 22.0, label="Edger E1"),
    Equipment("R1", "stand", 25.0, accel=1.0, label="Sbozzatore R1"),
    Equipment("E2", "marker", 57.0, label="Edger E2"),
    Equipment("R2", "stand", 60.0, accel=1.0, label="Sbozzatore R2"),
    Equipment("SHR", "marker", 175.0, label="Cesoia crop"),
    Equipment("DS2", "marker", 182.0, label="Descagliatore finitore"),
    Equipment("F1", "stand", 190.0, accel=1.5, group="FM", label="F1"),
    Equipment("F2", "stand", 195.5, accel=1.5, group="FM", label="F2"),
    Equipment("F3", "stand", 201.0, accel=1.5, group="FM", label="F3"),
    Equipment("F4", "stand", 206.5, accel=1.5, group="FM", label="F4"),
    Equipment("F5", "stand", 212.0, accel=1.5, group="FM", label="F5"),
    Equipment("F6", "stand", 217.5, accel=1.5, group="FM", label="F6"),
    Equipment("F7", "stand", 223.0, accel=1.5, group="FM", label="F7"),
    Equipment("DC1", "coiler", 330.0, accel=1.5, label="Avvolgitore 1"),
]

_SECTIONS = [
    Section(
        "S1",
        x_start=0.0,
        length=25.0,
        label="Forno - R1",
        events=(
            SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=1.2, direction=FWD),
        ),
    ),
    Section("S2", x_start=25.0, length=35.0, label="R1 - R2"),
    Section(
        "S3",
        x_start=60.0,
        length=115.0,
        label="Tavolo di trasferimento",
        events=(
            SpeedEvent("S3-1", "S3", x_trigger=65.0, v_target=5.0, direction=FWD),
            SpeedEvent("S3-2", "S3", x_trigger=155.0, v_target=1.0, direction=FWD),
        ),
    ),
    Section("S4", x_start=175.0, length=15.0, label="Cesoia - F1"),
    Section("S5", x_start=190.0, length=140.0, label="Finitore - avvolgitore"),
]

# (pass_no, stand, verso, h_in, h_out, w_in, w_out, v_exit, reversing_delay, sgombero)
_PASSES = [
    (1, "R1", FWD, 220.0, 175.0, 1250.0, 1255.0, 2.50, 0.0, 0.0),
    (2, "R1", REV, 175.0, 135.0, 1255.0, 1260.0, 3.00, 6.0, 5.0),
    (3, "R1", FWD, 135.0, 105.0, 1260.0, 1265.0, 3.50, 6.0, 5.0),
    (4, "R2", FWD, 105.0, 75.0, 1265.0, 1268.0, 3.50, 0.0, 0.0),
    (5, "R2", REV, 75.0, 52.0, 1268.0, 1270.0, 4.00, 6.0, 5.0),
    (6, "R2", FWD, 52.0, 38.0, 1270.0, 1272.0, 4.50, 6.0, 5.0),
    (7, "F1", FWD, 38.0, 22.0, 1272.0, 1272.0, 1.70, 0.0, 0.0),
    (8, "F2", FWD, 22.0, 13.2, 1272.0, 1272.0, 2.84, 0.0, 0.0),
    (9, "F3", FWD, 13.2, 8.6, 1272.0, 1272.0, 4.36, 0.0, 0.0),
    (10, "F4", FWD, 8.6, 6.0, 1272.0, 1272.0, 6.25, 0.0, 0.0),
    (11, "F5", FWD, 6.0, 4.5, 1272.0, 1272.0, 8.33, 0.0, 0.0),
    (12, "F6", FWD, 4.5, 3.6, 1272.0, 1272.0, 10.42, 0.0, 0.0),
    (13, "F7", FWD, 3.6, 3.0, 1272.0, 1272.0, 12.50, 0.0, 0.0),
]


def example_case() -> Case:
    passes = []
    for pass_no, stand, direction, h_in, h_out, w_in, w_out, v_exit, delay, clearance in _PASSES:
        passes.append(
            RollingPass(
                product_id="P1",
                pass_no=pass_no,
                equipment_id=stand,
                direction=direction,
                h_in=h_in,
                h_out=h_out,
                w_in=w_in,
                w_out=w_out,
                v_exit=v_exit,
                reversing_delay=delay,
                reversing_clearance=clearance,
                master=(stand == "F7"),
                zoom_pct=8.0 if stand == "F7" else 0.0,
                # 130 m dopo F7 cadono oltre l'avvolgitore, che sta a 107 m:
                # il trigger usa percio' la testa virtuale, cioe' lo zoom parte
                # dopo qualche avvolgimento, come nel modello offline
                zoom_trigger=130.0 if stand == "F7" else 0.0,
            )
        )

    product = Product(
        id="P1",
        slab_thk=220.0,
        slab_wid=1250.0,
        slab_len=10.5,
        label="Coil 3.0 mm x 1272",
        grade="S235JR",
        passes=tuple(passes),
    )

    settings = SimSettings(
        pacing=170.0,
        n_pieces=3,
        gap_min=5.0,
        pacing_scan_min=90.0,
        pacing_scan_max=300.0,
        pacing_scan_steps=106,
        mc_runs=600,
        mc_speed_tol_pct=2.0,
        mc_delay_sigma=1.0,
        mc_release_sigma=2.0,
    )

    return Case(
        line=Line(tuple(_EQUIPMENT), tuple(_SECTIONS)),
        products=(product,),
        settings=settings,
        info={
            "schema_version": "1",
            "mill_name": "HSM di esempio",
            "notes": "Dati inventati a scopo dimostrativo",
        },
    )
