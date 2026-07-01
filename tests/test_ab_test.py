"""Tests for the simulated A/B test helper functions."""

import numpy as np
import pandas as pd

from analysis.ab_test import (
    ExperimentConfig,
    check_assumptions,
    classify_effect_size,
    cohens_d,
    simulate_discount_experiment,
    validate_customer_revenue,
)


def build_customer_revenue() -> pd.DataFrame:
    """Create a small customer revenue fixture.

    Returns:
        DataFrame shaped like the dbt customer mart query output.
    """

    return pd.DataFrame(
        {
            "customer_unique_id": [f"customer_{index}" for index in range(100)],
            "gross_value": np.linspace(50.0, 500.0, 100),
            "order_count": [1] * 100,
            "recency_days": [30] * 100,
            "rfm_segment": ["potential_loyalists"] * 100,
        }
    )


def test_validate_customer_revenue_accepts_required_columns() -> None:
    """Validate that a correctly shaped customer revenue frame passes."""

    validate_customer_revenue(build_customer_revenue())


def test_simulate_discount_experiment_is_reproducible() -> None:
    """Verify random assignment and simulated outcomes are reproducible."""

    customer_revenue = build_customer_revenue()
    config = ExperimentConfig(random_seed=123)

    first_run = simulate_discount_experiment(customer_revenue, config)
    second_run = simulate_discount_experiment(customer_revenue, config)

    pd.testing.assert_series_equal(
        first_run["experiment_group"],
        second_run["experiment_group"],
    )
    pd.testing.assert_series_equal(
        first_run["simulated_gross_value"],
        second_run["simulated_gross_value"],
    )


def test_check_assumptions_selects_welch_for_large_groups() -> None:
    """Confirm large customer-level experiments use Welch's t-test."""

    experiment_data = simulate_discount_experiment(
        build_customer_revenue(),
        ExperimentConfig(random_seed=123),
    )

    assumptions = check_assumptions(
        experiment_data,
        ExperimentConfig(random_seed=123),
    )

    assert assumptions.selected_test == "welch_t_test"


def test_cohens_d_is_positive_when_treatment_mean_is_higher() -> None:
    """Verify effect size direction follows treatment minus control."""

    control_values = np.array([1.0, 2.0, 3.0])
    treatment_values = np.array([2.0, 3.0, 4.0])

    assert cohens_d(control_values, treatment_values) > 0


def test_classify_effect_size_uses_standard_thresholds() -> None:
    """Verify Cohen's d thresholds map to expected practical classes."""

    assert classify_effect_size(0.19) == "negligible"
    assert classify_effect_size(0.2) == "small"
    assert classify_effect_size(0.5) == "medium"
    assert classify_effect_size(0.8) == "large"
