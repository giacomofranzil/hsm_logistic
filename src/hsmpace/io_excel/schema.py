"""Schema of the input workbook: sheet names, columns and units.

Units are fixed here and are not negotiable inside the file: there is no unit
column to fill in. A rigid template is far more robust when the file is passed
around between several people.
"""

from __future__ import annotations

SCHEMA_VERSION = "1"

SHEET_INFO = "Info"
SHEET_LAYOUT = "Layout"
SHEET_SECTIONS = "Sections"
SHEET_PRODUCTS = "Products"
SHEET_PASSES = "PassSchedule"
SHEET_SIM = "Simulation"
SHEET_GUIDE = "Guide"

MAX_EVENTS_PER_SECTION = 7

LAYOUT_COLUMNS = [
    ("equipment_id", "Unique identifier (R1, F7, DC1)"),
    ("kind", "start | stand | coiler | marker"),
    ("x_m", "Absolute position along the line, in metres"),
    (
        "accel_mps2",
        "Acceleration = deceleration, m/s2. Read only on stand rows, where it applies "
        "while the piece is gripped, and on the coiler row, where it is the "
        "deceleration of the tail down to the final speed, including while the "
        "finishing mill is still rolling. Ignored on start and marker rows",
    ),
    ("group", "Tandem group, for example FM for the finishing stands"),
    ("label", "Description shown on the charts"),
]

SECTION_COLUMNS = [
    ("section_id", "Unique identifier of the section"),
    ("label", "Description shown on the charts"),
    ("start_ref", "Reference equipment, 'prev', or empty for an absolute position"),
    ("start_offset_m", "Distance from the reference to the start of the section, m"),
    ("length_m", "Length of the section, m"),
    ("direction", "fwd | rev: direction of travel in which the events apply"),
    ("during_pass", "YES if the event applies while rolling, NO to defer it"),
    ("accel_mps2", "Roller table acceleration in this section, m/s2 (empty = global default)"),
]

SECTION_EVENT_COLUMNS = [
    ("d{}_m", "Distance from the start of the section of speed change {}, m"),
    ("v{}_mps", "New commanded speed {}, m/s"),
    ("a{}_mps2", "Acceleration of change {}, m/s2 (empty = the one of the axis)"),
]

PRODUCT_COLUMNS = [
    ("product_id", "Unique identifier of the product"),
    ("label", "Description"),
    ("grade", "Steel grade"),
    ("slab_thk_mm", "Slab thickness, mm"),
    ("slab_wid_mm", "Slab width, mm"),
    ("slab_len_m", "Slab length, m"),
]

PASS_COLUMNS = [
    ("product_id", "Product this pass belongs to"),
    ("pass_no", "Sequence number of the pass"),
    ("equipment_id", "Stand where the pass takes place"),
    ("direction", "fwd | rev"),
    ("h_in_mm", "Entry thickness, mm"),
    ("h_out_mm", "Exit thickness, mm"),
    ("w_in_mm", "Entry width, mm"),
    ("w_out_mm", "Exit width, mm"),
    ("v_exit_mps", "Material speed at the stand exit, m/s"),
    (
        "reversing_delay_s",
        "Dead time of the reversal that FOLLOWS this pass, s",
    ),
    (
        "reversing_clearance_m",
        "Distance between the stand and the closest extremity when the piece stops for "
        "the reversal that FOLLOWS this pass, m (empty = shortest braking distance)",
    ),
    (
        "approach_v_mps",
        "Speed at which the piece comes back towards THIS pass after a reversal "
        "(empty = entry speed of the pass)",
    ),
    ("master", "YES on the stand that sets the mass flow of the tandem group"),
    ("zoom_pct", "Zoom rolling: speed increase in per cent"),
    ("zoom_trigger_m", "Zoom: travel of the virtual head beyond this stand, m"),
    ("zoom_accel_mps2", "Zoom: acceleration, m/s2 (empty = the one of the axis)"),
]

# columns introduced after the first version of the schema: their absence does
# not invalidate a workbook already in circulation
OPTIONAL_COLUMNS = {"reversing_clearance_m"}

SIM_KEYS = [
    ("pacing_s", 170.0, "Nominal cadence between one piece and the next, s"),
    ("n_pieces", 3, "Number of simulated pieces"),
    ("piece_products", "", "Comma separated product sequence (empty = repeat the first)"),
    ("gap_min_m", 5.0, "Minimum distance allowed between a tail and the next head, m"),
    ("pacing_scan_min_s", 90.0, "Lower bound of the pacing scan, s"),
    ("pacing_scan_max_s", 300.0, "Upper bound of the pacing scan, s"),
    ("pacing_scan_steps", 106, "Number of points in the scan"),
    ("mc_runs", 600, "Number of Monte Carlo runs for the robustness study"),
    ("mc_speed_tol_pct", 2.0, "Tolerance on the pass speeds, +/- %"),
    ("mc_delay_sigma_s", 1.0, "Standard deviation of the dead times, s"),
    ("mc_release_sigma_s", 2.0, "Standard deviation of the release instant, s"),
    ("mc_seed", 20260831, "Seed of the random generator, for reproducible results"),
    ("table_accel_mps2", 1.0, "Default roller table acceleration, m/s2"),
    ("coiler_v_final_mps", 1.0, "Speed the tail must have when it reaches the coiler, m/s"),
    ("max_time_s", 1800.0, "Maximum simulation time of a single piece, s"),
    ("time_axis_down", "YES", "YES for time increasing downwards on the diagram"),
]

GUIDE_TEXT = [
    ("How the model works", True),
    ("", False),
    (
        "The head commands, the tail follows. You describe the speed changes of the "
        "extremity that leads in the current direction of travel; the speed of the "
        "other extremity follows from the mass flow balance of the engaged stands:",
        False,
    ),
    ("    v_trailing = v_leading / product of the lambdas,   lambda = (h_in*w_in)/(h_out*w_out)", False),
    ("", False),
    ("Units are fixed in the file, there is no unit column to fill in:", True),
    ("    positions and lengths in m, thicknesses and widths in mm,", False),
    ("    speeds in m/s, times in s, accelerations in m/s2.", False),
    ("", False),
    ("Sheet Layout: the kind column", True),
    (
        "Every row is one item of equipment placed at an absolute position. The kind "
        "column decides what the model does with it and accepts four values:",
        False,
    ),
    (
        "    start    the point where the piece is released, normally the furnace exit. "
        "Exactly one row must carry it. At release the head sits here and the tail one "
        "slab length further upstream.",
        False,
    ),
    (
        "    stand    a rolling stand. Only these can appear in the PassSchedule sheet, "
        "and their acceleration governs the piece while it is gripped.",
        False,
    ),
    (
        "    coiler   the coiler. The head stops here, and the acceleration on this row "
        "is the deceleration of the tail down to the final speed, used even while the "
        "finishing mill is still rolling.",
        False,
    ),
    (
        "    marker   anything with no dynamics: descalers, edgers, shears. It is only "
        "drawn as a reference line on the charts and its acceleration is ignored.",
        False,
    ),
    ("", False),
    ("Sheet Layout: the group column", True),
    (
        "It is not a comment, it drives the calculation. Stands carrying the same group "
        "label form a tandem, and inside a tandem the pass flagged as master in the "
        "PassSchedule sheet sets the mass flow: the speeds of all the other stands in "
        "the group are RECOMPUTED from it and the ones you entered are only reported as "
        "a deviation. This is deliberate, because between two stands of a tandem the "
        "strip has a fixed length, so inconsistent speeds would describe an impossible "
        "motion.",
        False,
    ),
    (
        "Consequence to keep in mind: emptying the group column switches that protection "
        "off without any error message, and the speeds you entered are used as they are. "
        "Same thing if the group exists but no pass in it is flagged as master.",
        False,
    ),
    ("", False),
    ("Sheet Sections: speed changes", True),
    (
        "Roller tables have no setpoint of their own: the line is divided into sections "
        "defined by whoever fills in the file, possibly shorter than the spacing between "
        "two stands. Each section allows up to 7 speed changes, given as a distance from "
        "the start of the section plus a target speed.",
        False,
    ),
    (
        "The distance is the point where the new speed must be REACHED, not where the "
        "ramp begins: the tool anticipates the ramp by v_new^2 - v_old^2 over twice the "
        "acceleration so that the piece is at speed exactly there. If there is not enough "
        "room the ramp starts as early as it can and the difference is reported.",
        False,
    ),
    (
        "An event whose target position falls while a pass is engaged is deferred to "
        "disengagement, because while rolling it is the mill that commands and not the "
        "roller table. The same applies when a stand still to be engaged lies between the "
        "piece and the target position: a ramp cannot be planned across a pass, the bite "
        "would reset the speed anyway. Put YES in during_pass to override this.",
        False,
    ),
    (
        "If instead only the anticipation reaches back into the rolling zone, while the "
        "target position is already in free running, the ramp does start during the pass "
        "and the tool reports it: it is the mill decelerating ahead of tail-out, which is "
        "a real manoeuvre.",
        False,
    ),
    ("", False),
    ("Accelerations: three sources, one precedence", True),
    (
        "    1. the acceleration written next to a speed change applies to that ramp only, "
        "then the value below takes over again;",
        False,
    ),
    (
        "    2. while the piece is gripped, the acceleration of the stand rolling it, "
        "except during the final slowdown towards the coiler (see below);",
        False,
    ),
    (
        "    3. while the piece is free, the acceleration of the section it is in, or the "
        "global default table_accel_mps2 from the Simulation sheet when the section leaves "
        "it empty.",
        False,
    ),
    (
        "So the braking towards a reversal and the restart afterwards use the roller table "
        "value, because in that moment the bar is moved by the table and not by the mill.",
        False,
    ),
    ("", False),
    ("Reversing roughing", True),
    (
        "The reversing delay and the reversing clearance on a row describe the reversal "
        "that FOLLOWS that pass. Reading the schedule downwards it says: finish this pass, "
        "back off by the clearance, wait for the delay, then go the other way. The last "
        "pass, and any pass followed by another one in the same direction, carry none: a "
        "value written there is ignored and reported as a warning.",
        False,
    ),
    (
        "The clearance is the distance between the stand and the extremity of the piece "
        "closest to it once the piece has stopped, and it is measured from the stand, so "
        "increase it if the real constraint is the edger a few metres before. Leaving it "
        "empty makes the piece stop as soon as the deceleration allows, at v^2/(2a). If "
        "the requested clearance is shorter than that distance the tool reports the one "
        "actually achieved rather than faking an impossible braking.",
        False,
    ),
    (
        "The approach speed instead stays on the row of the pass it belongs to: it is the "
        "speed at which the piece comes back TOWARDS that pass. So for one reversal the "
        "clearance and the delay are on one row and the approach speed on the next.",
        False,
    ),
    ("", False),
    ("Zoom rolling", True),
    (
        "Zoom keeps the opposite convention on purpose, the one of the offline model TRoll: "
        "zoom_trigger_m is the point where the acceleration STARTS, not where the speed is "
        "reached. It is measured from the stand on whose row it is written, and it uses "
        "the virtual head, that is it ignores the fact that the head stops at the coiler: "
        "if the trigger falls beyond the coiler the zoom starts after a few wraps.",
        False,
    ),
    ("", False),
    ("Arrival at the coiler", True),
    (
        "The control starts the slowdown as late as possible, so that the tail reaches "
        "the coiler at coiler_v_final_mps, using the acceleration written on the coiler "
        "row of the Layout sheet. The constraint is on the tail; the command is on the "
        "leading extremity, scaled by the remaining elongation chain: the tail is held "
        "at that deceleration and the mill at that rate times the product of the lambdas "
        "still engaged. At each tail-out the commanded rate steps down, the tail "
        "deceleration stays the same. If the tail is still in the finishing mill when "
        "the latest start arrives, the tandem slows down anyway: that is what the plant "
        "does. If even that is not enough, the tool reports the speed the tail actually "
        "arrives at rather than faking an impossible braking.",
        False,
    ),
    ("", False),
    ("What the model does not do", True),
    (
        "No interlocks and no hold points: the pieces follow their nominal profiles and "
        "the tool reports where the gap drops below the threshold, without stopping the "
        "piece behind. Roller slip neglected, infinite jerk, no thermal model, no coilbox, "
        "no furnace cadence constraint.",
        False,
    ),
]
