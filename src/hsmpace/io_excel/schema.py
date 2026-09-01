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
    ("accel_mps2", "Acceleration = deceleration of the axis, m/s2"),
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
    ("reversing_delay_s", "Dead time ahead of this pass when the direction changes, s"),
    (
        "reversing_clearance_m",
        "Distance between the stand and the closest extremity when the piece stops "
        "to reverse, m (empty = shortest braking distance)",
    ),
    ("approach_v_mps", "Approach speed after the reversal (empty = entry speed)"),
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
    ("Sections and speed events", True),
    (
        "Roller tables have no setpoint of their own: the line is divided into sections "
        "defined by whoever fills in the file, possibly shorter than the spacing between "
        "two stands. Each section allows up to 7 speed changes, given as a distance from "
        "the start of the section plus a target speed.",
        False,
    ),
    (
        "An event that would fire while a pass is engaged is deferred to disengagement, "
        "because while rolling it is the mill that commands, not the roller table. Put "
        "YES in during_pass to make it apply anyway.",
        False,
    ),
    ("", False),
    ("Reversing roughing", True),
    (
        "After tail-out the piece keeps going until the extremity closest to the stand "
        "is reversing_clearance_m metres away from it, where it stops, waits for the "
        "reversing delay of the following pass and restarts in the opposite direction. "
        "The reversing delay must already include screwdown and side guide centring, and "
        "the clearance is measured from the stand, so increase it if the real constraint "
        "is the edger a few metres before.",
        False,
    ),
    (
        "Leaving the clearance empty makes the piece stop as soon as the deceleration "
        "allows, that is at v^2/(2a) from the stand. If the requested clearance is "
        "shorter than that distance the tool reports it rather than faking an impossible "
        "braking.",
        False,
    ),
    ("", False),
    ("Zoom rolling", True),
    (
        "Defined as a percentage speed increase starting when the head has travelled "
        "zoom_trigger_m beyond the given stand. The trigger uses the virtual head, that "
        "is it ignores the fact that the head stops at the coiler: if the trigger falls "
        "beyond the coiler the zoom starts after a few wraps, as in the offline model.",
        False,
    ),
    ("", False),
    ("What the model does not do", True),
    (
        "No interlocks and no hold points: the pieces follow their nominal profiles and "
        "the tool reports where the gap drops below the threshold, without stopping the "
        "piece behind. Roller slip neglected, infinite jerk, no thermal model, no "
        "furnace or coiler cycle constraint.",
        False,
    ),
]
