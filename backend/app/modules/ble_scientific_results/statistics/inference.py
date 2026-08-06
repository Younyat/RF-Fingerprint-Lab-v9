"""Pure statistical-inference primitives for the paper's confirmatory
analyses. Every resampling/permutation function here respects the design's
own clustering: a physical unit (or day, for within-unit contrasts) is
resampled/permuted as a whole block, never an individual burst or window --
bursts within one capture are not independent draws (see burst_records.py,
decision_window_records.py).
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


# ----------------------------------------------------------------------
# Paired contrasts
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class PairedContrast:
    n_pairs: int
    mean_difference: float
    differences: tuple[float, ...]


def paired_contrast(scores_a: Sequence[float], scores_b: Sequence[float]) -> PairedContrast:
    """The observed statistic for a paired comparison (e.g. per-unit balanced
    accuracy of model A vs model B) -- one difference per matched block
    (unit/day/whatever the caller already aggregated to), never per-burst."""
    if len(scores_a) != len(scores_b):
        raise ValueError("LENGTH_MISMATCH")
    if len(scores_a) == 0:
        raise ValueError("NEED_AT_LEAST_ONE_PAIR")
    differences = tuple(a - b for a, b in zip(scores_a, scores_b))
    return PairedContrast(n_pairs=len(differences), mean_difference=sum(differences) / len(differences), differences=differences)


# ----------------------------------------------------------------------
# Exact randomization inference (sign-flip test for paired data)
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class RandomizationTestResult:
    observed_statistic: float
    p_value: float
    n_permutations: int
    exact: bool


_EXACT_ENUMERATION_MAX_N = 20  # 2**20 sign patterns is the practical ceiling for exhaustive enumeration.


def exact_randomization_test(
    differences: Sequence[float], *, statistic: Callable[[Sequence[float]], float] = lambda d: sum(d) / len(d),
    n_monte_carlo: int = 20000, rng: np.random.Generator | None = None,
) -> RandomizationTestResult:
    """Two-sided sign-flip randomization test for paired differences: under
    the null hypothesis of no systematic effect, each pair's sign is
    exchangeable, so the reference distribution is every +/-1 relabeling of
    the observed differences. Enumerates ALL 2**n sign patterns (an exact
    test, not an approximation) when n is small enough; falls back to Monte
    Carlo sampling of sign patterns for larger n, clearly flagged via
    `exact=False`."""
    n = len(differences)
    if n == 0:
        raise ValueError("NEED_AT_LEAST_ONE_DIFFERENCE")
    observed = statistic(differences)
    observed_abs = abs(observed)

    if n <= _EXACT_ENUMERATION_MAX_N:
        count_as_extreme = 0
        total = 0
        for signs in itertools.product((1, -1), repeat=n):
            permuted = [sign * value for sign, value in zip(signs, differences)]
            total += 1
            if abs(statistic(permuted)) >= observed_abs - 1e-12:
                count_as_extreme += 1
        return RandomizationTestResult(observed_statistic=observed, p_value=count_as_extreme / total, n_permutations=total, exact=True)

    rng = rng or np.random.default_rng(12345)
    count_as_extreme = 0
    for _ in range(n_monte_carlo):
        signs = rng.choice([1, -1], size=n)
        permuted = [sign * value for sign, value in zip(signs, differences)]
        if abs(statistic(permuted)) >= observed_abs - 1e-12:
            count_as_extreme += 1
    return RandomizationTestResult(observed_statistic=observed, p_value=count_as_extreme / n_monte_carlo, n_permutations=n_monte_carlo, exact=False)


@dataclass(frozen=True)
class TwoSamplePermutationResult:
    observed_statistic: float
    p_value: float
    n_permutations: int
    exact: bool


_EXACT_TWO_SAMPLE_MAX_COMBINATIONS = 20000


def exact_two_sample_permutation_test(
    values: Sequence[float], group_labels: Sequence[bool], *,
    statistic: Callable[[Sequence[float], Sequence[float]], float] | None = None,
    n_monte_carlo: int = 20000, rng: np.random.Generator | None = None,
) -> TwoSamplePermutationResult:
    """Exact permutation test for a two-group comparison of WHOLE UNITS
    (e.g. which physical units were randomly assigned RESET vs CONTROL) --
    NOT a paired sign-flip test (see exact_randomization_test above for
    that). Enumerates every way to relabel which indices belong to group 1,
    holding both observed group sizes fixed -- the correct null-
    exchangeability structure under a randomized between-unit assignment.
    Falls back to Monte Carlo relabeling when the exact count of
    combinations is impractically large."""
    n = len(values)
    if n != len(group_labels):
        raise ValueError("LENGTH_MISMATCH")
    if statistic is None:
        def statistic(a: Sequence[float], b: Sequence[float]) -> float:
            return (sum(a) / len(a)) - (sum(b) / len(b))
    indices = list(range(n))
    group1_indices = [i for i in indices if group_labels[i]]
    n1 = len(group1_indices)
    if n1 == 0 or n1 == n:
        raise ValueError("NEED_BOTH_GROUPS_NONEMPTY")
    group1_values = [values[i] for i in group1_indices]
    group0_values = [values[i] for i in indices if not group_labels[i]]
    observed = statistic(group1_values, group0_values)
    observed_abs = abs(observed)

    total_combinations = math.comb(n, n1)
    if total_combinations <= _EXACT_TWO_SAMPLE_MAX_COMBINATIONS:
        count_extreme = 0
        for combo in itertools.combinations(indices, n1):
            combo_set = set(combo)
            g1 = [values[i] for i in combo_set]
            g0 = [values[i] for i in indices if i not in combo_set]
            if abs(statistic(g1, g0)) >= observed_abs - 1e-12:
                count_extreme += 1
        return TwoSamplePermutationResult(observed_statistic=observed, p_value=count_extreme / total_combinations, n_permutations=total_combinations, exact=True)

    rng = rng or np.random.default_rng(12345)
    count_extreme = 0
    for _ in range(n_monte_carlo):
        permuted = rng.permutation(n)
        combo_set = set(int(i) for i in permuted[:n1])
        g1 = [values[i] for i in combo_set]
        g0 = [values[i] for i in indices if i not in combo_set]
        if abs(statistic(g1, g0)) >= observed_abs - 1e-12:
            count_extreme += 1
    return TwoSamplePermutationResult(observed_statistic=observed, p_value=count_extreme / n_monte_carlo, n_permutations=n_monte_carlo, exact=False)


@dataclass(frozen=True)
class StratifiedCrossoverTestResult:
    observed_statistic: float
    p_value: float
    n_permutations: int
    exact: bool


_EXACT_STRATIFIED_MAX_TOTAL_COMBINATIONS = 20000


def _crossover_delta_cycle(device_ids: Sequence[str], values_by_device: dict[str, Sequence[float]], labels_by_device: dict[str, Sequence[bool]]) -> float:
    device_effects = []
    for device_id in device_ids:
        values = values_by_device[device_id]
        labels = labels_by_device[device_id]
        reset_values = [value for value, is_reset in zip(values, labels) if is_reset]
        control_values = [value for value, is_reset in zip(values, labels) if not is_reset]
        device_effects.append((sum(reset_values) / len(reset_values)) - (sum(control_values) / len(control_values)))
    return sum(device_effects) / len(device_effects)


def stratified_crossover_permutation_test(
    device_day_values: dict[str, Sequence[float]], device_day_is_reset: dict[str, Sequence[bool]], *,
    n_monte_carlo: int = 20000, rng: np.random.Generator | None = None,
) -> StratifiedCrossoverTestResult:
    """Within-device randomized crossover test (each enrolled device acts as
    its OWN control -- no device is ever permanently assigned RESET or
    CONTROL). The statistic is delta_cycle = mean over devices of
    (mean(D | RESET, device) - mean(D | CONTROL, device)), one number per
    device averaged with equal device weight. The null distribution
    re-permutes WHICH of each device's own days are labeled RESET --
    stratified BY DEVICE, preserving each device's own RESET/CONTROL day
    count (its balance), never pooling days across devices. Enumerates the
    exact joint permutation space when small enough (small pilot-sized day
    counts); falls back to Monte Carlo relabeling for realistic campaign
    sizes, where the joint space across 5+ devices is intractably large."""
    device_ids = list(device_day_values.keys())
    if not device_ids:
        raise ValueError("NEED_AT_LEAST_ONE_DEVICE")
    for device_id in device_ids:
        values = device_day_values[device_id]
        labels = device_day_is_reset[device_id]
        if len(values) != len(labels):
            raise ValueError(f"LENGTH_MISMATCH:{device_id}")
        if not any(labels) or all(labels):
            raise ValueError(f"DEVICE_NEEDS_BOTH_ARMS:{device_id}")

    observed = _crossover_delta_cycle(device_ids, device_day_values, device_day_is_reset)
    observed_abs = abs(observed)

    per_device_combo_counts = [math.comb(len(device_day_is_reset[d]), sum(device_day_is_reset[d])) for d in device_ids]
    total_joint = 1
    for count in per_device_combo_counts:
        total_joint *= count
        if total_joint > _EXACT_STRATIFIED_MAX_TOTAL_COMBINATIONS:
            break

    if total_joint <= _EXACT_STRATIFIED_MAX_TOTAL_COMBINATIONS:
        per_device_patterns: list[list[list[bool]]] = []
        for device_id in device_ids:
            n_days = len(device_day_is_reset[device_id])
            n_reset = sum(device_day_is_reset[device_id])
            patterns = []
            for combo in itertools.combinations(range(n_days), n_reset):
                pattern = [False] * n_days
                for index in combo:
                    pattern[index] = True
                patterns.append(pattern)
            per_device_patterns.append(patterns)
        count_extreme = 0
        total = 0
        for joint in itertools.product(*per_device_patterns):
            labels_by_device = {device_id: joint[i] for i, device_id in enumerate(device_ids)}
            permuted = _crossover_delta_cycle(device_ids, device_day_values, labels_by_device)
            total += 1
            if abs(permuted) >= observed_abs - 1e-12:
                count_extreme += 1
        return StratifiedCrossoverTestResult(observed_statistic=observed, p_value=count_extreme / total, n_permutations=total, exact=True)

    rng = rng or np.random.default_rng(12345)
    count_extreme = 0
    for _ in range(n_monte_carlo):
        labels_by_device = {}
        for device_id in device_ids:
            shuffled = list(device_day_is_reset[device_id])
            rng.shuffle(shuffled)
            labels_by_device[device_id] = shuffled
        permuted = _crossover_delta_cycle(device_ids, device_day_values, labels_by_device)
        if abs(permuted) >= observed_abs - 1e-12:
            count_extreme += 1
    return StratifiedCrossoverTestResult(observed_statistic=observed, p_value=count_extreme / n_monte_carlo, n_permutations=n_monte_carlo, exact=False)


# ----------------------------------------------------------------------
# Hierarchical (cluster) bootstrap
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class BootstrapCiResult:
    point_estimate: float
    ci_low: float
    ci_high: float
    n_resamples: int
    confidence_level: float


def hierarchical_cluster_bootstrap(
    cluster_values: Sequence[Sequence[float]], *, statistic: Callable[[Sequence[float]], float] = lambda values: sum(values) / len(values),
    n_resamples: int = 5000, confidence_level: float = 0.95, rng: np.random.Generator | None = None,
) -> BootstrapCiResult:
    """Resamples WHOLE clusters (e.g. physical units, each holding its own
    list of per-capture/per-window scores) with replacement -- never
    resamples individual observations across cluster boundaries, so the
    percentile CI this returns correctly reflects between-cluster
    variability instead of pretending every observation is independent."""
    n_clusters = len(cluster_values)
    if n_clusters == 0:
        raise ValueError("NEED_AT_LEAST_ONE_CLUSTER")
    rng = rng or np.random.default_rng(12345)
    flat_all = [value for cluster in cluster_values for value in cluster]
    point_estimate = statistic(flat_all)

    resample_statistics = np.empty(n_resamples, dtype=float)
    cluster_indices = np.arange(n_clusters)
    for i in range(n_resamples):
        chosen = rng.choice(cluster_indices, size=n_clusters, replace=True)
        pooled: list[float] = []
        for cluster_index in chosen:
            pooled.extend(cluster_values[cluster_index])
        resample_statistics[i] = statistic(pooled)

    alpha = 1.0 - confidence_level
    ci_low, ci_high = np.quantile(resample_statistics, [alpha / 2, 1 - alpha / 2])
    return BootstrapCiResult(point_estimate=point_estimate, ci_low=float(ci_low), ci_high=float(ci_high), n_resamples=n_resamples, confidence_level=confidence_level)


# ----------------------------------------------------------------------
# Holm-Bonferroni step-down correction
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class HolmResult:
    p_values: tuple[float, ...]
    adjusted_p_values: tuple[float, ...]
    reject: tuple[bool, ...]


def holm_correction(p_values: Sequence[float], *, alpha: float = 0.05) -> HolmResult:
    """The classic Holm (1979) step-down procedure, in the original
    input order. Adjusted p-values follow the standard "successive
    maximum" definition: adj_p_(i) = max(adj_p_(i-1), (m-i+1)*p_(i)),
    clipped to 1.0 -- monotone non-decreasing by construction, and a
    hypothesis is rejected iff its adjusted p-value <= alpha."""
    m = len(p_values)
    if m == 0:
        raise ValueError("NEED_AT_LEAST_ONE_P_VALUE")
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted_sorted = [0.0] * m
    running_max = 0.0
    for rank, original_index in enumerate(order):
        raw = (m - rank) * p_values[original_index]
        running_max = max(running_max, raw)
        adjusted_sorted[rank] = min(running_max, 1.0)
    adjusted = [0.0] * m
    for rank, original_index in enumerate(order):
        adjusted[original_index] = adjusted_sorted[rank]
    reject = tuple(value <= alpha for value in adjusted)
    return HolmResult(p_values=tuple(p_values), adjusted_p_values=tuple(adjusted), reject=reject)


# ----------------------------------------------------------------------
# Non-inferiority
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class NonInferiorityResult:
    mean_difference: float
    ci_low: float
    margin: float
    non_inferior: bool


def non_inferiority_test(differences: Sequence[float], *, margin: float, confidence_level: float = 0.95) -> NonInferiorityResult:
    """Standard one-sided non-inferiority test on paired differences
    (new - reference): non-inferiority is concluded iff the lower bound of
    a one-sided (1-alpha) CI for the mean difference exceeds -margin (the
    pre-registered, ALWAYS-negative-signed tolerance for how much worse the
    new arm may be). Uses a t-distribution CI (Welch-style single-sample
    CI on the paired differences), the same construction paired t-tests
    use."""
    n = len(differences)
    if n < 2:
        raise ValueError("NEED_AT_LEAST_TWO_PAIRED_DIFFERENCES")
    if margin <= 0:
        raise ValueError("MARGIN_MUST_BE_POSITIVE:this is a tolerance magnitude, sign is applied internally")
    mean_difference = sum(differences) / n
    variance = sum((value - mean_difference) ** 2 for value in differences) / (n - 1)
    standard_error = math.sqrt(variance / n)
    alpha = 1.0 - confidence_level
    t_critical = _t_quantile(1 - alpha, df=n - 1)
    ci_low = mean_difference - t_critical * standard_error
    return NonInferiorityResult(mean_difference=mean_difference, ci_low=ci_low, margin=margin, non_inferior=ci_low > -margin)


def _t_quantile(p: float, *, df: int) -> float:
    """One-sided Student's-t quantile without a scipy dependency, via the
    Cornish-Fisher expansion around the normal quantile -- accurate to
    within ~1e-3 for df >= 5 and p in [0.9, 0.995], the practical range
    non-inferiority testing in this module uses. Verified against textbook
    t-tables in this module's own tests."""
    z = _normal_quantile(p)
    g1 = (z**3 + z) / 4
    g2 = (5 * z**5 + 16 * z**3 + 3 * z) / 96
    g3 = (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384
    g4 = (79 * z**9 + 776 * z**7 + 1482 * z**5 - 1920 * z**3 - 945 * z) / 92160
    return z + g1 / df + g2 / df**2 + g3 / df**3 + g4 / df**4


def _normal_quantile(p: float) -> float:
    """Standard normal quantile (inverse CDF) via Acklam's rational
    approximation -- max absolute error ~1.15e-9, no scipy dependency."""
    if not 0 < p < 1:
        raise ValueError("P_OUT_OF_RANGE")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


# ----------------------------------------------------------------------
# Risk-coverage
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class RiskCoveragePoint:
    coverage: float
    risk: float
    threshold: float


def risk_coverage_curve(confidence_scores: Sequence[float], correct: Sequence[bool]) -> list[RiskCoveragePoint]:
    """Standard selective-prediction risk-coverage curve (El-Yaniv & Wiener,
    2010): sort trials by DESCENDING confidence, and at each prefix length k
    (the k most-confident trials), report coverage=k/n and risk=error rate
    among those k trials. One point per distinct confidence value (ties
    grouped so `threshold` is a real, achievable operating point)."""
    if len(confidence_scores) != len(correct):
        raise ValueError("LENGTH_MISMATCH")
    n = len(confidence_scores)
    if n == 0:
        raise ValueError("NEED_AT_LEAST_ONE_TRIAL")
    order = sorted(range(n), key=lambda i: confidence_scores[i], reverse=True)
    points: list[RiskCoveragePoint] = []
    cumulative_errors = 0
    accepted = 0
    i = 0
    while i < n:
        threshold = confidence_scores[order[i]]
        j = i
        while j < n and confidence_scores[order[j]] == threshold:
            accepted += 1
            if not correct[order[j]]:
                cumulative_errors += 1
            j += 1
        points.append(RiskCoveragePoint(coverage=accepted / n, risk=cumulative_errors / accepted, threshold=threshold))
        i = j
    return points
