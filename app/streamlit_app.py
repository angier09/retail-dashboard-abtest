"""Interactive RetailPulse dashboard backed by DuckDB mart tables.

The dashboard reads the dbt-built marts directly from the local DuckDB file and
keeps presentation logic separate from transformation logic. It fails
gracefully when the database or required tables are missing, which makes the
local app easier to run from a fresh clone.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


DEFAULT_DATABASE_PATH = Path(
    os.getenv("RETAILPULSE_DUCKDB_PATH", "retailpulse.duckdb")
)
DEFAULT_AB_TEST_SUMMARY_PATH = Path(
    os.getenv(
        "RETAILPULSE_AB_TEST_SUMMARY_PATH",
        "analysis/outputs/ab_test_summary.json",
    )
)
PAGE_TITLE = "RetailPulse"
PAGE_ICON = ":bar_chart:"
DATE_FORMAT = "YYYY-MM-DD"
TOP_CATEGORY_LIMIT = 12
TOP_STATE_LIMIT = 15
TOP_PRODUCT_LIMIT = 20
MINIMUM_FILTER_OPTIONS = 1
REQUIRED_TABLES = (
    "main_marts.fct_sales",
    "main_marts.fct_orders",
    "main_marts.dim_customer",
    "main_marts.dim_product",
    "main_marts.agg_daily_sales",
)
SALES_QUERY = """
select
    sales.sales_line_item_id,
    sales.order_id,
    sales.customer_unique_id,
    sales.product_id,
    sales.seller_id,
    sales.order_purchase_date,
    sales.customer_state,
    sales.product_category_name_english,
    sales.item_price,
    sales.freight_value,
    sales.item_total_value,
    sales.has_valid_delivery_timing,
    sales.delivery_days,
    sales.delivery_delay_days,
    sales.latest_review_score,
    sales.primary_payment_type,
    customers.rfm_segment,
    customers.is_churned
from main_marts.fct_sales as sales
left join main_marts.dim_customer as customers
    on sales.customer_unique_id = customers.customer_unique_id
"""
ORDERS_QUERY = """
select
    orders.order_id,
    orders.customer_unique_id,
    orders.order_status,
    orders.order_purchase_date,
    orders.customer_state,
    orders.order_item_count,
    orders.order_gross_value,
    orders.total_payment_value,
    orders.primary_payment_type,
    orders.average_review_score,
    orders.latest_review_score,
    orders.is_delivered,
    orders.has_valid_delivery_timing,
    orders.delivery_days,
    orders.delivery_delay_days,
    customers.rfm_segment,
    customers.is_churned
from main_marts.fct_orders as orders
left join main_marts.dim_customer as customers
    on orders.customer_unique_id = customers.customer_unique_id
"""
CUSTOMERS_QUERY = """
select
    customer_unique_id,
    customer_state,
    first_purchase_date,
    last_purchase_date,
    recency_days,
    customer_tenure_days,
    order_count,
    monetary_value,
    gross_value,
    average_order_value,
    average_review_score,
    recency_score,
    frequency_score,
    monetary_score,
    rfm_score,
    rfm_segment,
    is_churned
from main_marts.dim_customer
"""
DAILY_QUERY = """
select
    order_purchase_date,
    delivered_order_count,
    customer_count,
    item_count,
    item_revenue,
    freight_revenue,
    gross_revenue,
    average_order_revenue,
    average_delivery_days,
    average_review_score
from main_marts.agg_daily_sales
order by order_purchase_date
"""
PRODUCT_QUERY = """
select
    product_id,
    product_category_name_english,
    delivered_item_count,
    delivered_order_count,
    delivered_customer_count,
    delivered_item_revenue,
    delivered_gross_value,
    average_item_price
from main_marts.dim_product
where delivered_item_count > 0
"""


class DashboardDataError(RuntimeError):
    """Raised when dashboard source data cannot be loaded safely."""


@dataclass(frozen=True)
class DashboardData:
    """Container for all dataframes used by the dashboard.

    Attributes:
        sales: Delivered sales line-item records joined to customer segments.
        orders: Order-grain facts joined to customer segments.
        customers: Person-level customer dimension records.
        daily: Daily delivered-order KPI records.
        products: Product dimension records with sales rollups.
    """

    sales: pd.DataFrame
    orders: pd.DataFrame
    customers: pd.DataFrame
    daily: pd.DataFrame
    products: pd.DataFrame


@dataclass(frozen=True)
class FilterState:
    """Dashboard filter selections from the sidebar.

    Attributes:
        start_date: Inclusive purchase date lower bound.
        end_date: Inclusive purchase date upper bound.
        states: Selected customer states.
        categories: Selected product categories.
        segments: Selected customer RFM segments.
    """

    start_date: date
    end_date: date
    states: tuple[str, ...]
    categories: tuple[str, ...]
    segments: tuple[str, ...]


def configure_page() -> None:
    """Configure Streamlit page metadata and global styling."""

    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.25rem;
            padding-bottom: 2rem;
        }
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #d9e2df;
            border-left: 4px solid #16837a;
            border-radius: 8px;
            padding: 0.85rem 1rem;
        }
        [data-testid="stMetricLabel"] {
            color: #40514e;
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def load_dataframe(database_path: Path, query: str) -> pd.DataFrame:
    """Run a DuckDB query and return a pandas DataFrame.

    Args:
        database_path: Local DuckDB database file.
        query: SQL query to execute.

    Returns:
        Query result as a pandas DataFrame.
    """

    with duckdb.connect(str(database_path), read_only=True) as connection:
        return connection.execute(query).fetchdf()


def validate_database(database_path: Path) -> None:
    """Validate that the expected DuckDB database and marts exist.

    Args:
        database_path: Local DuckDB database file.

    Raises:
        DashboardDataError: If the database file or required tables are missing.
    """

    if not database_path.exists():
        raise DashboardDataError(
            f"Database not found at {database_path}. Run dbt before launching "
            "the dashboard."
        )

    missing_tables: list[str] = []
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for table_name in REQUIRED_TABLES:
            exists = connection.execute(
                "select count(*) from information_schema.tables "
                "where table_schema || '.' || table_name = ?",
                [table_name],
            ).fetchone()[0]
            if exists == 0:
                missing_tables.append(table_name)

    if missing_tables:
        formatted_tables = ", ".join(missing_tables)
        raise DashboardDataError(
            f"Required mart tables are missing: {formatted_tables}. Run "
            "`dbt run --project-dir dbt --profiles-dir dbt` first."
        )


@st.cache_data(show_spinner="Loading mart tables")
def load_dashboard_data(database_path_text: str) -> DashboardData:
    """Load dashboard data from DuckDB with Streamlit caching.

    Args:
        database_path_text: String path to the DuckDB database.

    Returns:
        Dataframes needed for dashboard tabs.

    Raises:
        DashboardDataError: If required data cannot be loaded.
    """

    database_path = Path(database_path_text)
    validate_database(database_path)
    try:
        data = DashboardData(
            sales=load_dataframe(database_path, SALES_QUERY),
            orders=load_dataframe(database_path, ORDERS_QUERY),
            customers=load_dataframe(database_path, CUSTOMERS_QUERY),
            daily=load_dataframe(database_path, DAILY_QUERY),
            products=load_dataframe(database_path, PRODUCT_QUERY),
        )
    except duckdb.Error as error:
        raise DashboardDataError(
            f"DuckDB could not load dashboard data: {error}"
        ) from error

    if data.sales.empty or data.orders.empty or data.customers.empty:
        raise DashboardDataError(
            "Dashboard marts loaded, but one or more core tables are empty."
        )
    return convert_date_columns(data)


def convert_date_columns(data: DashboardData) -> DashboardData:
    """Normalize date columns to pandas datetime values.

    Args:
        data: Raw dashboard dataframes loaded from DuckDB.

    Returns:
        Dashboard data with date columns converted for filtering and plotting.
    """

    sales = data.sales.copy()
    orders = data.orders.copy()
    customers = data.customers.copy()
    daily = data.daily.copy()
    products = data.products.copy()

    sales["order_purchase_date"] = pd.to_datetime(sales["order_purchase_date"])
    orders["order_purchase_date"] = pd.to_datetime(orders["order_purchase_date"])
    customers["first_purchase_date"] = pd.to_datetime(
        customers["first_purchase_date"]
    )
    customers["last_purchase_date"] = pd.to_datetime(
        customers["last_purchase_date"]
    )
    daily["order_purchase_date"] = pd.to_datetime(daily["order_purchase_date"])
    return DashboardData(
        sales=sales,
        orders=orders,
        customers=customers,
        daily=daily,
        products=products,
    )


def render_header() -> None:
    """Render the dashboard title and current data context."""

    st.title("RetailPulse")
    st.caption("Sales analytics, customer segmentation, and experimentation")


def sorted_options(series: pd.Series) -> list[str]:
    """Return sorted, non-null string options for a filter control.

    Args:
        series: Source column containing filter values.

    Returns:
        Sorted list of unique string values.
    """

    values = series.dropna().astype(str).unique().tolist()
    return sorted(values)


def render_filters(data: DashboardData) -> FilterState:
    """Render sidebar filters and return selected values.

    Args:
        data: Dashboard data used to populate filter options.

    Returns:
        Selected filter state.
    """

    min_date = data.daily["order_purchase_date"].min().date()
    max_date = data.daily["order_purchase_date"].max().date()

    with st.sidebar:
        st.header("Filters")
        selected_date_range = st.date_input(
            "Purchase date",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            format=DATE_FORMAT,
        )
        start_date, end_date = coerce_date_range(
            selected_date_range,
            min_date,
            max_date,
        )
        states = st.multiselect(
            "Customer state",
            options=sorted_options(data.orders["customer_state"]),
            default=sorted_options(data.orders["customer_state"]),
        )
        categories = st.multiselect(
            "Product category",
            options=sorted_options(data.sales["product_category_name_english"]),
            default=sorted_options(data.sales["product_category_name_english"]),
        )
        segments = st.multiselect(
            "Customer segment",
            options=sorted_options(data.customers["rfm_segment"]),
            default=sorted_options(data.customers["rfm_segment"]),
        )

    return FilterState(
        start_date=start_date,
        end_date=end_date,
        states=tuple(states),
        categories=tuple(categories),
        segments=tuple(segments),
    )


def coerce_date_range(
    selected_date_range: date | tuple[date, ...],
    min_date: date,
    max_date: date,
) -> tuple[date, date]:
    """Normalize Streamlit date input into a complete date range.

    Args:
        selected_date_range: Value returned by Streamlit date_input.
        min_date: Fallback minimum date.
        max_date: Fallback maximum date.

    Returns:
        Two-date tuple containing start and end date.
    """

    if isinstance(selected_date_range, tuple):
        if len(selected_date_range) == 2:
            return selected_date_range[0], selected_date_range[1]
        if len(selected_date_range) == MINIMUM_FILTER_OPTIONS:
            return selected_date_range[0], max_date
    return min_date, max_date


def filter_data(data: DashboardData, filters: FilterState) -> DashboardData:
    """Apply dashboard filters to all mart dataframes.

    Args:
        data: Unfiltered dashboard data.
        filters: Sidebar filter selections.

    Returns:
        Filtered dashboard data.
    """

    start_timestamp = pd.Timestamp(filters.start_date)
    end_timestamp = pd.Timestamp(filters.end_date)

    sales = data.sales[
        data.sales["order_purchase_date"].between(
            start_timestamp,
            end_timestamp,
        )
        & data.sales["customer_state"].isin(filters.states)
        & data.sales["product_category_name_english"].isin(filters.categories)
        & data.sales["rfm_segment"].isin(filters.segments)
    ].copy()

    filtered_order_ids = sales["order_id"].drop_duplicates()
    orders = data.orders[
        data.orders["order_purchase_date"].between(
            start_timestamp,
            end_timestamp,
        )
        & data.orders["customer_state"].isin(filters.states)
        & data.orders["rfm_segment"].isin(filters.segments)
        & data.orders["order_id"].isin(filtered_order_ids)
    ].copy()

    filtered_customers = sales["customer_unique_id"].drop_duplicates()
    customers = data.customers[
        data.customers["customer_unique_id"].isin(filtered_customers)
    ].copy()

    daily = build_filtered_daily_sales(sales, orders)
    products = data.products[
        data.products["product_category_name_english"].isin(filters.categories)
    ].copy()
    return DashboardData(
        sales=sales,
        orders=orders,
        customers=customers,
        daily=daily,
        products=products,
    )


def build_filtered_daily_sales(
    sales: pd.DataFrame,
    orders: pd.DataFrame,
) -> pd.DataFrame:
    """Build daily KPIs after dashboard filters are applied.

    Args:
        sales: Filtered delivered sales line items.
        orders: Filtered order-grain records.

    Returns:
        Daily KPI dataframe for trend charts.
    """

    if sales.empty:
        return pd.DataFrame(
            columns=[
                "order_purchase_date",
                "gross_revenue",
                "delivered_order_count",
                "customer_count",
                "item_count",
                "average_order_revenue",
                "average_delivery_days",
                "average_review_score",
            ]
        )

    daily_sales = (
        sales.groupby("order_purchase_date", as_index=False)
        .agg(
            gross_revenue=("item_total_value", "sum"),
            item_count=("sales_line_item_id", "count"),
            customer_count=("customer_unique_id", "nunique"),
            delivered_order_count=("order_id", "nunique"),
        )
        .sort_values("order_purchase_date")
    )
    daily_orders = (
        orders.groupby("order_purchase_date", as_index=False)
        .agg(
            average_order_revenue=("order_gross_value", "mean"),
            average_delivery_days=("delivery_days", "mean"),
            average_review_score=("average_review_score", "mean"),
        )
        .sort_values("order_purchase_date")
    )
    return daily_sales.merge(
        daily_orders,
        on="order_purchase_date",
        how="left",
    )


def render_empty_state() -> None:
    """Render an empty-state message for filters with no matching data."""

    st.warning("No records match the current filter selection.")


def currency(value: float) -> str:
    """Format a number as currency-like text.

    Args:
        value: Numeric value to format.

    Returns:
        Currency-formatted string.
    """

    return f"${value:,.0f}"


def decimal(value: float, digits: int = 1) -> str:
    """Format a decimal number with a fixed number of digits.

    Args:
        value: Numeric value to format.
        digits: Number of decimal places.

    Returns:
        Decimal-formatted string.
    """

    if pd.isna(value):
        return "n/a"
    return f"{value:,.{digits}f}"


def render_kpis(data: DashboardData) -> None:
    """Render top-level KPI cards.

    Args:
        data: Filtered dashboard data.
    """

    revenue = float(data.sales["item_total_value"].sum())
    order_count = int(data.sales["order_id"].nunique())
    customer_count = int(data.sales["customer_unique_id"].nunique())
    average_order_value = revenue / order_count if order_count else 0.0
    delivery_days = data.orders.loc[
        data.orders["has_valid_delivery_timing"],
        "delivery_days",
    ].mean()
    review_score = data.orders["average_review_score"].mean()

    columns = st.columns(5)
    columns[0].metric("Gross revenue", currency(revenue))
    columns[1].metric("Delivered orders", f"{order_count:,}")
    columns[2].metric("Customers", f"{customer_count:,}")
    columns[3].metric("AOV", currency(average_order_value))
    columns[4].metric(
        "Avg delivery days",
        decimal(float(delivery_days)) if not pd.isna(delivery_days) else "n/a",
        help=f"Average review score: {decimal(float(review_score), 2)}",
    )


def build_revenue_trend(data: DashboardData) -> go.Figure:
    """Build a daily gross revenue trend chart.

    Args:
        data: Filtered dashboard data.

    Returns:
        Plotly line chart.
    """

    figure = px.line(
        data.daily,
        x="order_purchase_date",
        y="gross_revenue",
        markers=False,
        labels={
            "order_purchase_date": "Purchase date",
            "gross_revenue": "Gross revenue",
        },
    )
    figure.update_traces(line_color="#16837a", line_width=2)
    figure.update_layout(height=360, margin={"l": 10, "r": 10, "t": 25, "b": 5})
    return figure


def build_category_chart(data: DashboardData) -> go.Figure:
    """Build a top product category revenue chart.

    Args:
        data: Filtered dashboard data.

    Returns:
        Plotly bar chart.
    """

    category_revenue = (
        data.sales.groupby("product_category_name_english", as_index=False)
        .agg(
            gross_revenue=("item_total_value", "sum"),
            orders=("order_id", "nunique"),
        )
        .sort_values("gross_revenue", ascending=False)
        .head(TOP_CATEGORY_LIMIT)
    )
    figure = px.bar(
        category_revenue.sort_values("gross_revenue"),
        x="gross_revenue",
        y="product_category_name_english",
        orientation="h",
        color="orders",
        color_continuous_scale=["#d7ede8", "#16837a"],
        labels={
            "gross_revenue": "Gross revenue",
            "product_category_name_english": "Category",
            "orders": "Orders",
        },
    )
    figure.update_layout(height=420, margin={"l": 10, "r": 10, "t": 25, "b": 5})
    return figure


def build_state_chart(data: DashboardData) -> go.Figure:
    """Build a customer-state revenue chart.

    Args:
        data: Filtered dashboard data.

    Returns:
        Plotly bar chart.
    """

    state_revenue = (
        data.sales.groupby("customer_state", as_index=False)
        .agg(
            gross_revenue=("item_total_value", "sum"),
            customers=("customer_unique_id", "nunique"),
        )
        .sort_values("gross_revenue", ascending=False)
        .head(TOP_STATE_LIMIT)
    )
    figure = px.bar(
        state_revenue,
        x="customer_state",
        y="gross_revenue",
        color="customers",
        color_continuous_scale=["#f4df9e", "#b46f20"],
        labels={
            "customer_state": "State",
            "gross_revenue": "Gross revenue",
            "customers": "Customers",
        },
    )
    figure.update_layout(height=360, margin={"l": 10, "r": 10, "t": 25, "b": 5})
    return figure


def build_segment_chart(data: DashboardData) -> go.Figure:
    """Build customer segment contribution chart.

    Args:
        data: Filtered dashboard data.

    Returns:
        Plotly bar chart.
    """

    segment_revenue = (
        data.sales.groupby("rfm_segment", as_index=False)
        .agg(
            gross_revenue=("item_total_value", "sum"),
            customers=("customer_unique_id", "nunique"),
        )
        .sort_values("gross_revenue", ascending=False)
    )
    figure = px.bar(
        segment_revenue,
        x="rfm_segment",
        y="gross_revenue",
        color="customers",
        color_continuous_scale=["#f1c7c2", "#b4413c"],
        labels={
            "rfm_segment": "Segment",
            "gross_revenue": "Gross revenue",
            "customers": "Customers",
        },
    )
    figure.update_layout(height=360, margin={"l": 10, "r": 10, "t": 25, "b": 5})
    return figure


def build_rfm_scatter(data: DashboardData) -> go.Figure:
    """Build an RFM scatterplot by customer.

    Args:
        data: Filtered dashboard data.

    Returns:
        Plotly scatter chart.
    """

    figure = px.scatter(
        data.customers,
        x="recency_days",
        y="gross_value",
        color="rfm_segment",
        size="order_count",
        opacity=0.55,
        labels={
            "recency_days": "Recency days",
            "gross_value": "Gross customer value",
            "rfm_segment": "Segment",
            "order_count": "Orders",
        },
    )
    figure.update_layout(height=460, margin={"l": 10, "r": 10, "t": 25, "b": 5})
    return figure


def build_delivery_chart(data: DashboardData) -> go.Figure:
    """Build delivery and review score chart by payment method.

    Args:
        data: Filtered dashboard data.

    Returns:
        Plotly scatter chart.
    """

    payment_summary = (
        data.orders[data.orders["has_valid_delivery_timing"]]
        .groupby("primary_payment_type", as_index=False)
        .agg(
            average_delivery_days=("delivery_days", "mean"),
            average_review_score=("average_review_score", "mean"),
            orders=("order_id", "nunique"),
        )
        .dropna(subset=["primary_payment_type"])
    )
    figure = px.scatter(
        payment_summary,
        x="average_delivery_days",
        y="average_review_score",
        size="orders",
        color="primary_payment_type",
        labels={
            "average_delivery_days": "Average delivery days",
            "average_review_score": "Average review score",
            "orders": "Orders",
            "primary_payment_type": "Payment type",
        },
    )
    figure.update_layout(height=380, margin={"l": 10, "r": 10, "t": 25, "b": 5})
    return figure


def build_top_products_table(data: DashboardData) -> pd.DataFrame:
    """Build a table of top products after filters.

    Args:
        data: Filtered dashboard data.

    Returns:
        Product-level revenue table.
    """

    return (
        data.sales.groupby(
            ["product_id", "product_category_name_english"],
            as_index=False,
        )
        .agg(
            gross_revenue=("item_total_value", "sum"),
            orders=("order_id", "nunique"),
            customers=("customer_unique_id", "nunique"),
            average_item_price=("item_price", "mean"),
        )
        .sort_values("gross_revenue", ascending=False)
        .head(TOP_PRODUCT_LIMIT)
    )


def render_sales_tab(data: DashboardData) -> None:
    """Render sales overview dashboard tab.

    Args:
        data: Filtered dashboard data.
    """

    st.subheader("Sales Overview")
    render_kpis(data)
    st.plotly_chart(build_revenue_trend(data), width="stretch")

    left_column, right_column = st.columns(2)
    with left_column:
        st.plotly_chart(build_category_chart(data), width="stretch")
    with right_column:
        st.plotly_chart(build_state_chart(data), width="stretch")

    st.dataframe(
        build_top_products_table(data),
        width="stretch",
        hide_index=True,
    )


def render_customer_tab(data: DashboardData) -> None:
    """Render customer segmentation dashboard tab.

    Args:
        data: Filtered dashboard data.
    """

    st.subheader("Customer Segments")
    left_column, right_column = st.columns([1, 1])
    with left_column:
        st.plotly_chart(build_segment_chart(data), width="stretch")
    with right_column:
        churn_rate = float(data.customers["is_churned"].mean())
        repeat_rate = float((data.customers["order_count"] > 1).mean())
        average_lifetime_value = float(data.customers["gross_value"].mean())
        st.metric("Churned customers", f"{churn_rate:.1%}")
        st.metric("Repeat customer rate", f"{repeat_rate:.1%}")
        st.metric("Avg customer value", currency(average_lifetime_value))

    st.plotly_chart(build_rfm_scatter(data), width="stretch")


def render_operations_tab(data: DashboardData) -> None:
    """Render delivery, review, and payment operations dashboard tab.

    Args:
        data: Filtered dashboard data.
    """

    st.subheader("Operations Quality")
    valid_delivery_rate = float(data.orders["has_valid_delivery_timing"].mean())
    late_delivery_rate = float(
        (data.orders["delivery_delay_days"].fillna(0) > 0).mean()
    )
    review_score = float(data.orders["average_review_score"].mean())

    columns = st.columns(3)
    columns[0].metric("Valid delivery timing", f"{valid_delivery_rate:.1%}")
    columns[1].metric("Late delivery rate", f"{late_delivery_rate:.1%}")
    columns[2].metric("Avg review score", decimal(review_score, 2))
    st.plotly_chart(build_delivery_chart(data), width="stretch")

    payment_table = (
        data.orders.groupby("primary_payment_type", as_index=False)
        .agg(
            orders=("order_id", "nunique"),
            gross_revenue=("order_gross_value", "sum"),
            average_order_value=("order_gross_value", "mean"),
            average_review_score=("average_review_score", "mean"),
        )
        .sort_values("gross_revenue", ascending=False)
    )
    st.dataframe(payment_table, width="stretch", hide_index=True)


def load_ab_summary(summary_path: Path) -> dict[str, Any] | None:
    """Load the simulated A/B test JSON summary when available.

    Args:
        summary_path: Path to the A/B test summary JSON file.

    Returns:
        Parsed summary dictionary, or None when the file is absent.
    """

    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def render_experiment_tab(summary_path: Path) -> None:
    """Render the simulated A/B test dashboard tab.

    Args:
        summary_path: Path to the A/B test summary JSON file.
    """

    st.subheader("Experiment Results")
    summary = load_ab_summary(summary_path)
    if summary is None:
        st.info(
            "Run `python analysis/ab_test.py` to generate the experiment "
            "summary displayed here."
        )
        return

    result = summary["result"]
    assumptions = summary["assumptions"]
    columns = st.columns(4)
    columns[0].metric("Relative lift", f"{result['relative_lift']:.2%}")
    columns[1].metric("Mean difference", currency(result["mean_difference"]))
    columns[2].metric("p-value", f"{result['p_value']:.3g}")
    columns[3].metric("Cohen's d", decimal(result["effect_size"], 3))

    st.write(summary["interpretation"])
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "selected_test": assumptions["selected_test"],
                    "control_customers": assumptions["control_sample_size"],
                    "treatment_customers": assumptions[
                        "treatment_sample_size"
                    ],
                    "levene_p_value": assumptions["levene_p_value"],
                    "control_normality_p": assumptions[
                        "control_shapiro_p_value"
                    ],
                    "treatment_normality_p": assumptions[
                        "treatment_shapiro_p_value"
                    ],
                }
            ]
        ),
        width="stretch",
        hide_index=True,
    )


def render_dashboard(data: DashboardData, summary_path: Path) -> None:
    """Render dashboard tabs for the filtered data.

    Args:
        data: Filtered dashboard data.
        summary_path: Path to the A/B test summary JSON file.
    """

    if data.sales.empty or data.orders.empty or data.customers.empty:
        render_empty_state()
        return

    sales_tab, customer_tab, operations_tab, experiment_tab = st.tabs(
        [
            "Sales",
            "Customers",
            "Operations",
            "Experiment",
        ]
    )
    with sales_tab:
        render_sales_tab(data)
    with customer_tab:
        render_customer_tab(data)
    with operations_tab:
        render_operations_tab(data)
    with experiment_tab:
        render_experiment_tab(summary_path)


def main() -> None:
    """Run the Streamlit dashboard application."""

    configure_page()
    render_header()
    database_path = DEFAULT_DATABASE_PATH
    summary_path = DEFAULT_AB_TEST_SUMMARY_PATH

    try:
        data = load_dashboard_data(str(database_path))
    except DashboardDataError as error:
        st.error(str(error))
        st.stop()

    filters = render_filters(data)
    filtered_data = filter_data(data, filters)
    render_dashboard(filtered_data, summary_path)


if __name__ == "__main__":
    main()
