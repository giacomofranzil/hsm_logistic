"""Example case: conventional Hot Strip Mill.

Layout with a two stand reversing roughing mill with edgers, transfer table,
crop shear, seven stand finishing mill and two in-line downcoilers. The numbers
are plausible but invented: they serve to run the tool and to show the format,
they do not describe a real plant.
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
    Equipment("FURN", "start", 0.0, label="Furnace exit"),
    Equipment("DS1", "marker", 8.0, label="Primary descaler"),
    Equipment("E1", "marker", 22.0, label="Edger E1"),
    Equipment("R1", "stand", 25.0, accel=1.0, label="Roughing stand R1"),
    Equipment("E2", "marker", 57.0, label="Edger E2"),
    Equipment("R2", "stand", 60.0, accel=1.0, label="Roughing stand R2"),
    Equipment("SHR", "marker", 175.0, label="Crop shear"),
    Equipment("DS2", "marker", 182.0, label="Finishing descaler"),
    Equipment("F1", "stand", 190.0, accel=1.5, group="FM", label="F1"),
    Equipment("F2", "stand", 195.5, accel=1.5, group="FM", label="F2"),
    Equipment("F3", "stand", 201.0, accel=1.5, group="FM", label="F3"),
    Equipment("F4", "stand", 206.5, accel=1.5, group="FM", label="F4"),
    Equipment("F5", "stand", 212.0, accel=1.5, group="FM", label="F5"),
    Equipment("F6", "stand", 217.5, accel=1.5, group="FM", label="F6"),
    Equipment("F7", "stand", 223.0, accel=1.5, group="FM", label="F7"),
    Equipment("DC1", "coiler", 330.0, accel=0.9, label="Downcoiler 1"),
    Equipment("DC2", "coiler", 348.0, accel=0.9, label="Downcoiler 2"),
]

_SECTIONS = [
    Section(
        "S1",
        x_start=0.0,
        length=25.0,
        label="Furnace to R1",
        events=(
            SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=1.2, direction=FWD),
        ),
    ),
    Section("S2", x_start=25.0, length=35.0, label="R1 to R2"),
    Section(
        "S3",
        x_start=60.0,
        length=115.0,
        label="Transfer table",
        events=(
            SpeedEvent("S3-1", "S3", x_trigger=65.0, v_target=5.0, direction=FWD),
            SpeedEvent("S3-2", "S3", x_trigger=155.0, v_target=1.0, direction=FWD),
        ),
    ),
    Section("S4", x_start=175.0, length=15.0, label="Shear to F1"),
    Section("S5", x_start=190.0, length=170.0, label="Finishing mill to coilers"),
]

# (pass_no, stand, direction, h_in, h_out, w_in, w_out, v_exit, reversing_delay, clearance)
# The reversing delay and clearance describe the reversal that FOLLOWS the pass on
# the same row, so passes 3 and 6 carry none: after them the direction does not change.
_PASSES = [
    (1, "R1", FWD, 220.0, 175.0, 1250.0, 1255.0, 2.50, 6.0, 5.0),
    (2, "R1", REV, 175.0, 135.0, 1255.0, 1260.0, 3.00, 6.0, 5.0),
    (3, "R1", FWD, 135.0, 105.0, 1260.0, 1265.0, 3.50, 0.0, 0.0),
    (4, "R2", FWD, 105.0, 75.0, 1265.0, 1268.0, 3.50, 6.0, 9.0),
    (5, "R2", REV, 75.0, 52.0, 1268.0, 1270.0, 4.00, 6.0, 9.0),
    (6, "R2", FWD, 52.0, 38.0, 1270.0, 1272.0, 4.50, 0.0, 0.0),
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
                # 130 m past F7, as virtual-head travel, the TRoll convention.
                # The same number is used on DC1 and DC2: the zoom is not recomputed
                # as table plus wraps on the assigned mandrel.
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
        coiler_pattern=("DC1", "DC2"),
        gap_min=5.0,
        pacing_scan_min=70.0,
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
            "mill_name": "Example HSM",
            "notes": "Invented data, for demonstration only",
        },
    )
