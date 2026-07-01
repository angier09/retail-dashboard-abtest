"""Simulate and analyze a customer-level discount campaign A/B test.

The Olist dataset does not contain real experiment assignments, campaign
eligibility, or discount exposure logs. This module therefore creates a clearly
synthetic experiment on top of observed delivered customer revenue from the dbt
mart layer. Customers are randomized once, treatment customers receive a
simulated incremental revenue lift, and the resulting groups are compared with
a statistically documented test.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
from scipy import stats
from statsmodels.stats.weightstats import CompareMeans, DescrStatsW


DEFAULT_DATABASE_PATH = Path(
    os.getenv("RETAILPULSE_DUCKDB_PATH", "retailpulse.duckdb")
)
DEFAULT_OUTPUT_DIR = Path(
    os.getenv("RETAILPULSE_AB_TEST_OUTPUT_DIR", "analysis/outputs")
)
DEFAULT_RANDOM_SEED = 20260701
DEFAULT_TREATMENT_PROBABILITY = 0.5
DEFAULT_SYNTHETIC_LIFT = 0.08
DEFAULT_NOISE_STANDARD_DEVIATION = 0.03
DEFAULT_CONFIDENCE_LEVEL = 0.95
DEFAULT_ALPHA = 1.0 - DEFAULT_CONFIDENCE_LEVEL
MINIMUM_T_TEST_SAMPLE_SIZE = 30
NORMALITY_SAMPLE_SIZE = 5_000
BOOTSTRAP_ITERATIONS = 2_000
PLOT_BIN_COUNT = 80
NEGLIGIBLE_EFFECT_THRESHOLD = 0.2
SMALL_EFFECT_THRESHOLD = 0.5
MEDIUM_EFFECT_THRESHOLD = 0.8
CUSTOMER_QUERY = """
select
    customer_unique_id,
    gross_value,
    order_count,
    recency_days,
    rfm_segment
from main_marts.dim_customer
where gross_value > 0
order by customer_unique_id
"""


@dataclass(frozen=True)
class ExperimentConfig:
    """Configuration values controlling the synthetic experiment.

    Attributes:
        database_path: DuckDB database containing dbt mart tables.
        output_dir: Directory where plot and JSON summaries are written.
        random_seed: Seed used for reproducible customer randomization.
        treatment_probability: Probability of assigning a customer to treatment.
        synthetic_lift: Revenue lift applied to treatment customers.
        noise_standard_deviation: Customer-level random noise around outcomes.
        confidence_level: Confidence level used for interval estimates.
    """

    database_path: Path = DEFAULT_DATABASE_PATH
    output_dir: Path = DEFAULT_OUTPUT_DIR
    random_seed: int = DEFAULT_RANDOM_SEED
    treatment_probability: float = DEFAULT_TREATMENT_PROBABILITY
    synthetic_lift: float = DEFAULT_SYNTHETIC_LIFT
    noise_standard_deviation: float = DEFAULT_NOISE_STANDARD_DEVIATION
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL


@dataclass(frozen=True)
class AssumptionCheck:
    """Statistical assumption diagnostics for the simulated experiment.

    Attributes:
        control_sample_size: Number of control customers.
        treatment_sample_size: Number of treatment customers.
        control_shapiro_p_value: Shapiro-Wilk p-value for sampled controls.
        treatment_shapiro_p_value: Shapiro-Wilk p-value for sampled treatments.
        levene_p_value: Levene p-value for equality of variance.
        selected_test: Name of the statistical test selected for analysis.
        rationale: Plain-language rationale for the test selection.
    """

    control_sample_size: int
    treatment_sample_size: int
    control_shapiro_p_value: float
    treatment_shapiro_p_value: float
    levene_p_value: float
    selected_test: str
    rationale: str


@dataclass(frozen=True)
class TestResult:
    """Statistical result comparing treatment and control groups.

    Attributes:
        control_mean: Mean simulated revenue per control customer.
        treatment_mean: Mean simulated revenue per treatment customer.
        mean_difference: Treatment mean minus control mean.
        relative_lift: Mean difference divided by the control mean.
        p_value: P-value from the selected hypothesis test.
        confidence_interval_low: Lower bound for the mean difference interval.
        confidence_interval_high: Upper bound for the mean difference interval.
        effect_size: Cohen's d standardized mean difference.
        is_significant: Whether the p-value is below alpha.
    """

    control_mean: float
    treatment_mean: float
    mean_difference: float
    relative_lift: float
    p_value: float
    confidence_interval_low: float
    confidence_interval_high: float
    effect_size: float
    is_significant: bool


@dataclass(frozen=True)
class ExperimentReport:
    """Complete A/B test report for printing and downstream consumption.

    Attributes:
        config: Experiment settings used for the run.
        assumptions: Statistical assumption checks.
        result: Hypothesis test result.
        statistical_summary: Plain-language statistical and practical summary.
        interpretation: Stakeholder-readable conclusion.
        plot_path: HTML plot written for visual review.
        summary_path: JSON summary written for reproducibility.
    """

    config: ExperimentConfig
    assumptions: AssumptionCheck
    result: TestResult
    statistical_summary: str
    interpretation: str
    plot_path: Path
    summary_path: Path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the A/B test script.

    Returns:
        Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description="Run the RetailPulse simulated discount A/B test."
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help="Path to the DuckDB database produced by dbt.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where output artifacts should be written.",
    )
    parser.add_argument(
        "--synthetic-lift",
        type=float,
        default=DEFAULT_SYNTHETIC_LIFT,
        help="Treatment revenue lift to simulate, expressed as a decimal.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help="Random seed for reproducible assignment and simulated noise.",
    )
    return parser.parse_args()


def load_customer_revenue(database_path: Path) -> pd.DataFrame:
    """Load delivered customer revenue from the dbt mart layer.

    Args:
        database_path: Path to the DuckDB database containing mart tables.

    Returns:
        DataFrame with customer-level revenue and segmentation fields.

    Raises:
        FileNotFoundError: If the DuckDB database does not exist.
        ValueError: If the query returns no usable customer records.
    """

    if not database_path.exists():
        raise FileNotFoundError(
            f"DuckDB database not found at {database_path}. "
            "Run dbt before running the A/B test."
        )

    with duckdb.connect(str(database_path), read_only=True) as connection:
        customer_revenue = connection.execute(CUSTOMER_QUERY).fetchdf()

    validate_customer_revenue(customer_revenue)
    return customer_revenue


def validate_customer_revenue(customer_revenue: pd.DataFrame) -> None:
    """Validate the customer revenue input used for simulation.

    Args:
        customer_revenue: DataFrame loaded from the customer mart.

    Raises:
        ValueError: If required columns are missing or no positive revenue
            observations are available.
    """

    required_columns = {
        "customer_unique_id",
        "gross_value",
        "order_count",
        "recency_days",
        "rfm_segment",
    }
    missing_columns = required_columns.difference(customer_revenue.columns)
    if missing_columns:
        sorted_columns = ", ".join(sorted(missing_columns))
        raise ValueError(f"Customer revenue data is missing: {sorted_columns}")

    if customer_revenue.empty:
        raise ValueError("Customer revenue data is empty.")

    if (customer_revenue["gross_value"] <= 0).all():
        raise ValueError("Customer revenue data has no positive gross revenue.")


def simulate_discount_experiment(
    customer_revenue: pd.DataFrame,
    config: ExperimentConfig,
) -> pd.DataFrame:
    """Randomize customers and simulate a discount-campaign revenue outcome.

    The simulated outcome keeps each customer's real delivered gross revenue as
    the baseline, then applies random customer-level noise to both groups and a
    fixed incremental lift to treatment customers. Randomizing by customer keeps
    repeat purchasers from appearing in both groups.

    Args:
        customer_revenue: Customer-level revenue records from `dim_customer`.
        config: Experiment settings controlling randomization and effect size.

    Returns:
        DataFrame with experiment assignment and simulated outcome columns.
    """

    rng = np.random.default_rng(config.random_seed)
    row_count = len(customer_revenue)
    assignments = rng.choice(
        ["control", "treatment"],
        size=row_count,
        p=[
            1.0 - config.treatment_probability,
            config.treatment_probability,
        ],
    )
    random_noise = rng.normal(
        loc=0.0,
        scale=config.noise_standard_deviation,
        size=row_count,
    )
    treatment_effect = np.where(
        assignments == "treatment",
        config.synthetic_lift,
        0.0,
    )

    experiment_data = customer_revenue.copy()
    experiment_data["experiment_group"] = assignments
    experiment_data["baseline_gross_value"] = experiment_data["gross_value"]
    experiment_data["simulated_gross_value"] = (
        experiment_data["baseline_gross_value"]
        * (1.0 + random_noise + treatment_effect)
    ).clip(lower=0.0)
    experiment_data["simulated_incremental_value"] = (
        experiment_data["simulated_gross_value"]
        - experiment_data["baseline_gross_value"]
    )
    return experiment_data


def check_assumptions(
    experiment_data: pd.DataFrame,
    config: ExperimentConfig,
) -> AssumptionCheck:
    """Check assumptions and choose the appropriate statistical test.

    The KPI is continuous revenue per randomized customer, so a chi-square test
    is not appropriate. With very large group sizes, Welch's t-test is selected
    because the central limit theorem supports inference on mean differences
    even when raw retail spend is skewed, and Welch's version does not assume
    equal group variances.

    Args:
        experiment_data: Simulated customer-level experiment data.
        config: Experiment settings used for random sampling.

    Returns:
        Assumption diagnostics and selected statistical test.
    """

    control_values = get_group_values(experiment_data, "control")
    treatment_values = get_group_values(experiment_data, "treatment")
    rng = np.random.default_rng(config.random_seed)
    control_sample = sample_for_normality(control_values, rng)
    treatment_sample = sample_for_normality(treatment_values, rng)
    control_shapiro_p_value = float(stats.shapiro(control_sample).pvalue)
    treatment_shapiro_p_value = float(stats.shapiro(treatment_sample).pvalue)
    levene_p_value = float(
        stats.levene(control_values, treatment_values, center="median").pvalue
    )

    if (
        len(control_values) >= MINIMUM_T_TEST_SAMPLE_SIZE
        and len(treatment_values) >= MINIMUM_T_TEST_SAMPLE_SIZE
    ):
        selected_test = "welch_t_test"
        rationale = (
            "The KPI is continuous revenue per randomized customer. Both groups "
            "are much larger than 30, so Welch's t-test is appropriate for a "
            "mean comparison under the central limit theorem, while allowing "
            "unequal variances common in retail spend."
        )
    else:
        selected_test = "mann_whitney_u"
        rationale = (
            "At least one group has fewer than 30 customers, so the script "
            "falls back to a non-parametric Mann-Whitney U test."
        )

    return AssumptionCheck(
        control_sample_size=len(control_values),
        treatment_sample_size=len(treatment_values),
        control_shapiro_p_value=control_shapiro_p_value,
        treatment_shapiro_p_value=treatment_shapiro_p_value,
        levene_p_value=levene_p_value,
        selected_test=selected_test,
        rationale=rationale,
    )


def sample_for_normality(
    values: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Sample values for Shapiro-Wilk normality diagnostics.

    Args:
        values: Full numeric group values.
        rng: NumPy random number generator for reproducible sampling.

    Returns:
        Values capped at the configured normality diagnostic sample size.
    """

    if len(values) <= NORMALITY_SAMPLE_SIZE:
        return values
    sample_indexes = rng.choice(
        len(values),
        size=NORMALITY_SAMPLE_SIZE,
        replace=False,
    )
    return values[sample_indexes]


def get_group_values(
    experiment_data: pd.DataFrame,
    group_name: str,
) -> np.ndarray:
    """Extract simulated gross revenue values for one experiment group.

    Args:
        experiment_data: Simulated customer-level experiment data.
        group_name: Experiment group name to filter.

    Returns:
        NumPy array of simulated gross revenue values.

    Raises:
        ValueError: If the requested group has no observations.
    """

    values = experiment_data.loc[
        experiment_data["experiment_group"] == group_name,
        "simulated_gross_value",
    ].to_numpy(dtype=float)
    if len(values) == 0:
        raise ValueError(f"Experiment group has no observations: {group_name}")
    return values


def run_hypothesis_test(
    experiment_data: pd.DataFrame,
    assumptions: AssumptionCheck,
    confidence_level: float,
) -> TestResult:
    """Run the selected hypothesis test for treatment versus control.

    Args:
        experiment_data: Simulated customer-level experiment data.
        assumptions: Output of assumption checks and test selection.
        confidence_level: Confidence level for the mean difference interval.

    Returns:
        Statistical result with p-value, confidence interval, and effect size.
    """

    if assumptions.selected_test == "welch_t_test":
        return run_welch_t_test(experiment_data, confidence_level)
    return run_mann_whitney_test(experiment_data, confidence_level)


def run_welch_t_test(
    experiment_data: pd.DataFrame,
    confidence_level: float,
) -> TestResult:
    """Compare treatment and control means with Welch's t-test.

    Args:
        experiment_data: Simulated customer-level experiment data.
        confidence_level: Confidence level for the mean difference interval.

    Returns:
        Statistical result for the continuous revenue KPI.
    """

    control_values = get_group_values(experiment_data, "control")
    treatment_values = get_group_values(experiment_data, "treatment")
    test_result = stats.ttest_ind(
        treatment_values,
        control_values,
        equal_var=False,
        alternative="two-sided",
    )
    confidence_interval = CompareMeans(
        DescrStatsW(treatment_values),
        DescrStatsW(control_values),
    ).tconfint_diff(
        alpha=1.0 - confidence_level,
        usevar="unequal",
    )
    return build_test_result(
        control_values=control_values,
        treatment_values=treatment_values,
        p_value=float(test_result.pvalue),
        confidence_interval=confidence_interval,
        alpha=1.0 - confidence_level,
    )


def run_mann_whitney_test(
    experiment_data: pd.DataFrame,
    confidence_level: float,
) -> TestResult:
    """Compare groups with Mann-Whitney U when samples are too small.

    Args:
        experiment_data: Simulated customer-level experiment data.
        confidence_level: Confidence level requested for reporting.

    Returns:
        Statistical result with a bootstrap confidence interval for the mean
        difference, allowing the report shape to stay consistent.
    """

    control_values = get_group_values(experiment_data, "control")
    treatment_values = get_group_values(experiment_data, "treatment")
    test_result = stats.mannwhitneyu(
        treatment_values,
        control_values,
        alternative="two-sided",
    )
    confidence_interval = bootstrap_mean_difference_interval(
        control_values,
        treatment_values,
        confidence_level,
    )
    return build_test_result(
        control_values=control_values,
        treatment_values=treatment_values,
        p_value=float(test_result.pvalue),
        confidence_interval=confidence_interval,
        alpha=1.0 - confidence_level,
    )


def bootstrap_mean_difference_interval(
    control_values: np.ndarray,
    treatment_values: np.ndarray,
    confidence_level: float,
) -> tuple[float, float]:
    """Estimate a bootstrap interval for treatment-control mean difference.

    Args:
        control_values: Control group KPI values.
        treatment_values: Treatment group KPI values.
        confidence_level: Confidence level for percentile interval.

    Returns:
        Lower and upper confidence interval bounds.
    """

    rng = np.random.default_rng(DEFAULT_RANDOM_SEED)
    differences = np.empty(BOOTSTRAP_ITERATIONS)
    for iteration in range(BOOTSTRAP_ITERATIONS):
        control_sample = rng.choice(
            control_values,
            size=len(control_values),
            replace=True,
        )
        treatment_sample = rng.choice(
            treatment_values,
            size=len(treatment_values),
            replace=True,
        )
        differences[iteration] = treatment_sample.mean() - control_sample.mean()

    alpha = 1.0 - confidence_level
    lower_percentile = 100.0 * (alpha / 2.0)
    upper_percentile = 100.0 * (1.0 - alpha / 2.0)
    lower_bound, upper_bound = np.percentile(
        differences,
        [lower_percentile, upper_percentile],
    )
    return float(lower_bound), float(upper_bound)


def build_test_result(
    control_values: np.ndarray,
    treatment_values: np.ndarray,
    p_value: float,
    confidence_interval: tuple[float, float],
    alpha: float,
) -> TestResult:
    """Build a standardized test result from group values and inference.

    Args:
        control_values: Control group KPI values.
        treatment_values: Treatment group KPI values.
        p_value: P-value from the selected statistical test.
        confidence_interval: Confidence interval for mean difference.
        alpha: Significance threshold.

    Returns:
        Standardized statistical result dataclass.
    """

    control_mean = float(np.mean(control_values))
    treatment_mean = float(np.mean(treatment_values))
    mean_difference = treatment_mean - control_mean
    relative_lift = mean_difference / control_mean
    return TestResult(
        control_mean=control_mean,
        treatment_mean=treatment_mean,
        mean_difference=float(mean_difference),
        relative_lift=float(relative_lift),
        p_value=p_value,
        confidence_interval_low=float(confidence_interval[0]),
        confidence_interval_high=float(confidence_interval[1]),
        effect_size=cohens_d(control_values, treatment_values),
        is_significant=p_value < alpha,
    )


def cohens_d(control_values: np.ndarray, treatment_values: np.ndarray) -> float:
    """Calculate Cohen's d standardized mean difference.

    Args:
        control_values: Control group KPI values.
        treatment_values: Treatment group KPI values.

    Returns:
        Cohen's d effect size for treatment minus control.
    """

    control_variance = np.var(control_values, ddof=1)
    treatment_variance = np.var(treatment_values, ddof=1)
    pooled_degrees = len(control_values) + len(treatment_values) - 2
    pooled_variance = (
        ((len(control_values) - 1) * control_variance)
        + ((len(treatment_values) - 1) * treatment_variance)
    ) / pooled_degrees
    pooled_standard_deviation = np.sqrt(pooled_variance)
    if pooled_standard_deviation == 0:
        return 0.0
    return float(
        (np.mean(treatment_values) - np.mean(control_values))
        / pooled_standard_deviation
    )


def classify_effect_size(effect_size: float) -> str:
    """Classify Cohen's d using standard practical-impact thresholds.

    Args:
        effect_size: Cohen's d standardized mean difference.

    Returns:
        Effect size class: negligible, small, medium, or large.
    """

    absolute_effect = abs(effect_size)
    if absolute_effect < NEGLIGIBLE_EFFECT_THRESHOLD:
        return "negligible"
    if absolute_effect < SMALL_EFFECT_THRESHOLD:
        return "small"
    if absolute_effect < MEDIUM_EFFECT_THRESHOLD:
        return "medium"
    return "large"


def practical_impact_label(effect_size_classification: str) -> str:
    """Map an effect-size class to plain-English business impact.

    Args:
        effect_size_classification: Cohen's d classification.

    Returns:
        Practical impact description.
    """

    impact_by_class = {
        "negligible": "minimal",
        "small": "modest",
        "medium": "substantial",
        "large": "substantial",
    }
    return impact_by_class[effect_size_classification]


def build_business_recommendation(
    result: TestResult,
    effect_size_classification: str,
) -> str:
    """Build a one-line recommendation from significance and effect size.

    Args:
        result: Statistical result to interpret.
        effect_size_classification: Cohen's d classification.

    Returns:
        Business recommendation sentence.
    """

    if not result.is_significant:
        return (
            "Because the result is not statistically significant, do not act on "
            "this finding alone; gather more data or test a clearer offer."
        )
    if effect_size_classification == "negligible":
        return (
            "Given the negligible effect size despite statistical significance, "
            "this result alone would not justify a business decision; test a "
            "stronger intervention or gather additional context before acting."
        )
    if effect_size_classification == "small":
        return (
            "Because the effect is statistically significant but small, evaluate "
            "campaign margin and operational cost before scaling."
        )
    return (
        "Because the result is statistically significant with a meaningful "
        "effect size, consider a controlled rollout while monitoring margin."
    )


def build_statistical_summary(result: TestResult, alpha: float) -> str:
    """Summarize statistical and practical significance in plain English.

    Args:
        result: Statistical result to summarize.
        alpha: Significance threshold used for the test.

    Returns:
        Multi-sentence summary combining p-value, Cohen's d, and a business
        recommendation.
    """

    effect_size_classification = classify_effect_size(result.effect_size)
    practical_impact = practical_impact_label(effect_size_classification)
    significance_text = (
        "statistically significant"
        if result.is_significant
        else "not statistically significant"
    )
    chance_text = (
        "unlikely due to random chance"
        if result.is_significant
        else "not strong enough to rule out random chance"
    )
    recommendation = build_business_recommendation(
        result=result,
        effect_size_classification=effect_size_classification,
    )
    return (
        f"The difference between groups is {significance_text} "
        f"(p {'<' if result.is_significant else '>='} {alpha:.2f}), meaning "
        f"it is {chance_text}. However, the effect size "
        f"(Cohen's d = {result.effect_size:.4f}) is classified as "
        f"{effect_size_classification}, meaning the practical impact of this "
        f"difference is {practical_impact}. {recommendation}"
    )


def build_interpretation(
    result: TestResult,
    assumptions: AssumptionCheck,
    alpha: float,
) -> str:
    """Create a non-technical interpretation of the A/B test.

    Args:
        result: Statistical result to interpret.
        assumptions: Assumption diagnostics supporting test choice.
        alpha: Significance threshold.

    Returns:
        Plain-language stakeholder interpretation.
    """

    significance_text = (
        "statistically significant"
        if result.is_significant
        else "not statistically significant"
    )
    return (
        f"The simulated discount treatment produced an average revenue lift of "
        f"{result.relative_lift:.2%} per customer versus control. The result is "
        f"{significance_text} at alpha={alpha:.2f} "
        f"(p={result.p_value:.4g}). The estimated impact is "
        f"{result.mean_difference:,.2f} currency units per customer, with a "
        f"confidence interval from {result.confidence_interval_low:,.2f} to "
        f"{result.confidence_interval_high:,.2f}. In business terms, this "
        f"simulation suggests the discount campaign would likely increase "
        f"customer revenue if the synthetic lift assumption is realistic. "
        f"The test used {assumptions.selected_test} because customers were "
        f"randomized independently and the KPI is continuous revenue."
    )


def write_distribution_plot(
    experiment_data: pd.DataFrame,
    output_dir: Path,
) -> Path:
    """Write an HTML distribution plot for simulated revenue by group.

    Args:
        experiment_data: Simulated customer-level experiment data.
        output_dir: Directory where the HTML chart should be written.

    Returns:
        Path to the generated HTML chart.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = output_dir / "ab_test_revenue_distribution.html"
    plot_data = experiment_data.assign(
        simulated_gross_value_log1p=lambda frame: np.log1p(
            frame["simulated_gross_value"]
        )
    )
    figure = px.histogram(
        plot_data,
        x="simulated_gross_value_log1p",
        color="experiment_group",
        barmode="overlay",
        nbins=PLOT_BIN_COUNT,
        opacity=0.7,
        title="Simulated Revenue per Customer by Experiment Group",
        labels={
            "simulated_gross_value_log1p": "Log(1 + simulated gross revenue)",
            "experiment_group": "Experiment group",
        },
    )
    figure.write_html(plot_path)
    return plot_path


def write_summary(report: ExperimentReport, output_dir: Path) -> Path:
    """Write the experiment report as JSON.

    Args:
        report: Complete experiment report.
        output_dir: Directory where the JSON summary should be written.

    Returns:
        Path to the generated JSON summary.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "ab_test_summary.json"
    report_payload = asdict(report)
    report_payload["config"]["database_path"] = str(report.config.database_path)
    report_payload["config"]["output_dir"] = str(report.config.output_dir)
    report_payload["plot_path"] = str(report.plot_path)
    report_payload["summary_path"] = str(report.summary_path)
    summary_path.write_text(
        json.dumps(report_payload, indent=2),
        encoding="utf-8",
    )
    return summary_path


def run_analysis(config: ExperimentConfig) -> ExperimentReport:
    """Run the full simulated A/B test workflow.

    Args:
        config: Experiment configuration.

    Returns:
        Complete experiment report containing assumptions, results, and outputs.
    """

    customer_revenue = load_customer_revenue(config.database_path)
    experiment_data = simulate_discount_experiment(customer_revenue, config)
    assumptions = check_assumptions(experiment_data, config)
    result = run_hypothesis_test(
        experiment_data=experiment_data,
        assumptions=assumptions,
        confidence_level=config.confidence_level,
    )
    interpretation = build_interpretation(
        result=result,
        assumptions=assumptions,
        alpha=1.0 - config.confidence_level,
    )
    statistical_summary = build_statistical_summary(
        result=result,
        alpha=1.0 - config.confidence_level,
    )
    plot_path = write_distribution_plot(experiment_data, config.output_dir)
    placeholder_summary_path = config.output_dir / "ab_test_summary.json"
    report = ExperimentReport(
        config=config,
        assumptions=assumptions,
        result=result,
        statistical_summary=statistical_summary,
        interpretation=interpretation,
        plot_path=plot_path,
        summary_path=placeholder_summary_path,
    )
    summary_path = write_summary(report, config.output_dir)
    return ExperimentReport(
        config=config,
        assumptions=assumptions,
        result=result,
        statistical_summary=statistical_summary,
        interpretation=interpretation,
        plot_path=plot_path,
        summary_path=summary_path,
    )


def format_report(report: ExperimentReport) -> str:
    """Format an experiment report for console output.

    Args:
        report: Complete experiment report.

    Returns:
        Multi-line human-readable report string.
    """

    return f"""
RetailPulse Simulated Discount A/B Test
=======================================

Dataset note:
Olist has no real discount campaign or experiment flag. This analysis is a
synthetic customer-level randomized experiment layered on top of observed
delivered customer revenue.

Hypotheses:
H0: Mean simulated gross revenue per customer is equal for treatment and control.
H1: Mean simulated gross revenue per customer differs between treatment and control.

Design:
- Randomization unit: customer_unique_id
- Primary KPI: simulated gross revenue per customer
- Treatment simulation: {report.config.synthetic_lift:.2%} incremental revenue lift
- Random seed: {report.config.random_seed}

Assumption checks:
- Control customers: {report.assumptions.control_sample_size:,}
- Treatment customers: {report.assumptions.treatment_sample_size:,}
- Control Shapiro-Wilk p-value: {report.assumptions.control_shapiro_p_value:.4g}
- Treatment Shapiro-Wilk p-value: {report.assumptions.treatment_shapiro_p_value:.4g}
- Levene variance p-value: {report.assumptions.levene_p_value:.4g}
- Selected test: {report.assumptions.selected_test}
- Rationale: {report.assumptions.rationale}

Statistical output:
- Control mean: {report.result.control_mean:,.2f}
- Treatment mean: {report.result.treatment_mean:,.2f}
- Mean difference: {report.result.mean_difference:,.2f}
- Relative lift: {report.result.relative_lift:.2%}
- p-value: {report.result.p_value:.4g}
- {report.config.confidence_level:.0%} confidence interval: [
    {report.result.confidence_interval_low:,.2f},
    {report.result.confidence_interval_high:,.2f}
  ]
- Effect size, Cohen's d: {report.result.effect_size:.4f}

Plain-language statistical summary:
{report.statistical_summary}

Plain-language interpretation:
{report.interpretation}

Outputs:
- Plot: {report.plot_path}
- Summary JSON: {report.summary_path}
""".strip()


def main() -> int:
    """Run the A/B test from the command line.

    Returns:
        Process exit code. Zero means success; non-zero means a handled error.
    """

    args = parse_args()
    config = ExperimentConfig(
        database_path=args.database_path,
        output_dir=args.output_dir,
        random_seed=args.random_seed,
        synthetic_lift=args.synthetic_lift,
    )

    try:
        report = run_analysis(config)
    except (duckdb.Error, FileNotFoundError, ValueError) as error:
        print(f"Unable to run A/B test: {error}")
        return 1

    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
