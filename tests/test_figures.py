"""Checks on the Plotly figures, including axis scaling."""

from __future__ import annotations

from hsmpace.core.analysis import analyse_sequence
from hsmpace.core.model import harmonise_tandem_speeds
from hsmpace.core.studies import base_results, sequence
from hsmpace.example import example_case
from hsmpace.viz.figures import gap_figure


def test_the_gap_chart_y_axis_follows_the_data_not_a_million_metres():
    """A violation band from y=-1e6 used to squash every curve onto the zero line."""
    case, _ = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)
    assert analyses

    fig = gap_figure(analyses, case.settings.gap_min)
    y_lo, y_hi = fig.layout.yaxis.range
    assert y_lo > -50
    assert y_hi < 5_000
    assert y_hi - y_lo > 10

    mins = [a.min_gap for a in analyses]
    assert y_lo < min(mins)
    assert y_hi > max(mins)
