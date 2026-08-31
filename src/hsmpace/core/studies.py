"""Studi sul pacing: curva gap-vs-pacing, pacing minimo, robustezza.

In modalita' open-loop i pezzi sono disaccoppiati: ogni prodotto si simula una
volta sola e le copie si ottengono traslando la traiettoria nel tempo. Questo
rende trascurabile il costo di scandire centinaia di valori di pacing o di
lanciare migliaia di run Monte Carlo.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .analysis import GapAnalysis, analyse_sequence
from .model import Case, Product, harmonise_tandem_speeds
from .simulate import PieceResult, shift_result, simulate_piece


def base_results(case: Case) -> dict[str, PieceResult]:
    """Una simulazione per prodotto, con rilascio a t = 0."""
    out: dict[str, PieceResult] = {}
    for product_id in dict.fromkeys(case.piece_products):
        out[product_id] = simulate_piece(case, case.product(product_id), 0.0, product_id)
    return out


def sequence(
    case: Case,
    base: dict[str, PieceResult],
    pacing: float,
    jitter: list[float] | None = None,
) -> list[PieceResult]:
    out: list[PieceResult] = []
    for i, product_id in enumerate(case.piece_products):
        offset = i * pacing + (jitter[i] if jitter else 0.0)
        out.append(shift_result(base[product_id], offset, f"#{i + 1}"))
    return out


@dataclass(frozen=True)
class PacingPoint:
    pacing: float
    min_gap: float
    feasible: bool
    t_critical: float | None = None
    x_critical: float | None = None
    section: str = ""
    equipment: str = ""
    pair: str = ""


def _point(case: Case, analyses: list[GapAnalysis], pacing: float) -> PacingPoint:
    gap_min = case.settings.gap_min
    if not analyses:
        return PacingPoint(pacing, float("inf"), True)
    worst = min(analyses, key=lambda a: a.min_gap)
    c = worst.critical
    return PacingPoint(
        pacing=pacing,
        min_gap=worst.min_gap,
        feasible=worst.min_gap >= gap_min,
        t_critical=c.t if c else None,
        x_critical=c.x if c else None,
        section=c.section if c else "",
        equipment=c.equipment if c else "",
        pair=f"{worst.front_id} / {worst.rear_id}",
    )


def gap_vs_pacing(
    case: Case,
    base: dict[str, PieceResult] | None = None,
    pacings: list[float] | None = None,
) -> list[PacingPoint]:
    """Gap minimo della sequenza al variare del pacing.

    E' il grafico piu' utile del tool: il pacing minimo ammissibile si legge
    dal punto in cui la curva incrocia la soglia, e la distanza dalla soglia e'
    il margine con cui si sta lavorando.
    """
    base = base or base_results(case)
    if pacings is None:
        s = case.settings
        steps = max(2, s.pacing_scan_steps)
        span = s.pacing_scan_max - s.pacing_scan_min
        pacings = [s.pacing_scan_min + span * i / (steps - 1) for i in range(steps)]

    out: list[PacingPoint] = []
    for pacing in pacings:
        results = sequence(case, base, pacing)
        analyses = analyse_sequence(results, case.settings.gap_min, case.line)
        out.append(_point(case, analyses, pacing))
    return out


def min_feasible_pacing(
    case: Case,
    base: dict[str, PieceResult] | None = None,
    curve: list[PacingPoint] | None = None,
    tolerance: float = 0.1,
) -> PacingPoint | None:
    """Pacing minimo oltre il quale la sequenza resta sempre ammissibile.

    Con le passate reversibili il gap minimo non e' monotono nel pacing, per
    cui non si applica una bisezione cieca: si scandisce la curva, si prende
    l'ultimo punto non ammissibile e si raffina l'intervallo successivo.
    """
    base = base or base_results(case)
    curve = curve or gap_vs_pacing(case, base)
    if not curve:
        return None

    last_bad = None
    for point in curve:
        if not point.feasible:
            last_bad = point
    if last_bad is None:
        return curve[0]

    after = [p for p in curve if p.pacing > last_bad.pacing]
    if not after:
        return None

    lo, hi = last_bad.pacing, after[0].pacing
    while hi - lo > tolerance:
        mid = 0.5 * (lo + hi)
        analyses = analyse_sequence(
            sequence(case, base, mid), case.settings.gap_min, case.line
        )
        point = _point(case, analyses, mid)
        if point.feasible:
            hi = mid
        else:
            lo = mid

    analyses = analyse_sequence(sequence(case, base, hi), case.settings.gap_min, case.line)
    return _point(case, analyses, hi)


@dataclass(frozen=True)
class MonteCarloResult:
    runs: int
    pacing: float
    violations: int
    min_gaps: tuple[float, ...]
    errors: int = 0

    @property
    def violation_rate(self) -> float:
        return self.violations / self.runs if self.runs else 0.0

    def percentile(self, q: float) -> float:
        if not self.min_gaps:
            return float("nan")
        data = sorted(self.min_gaps)
        idx = min(len(data) - 1, max(0, int(round(q * (len(data) - 1)))))
        return data[idx]

    @property
    def mean(self) -> float:
        return sum(self.min_gaps) / len(self.min_gaps) if self.min_gaps else float("nan")


def perturb_case(case: Case, rng: random.Random) -> Case:
    """Perturbazione delle velocita' di passata e dei tempi morti.

    Le velocita' sono perturbate prima del bilancio di massa, cosi' nel tandem
    conta la sola perturbazione della gabbia master e la schedule resta fisica.
    """
    tol = case.settings.mc_speed_tol_pct / 100.0
    sigma = case.settings.mc_delay_sigma

    products: list[Product] = []
    for product in case.products:
        passes = []
        for rp in product.passes:
            factor = 1.0 + rng.uniform(-tol, tol)
            delay = max(0.0, rp.reversing_delay + rng.gauss(0.0, sigma))
            passes.append(replace(rp, v_exit=rp.v_exit * factor, reversing_delay=delay))
        products.append(replace(product, passes=tuple(passes)))

    perturbed = replace(case, products=tuple(products))
    harmonised, _ = harmonise_tandem_speeds(perturbed)
    return harmonised


def monte_carlo(
    case: Case,
    pacing: float | None = None,
    runs: int | None = None,
    seed: int | None = None,
) -> MonteCarloResult:
    """Probabilita' di violazione del gap con velocita' e tempi morti dispersi.

    Ogni pezzo riceve la sua perturbazione indipendente e un jitter sull'istante
    di rilascio: il pacing nominale non e' mai rispettato al secondo.
    """
    settings = case.settings
    pacing = settings.pacing if pacing is None else pacing
    runs = settings.mc_runs if runs is None else runs
    rng = random.Random(settings.mc_seed if seed is None else seed)

    min_gaps: list[float] = []
    violations = 0
    errors = 0

    for _ in range(runs):
        try:
            results: list[PieceResult] = []
            for i, product_id in enumerate(case.piece_products):
                perturbed = perturb_case(case, rng)
                offset = i * pacing + rng.gauss(0.0, settings.mc_release_sigma)
                res = simulate_piece(
                    perturbed, perturbed.product(product_id), offset, f"#{i + 1}"
                )
                results.append(res)
            analyses = analyse_sequence(results, settings.gap_min, case.line)
        except Exception:  # input estremi generati dal campionamento
            errors += 1
            continue

        if not analyses:
            min_gaps.append(float("inf"))
            continue
        worst = min(a.min_gap for a in analyses)
        min_gaps.append(worst)
        if worst < settings.gap_min:
            violations += 1

    return MonteCarloResult(
        runs=len(min_gaps),
        pacing=pacing,
        violations=violations,
        min_gaps=tuple(min_gaps),
        errors=errors,
    )
