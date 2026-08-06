"""Known-value regression tests for statistics/inference.py."""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.statistics.inference import (
    _normal_quantile,
    _t_quantile,
    exact_randomization_test,
    exact_two_sample_permutation_test,
    hierarchical_cluster_bootstrap,
    holm_correction,
    non_inferiority_test,
    paired_contrast,
    risk_coverage_curve,
)


def test_paired_contrast_hand_computed():
    result = paired_contrast([0.8, 0.9, 0.7], [0.6, 0.7, 0.5])
    assert result.n_pairs == 3
    assert result.mean_difference == pytest.approx(0.2)
    assert result.differences == pytest.approx((0.2, 0.2, 0.2))


def test_exact_randomization_two_sided_p_value_hand_computed():
    # n=3, all differences identical and positive: only the all-plus and
    # all-minus sign patterns reach the observed magnitude -> p = 2/8.
    result = exact_randomization_test([1.0, 1.0, 1.0])
    assert result.exact is True
    assert result.n_permutations == 8
    assert result.p_value == pytest.approx(0.25)


def test_exact_randomization_single_pair_can_never_reject():
    result = exact_randomization_test([5.0])
    assert result.n_permutations == 2
    assert result.p_value == pytest.approx(1.0)


def test_exact_randomization_zero_effect_gives_large_p_value():
    result = exact_randomization_test([1.0, -1.0, 1.0, -1.0])
    assert result.observed_statistic == pytest.approx(0.0)
    assert result.p_value == pytest.approx(1.0)  # every sign pattern is at least as extreme as 0


def test_hierarchical_bootstrap_point_estimate_is_the_pooled_mean():
    clusters = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    result = hierarchical_cluster_bootstrap(clusters, n_resamples=500, rng=None)
    assert result.point_estimate == pytest.approx(3.5)
    assert result.ci_low <= result.point_estimate <= result.ci_high
    assert result.n_resamples == 500


def test_hierarchical_bootstrap_is_reproducible_with_a_fixed_seed():
    import numpy as np
    clusters = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [10.0, 12.0]]
    result_a = hierarchical_cluster_bootstrap(clusters, n_resamples=300, rng=np.random.default_rng(7))
    result_b = hierarchical_cluster_bootstrap(clusters, n_resamples=300, rng=np.random.default_rng(7))
    assert result_a.ci_low == pytest.approx(result_b.ci_low)
    assert result_a.ci_high == pytest.approx(result_b.ci_high)


def test_hierarchical_bootstrap_ignores_within_cluster_ordering_only_resamples_clusters():
    # A single-cluster degenerate case: every resample is identical to the
    # full sample (resampling "3 clusters with replacement" from 1 cluster
    # always yields that same cluster three times over) -> zero-width CI.
    clusters = [[1.0, 2.0, 3.0]]
    result = hierarchical_cluster_bootstrap(clusters, n_resamples=200)
    assert result.ci_low == pytest.approx(result.ci_high)
    assert result.ci_low == pytest.approx(2.0)


def test_exact_two_sample_permutation_hand_computed():
    # Values 0,0,0 in group1 vs 10,10 in group0: the observed partition is
    # the UNIQUE most-extreme split among C(5,3)=10 possible relabelings
    # (any other combo mixes at least one 0 into group0 or one 10 into
    # group1), so p = 1/10 exactly.
    values = [0.0, 0.0, 0.0, 10.0, 10.0]
    group_labels = [True, True, True, False, False]
    result = exact_two_sample_permutation_test(values, group_labels)
    assert result.exact is True
    assert result.n_permutations == 10
    assert result.observed_statistic == pytest.approx(-10.0)
    assert result.p_value == pytest.approx(0.1)


def test_exact_two_sample_permutation_identical_values_gives_p_one():
    values = [5.0, 5.0, 5.0, 5.0]
    group_labels = [True, True, False, False]
    result = exact_two_sample_permutation_test(values, group_labels)
    assert result.observed_statistic == pytest.approx(0.0)
    assert result.p_value == pytest.approx(1.0)


def test_exact_two_sample_permutation_requires_both_groups_nonempty():
    with pytest.raises(ValueError):
        exact_two_sample_permutation_test([1.0, 2.0], [True, True])


def test_holm_correction_textbook_example():
    p_values = [0.01, 0.02, 0.03, 0.20]
    result = holm_correction(p_values, alpha=0.05)
    assert result.adjusted_p_values == pytest.approx((0.04, 0.06, 0.06, 0.20))
    assert result.reject == (True, False, False, False)


def test_holm_correction_is_order_independent_modulo_permutation():
    permuted = [0.20, 0.01, 0.03, 0.02]
    result = holm_correction(permuted, alpha=0.05)
    assert result.adjusted_p_values == pytest.approx((0.20, 0.04, 0.06, 0.06))
    assert result.reject == (False, True, False, False)


def test_holm_correction_adjusted_p_values_are_monotone_in_sorted_order():
    p_values = [0.5, 0.001, 0.3, 0.02, 0.04]
    result = holm_correction(p_values)
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    adjusted_sorted = [result.adjusted_p_values[i] for i in order]
    assert adjusted_sorted == sorted(adjusted_sorted)


def test_normal_quantile_matches_known_reference_values():
    assert _normal_quantile(0.975) == pytest.approx(1.959964, abs=1e-4)
    assert _normal_quantile(0.5) == pytest.approx(0.0, abs=1e-6)
    assert _normal_quantile(0.95) == pytest.approx(1.644854, abs=1e-4)


def test_t_quantile_matches_known_table_values_at_moderate_and_large_df():
    assert _t_quantile(0.95, df=30) == pytest.approx(1.6973, abs=0.005)
    assert _t_quantile(0.95, df=10) == pytest.approx(1.8125, abs=0.005)


def test_non_inferiority_zero_variance_case():
    result = non_inferiority_test([0.0, 0.0, 0.0, 0.0, 0.0], margin=1.0)
    assert result.mean_difference == pytest.approx(0.0)
    assert result.ci_low == pytest.approx(0.0)
    assert result.non_inferior is True


def test_non_inferiority_rejects_when_ci_crosses_the_margin():
    # Large negative differences with a tight margin: cannot conclude
    # non-inferiority.
    result = non_inferiority_test([-5.0, -6.0, -4.0, -5.5, -4.5], margin=0.5)
    assert result.non_inferior is False


def test_non_inferiority_requires_positive_margin():
    with pytest.raises(ValueError):
        non_inferiority_test([0.0, 0.1], margin=-0.1)


def test_risk_coverage_curve_hand_computed():
    points = risk_coverage_curve([0.9, 0.8, 0.7, 0.6], [True, False, True, True])
    assert [round(p.coverage, 4) for p in points] == [0.25, 0.5, 0.75, 1.0]
    assert [round(p.risk, 4) for p in points] == [0.0, 0.5, 0.3333, 0.25]


def test_risk_coverage_curve_groups_tied_confidence_scores():
    points = risk_coverage_curve([0.9, 0.9, 0.5], [True, False, True])
    assert len(points) == 2
    assert points[0].coverage == pytest.approx(2 / 3)
    assert points[0].risk == pytest.approx(0.5)
    assert points[1].coverage == pytest.approx(1.0)
    assert points[1].risk == pytest.approx(1 / 3)
