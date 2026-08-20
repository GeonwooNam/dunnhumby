"""Dunnhumby 데이터셋의 가설 발굴용 간단 EDA.

실행:
    python eda.py

산출물:
    eda_report.md
    eda_outputs/*.csv
    eda_outputs/*.png

집계는 DuckDB SQL로 수행하며 원본 DB는 read-only로 연다. 이 스크립트의
목적은 가설을 확정하는 것이 아니라, 후속 검증 질문을 만들 수 있는 패턴을
빠르게 드러내는 것이다.
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "dunnhumby.duckdb"
OUTPUT_DIR = ROOT / "eda_outputs"
REPORT_PATH = ROOT / "eda_report.md"

AGE_ORDER = ["19-24", "25-34", "35-44", "45-54", "55-64", "65+"]
INCOME_ORDER = [
    "Under 15K",
    "15-24K",
    "25-34K",
    "35-49K",
    "50-74K",
    "75-99K",
    "100-124K",
    "125-149K",
    "150-174K",
    "175-199K",
    "200-249K",
    "250K+",
]
DISCOUNT_ORDER = ["No discount", "(0, 10%]", "(10%, 25%]", "(25%, 50%]", ">50%"]


OVERVIEW_SQL = """
SELECT
    COUNT(*) AS transaction_lines,
    COUNT(DISTINCT household_key) AS households,
    COUNT(DISTINCT BASKET_ID) AS baskets,
    COUNT(DISTINCT PRODUCT_ID) AS purchased_products,
    COUNT(DISTINCT STORE_ID) AS stores,
    MIN(DAY) AS min_day,
    MAX(DAY) AS max_day,
    MIN(WEEK_NO) AS min_week,
    MAX(WEEK_NO) AS max_week,
    SUM(SALES_VALUE) AS total_sales,
    SUM(-RETAIL_DISC - COUPON_DISC - COUPON_MATCH_DISC) AS discount_amount,
    AVG(SALES_VALUE) AS avg_line_sales
FROM transaction_data
"""


WEEKLY_SQL = """
WITH first_week AS (
    SELECT household_key, MIN(WEEK_NO) AS first_week
    FROM transaction_data
    GROUP BY household_key
),
weekly AS (
    SELECT
        WEEK_NO,
        MIN(DAY) AS min_day,
        MAX(DAY) AS max_day,
        COUNT(DISTINCT DAY) AS observed_days,
        SUM(SALES_VALUE) AS sales,
        COUNT(DISTINCT BASKET_ID) AS baskets,
        COUNT(DISTINCT household_key) AS active_households,
        SUM(-RETAIL_DISC - COUPON_DISC - COUPON_MATCH_DISC) AS discounts
    FROM transaction_data
    GROUP BY WEEK_NO
)
SELECT
    w.*,
    w.sales / w.observed_days AS sales_per_day,
    w.baskets::DOUBLE / w.observed_days AS baskets_per_day,
    COUNT(f.household_key) AS new_households,
    (
        SELECT COUNT(*)
        FROM campaign_desc AS c
        WHERE c.START_DAY <= w.max_day
          AND c.END_DAY >= w.min_day
    ) AS active_campaigns
FROM weekly AS w
LEFT JOIN first_week AS f
  ON f.first_week = w.WEEK_NO
GROUP BY ALL
ORDER BY w.WEEK_NO
"""


CUSTOMER_SQL = """
SELECT
    t.household_key,
    SUM(t.SALES_VALUE) AS sales,
    COUNT(DISTINCT t.BASKET_ID) AS baskets,
    COUNT(DISTINCT t.WEEK_NO) AS active_weeks,
    COUNT(DISTINCT t.PRODUCT_ID) AS products,
    COUNT(DISTINCT p.COMMODITY_DESC) AS category_diversity,
    MIN(t.DAY) AS first_day,
    MAX(t.DAY) AS last_day,
    SUM(-t.RETAIL_DISC - t.COUPON_DISC - t.COUPON_MATCH_DISC) AS discount_amount,
    SUM(t.SALES_VALUE) / COUNT(DISTINCT t.BASKET_ID) AS avg_basket_value
FROM transaction_data AS t
JOIN product AS p USING (PRODUCT_ID)
GROUP BY t.household_key
ORDER BY t.household_key
"""


HOURLY_SQL = """
WITH basket AS (
    SELECT
        BASKET_ID,
        household_key,
        MAX(TRY_CAST(SUBSTR(LPAD(TRANS_TIME, 4, '0'), 1, 2) AS INTEGER)) AS hour_of_day,
        SUM(SALES_VALUE) AS sales,
        COUNT(DISTINCT PRODUCT_ID) AS products
    FROM transaction_data
    GROUP BY BASKET_ID, household_key
)
SELECT
    hour_of_day,
    COUNT(*) AS baskets,
    AVG(sales) AS avg_basket_sales,
    AVG(products) AS avg_products,
    COUNT(DISTINCT household_key) AS households
FROM basket
GROUP BY hour_of_day
ORDER BY hour_of_day
"""


BASKET_SIZE_SQL = """
WITH basket AS (
    SELECT
        BASKET_ID,
        SUM(SALES_VALUE) AS sales,
        COUNT(DISTINCT PRODUCT_ID) AS products,
        COUNT(DISTINCT p.DEPARTMENT) AS departments
    FROM transaction_data AS t
    JOIN product AS p USING (PRODUCT_ID)
    GROUP BY BASKET_ID
),
banded AS (
    SELECT
        *,
        CASE
            WHEN products = 1 THEN '1'
            WHEN products <= 5 THEN '2-5'
            WHEN products <= 10 THEN '6-10'
            WHEN products <= 20 THEN '11-20'
            ELSE '21+'
        END AS product_band,
        CASE
            WHEN products = 1 THEN 1
            WHEN products <= 5 THEN 2
            WHEN products <= 10 THEN 3
            WHEN products <= 20 THEN 4
            ELSE 5
        END AS band_order
    FROM basket
)
SELECT
    product_band,
    band_order,
    COUNT(*) AS baskets,
    AVG(sales) AS avg_basket_sales,
    MEDIAN(sales) AS median_basket_sales,
    AVG(products) AS avg_products,
    AVG(departments) AS avg_departments
FROM banded
GROUP BY product_band, band_order
ORDER BY band_order
"""


DEPARTMENT_SQL = """
SELECT
    TRIM(p.DEPARTMENT) AS department,
    SUM(t.SALES_VALUE) AS sales,
    COUNT(DISTINCT t.BASKET_ID) AS baskets,
    COUNT(DISTINCT t.household_key) AS households,
    COUNT(DISTINCT t.PRODUCT_ID) AS products,
    SUM(t.SALES_VALUE) / COUNT(DISTINCT t.household_key) AS sales_per_buyer
FROM transaction_data AS t
JOIN product AS p USING (PRODUCT_ID)
WHERE NULLIF(TRIM(p.DEPARTMENT), '') IS NOT NULL
GROUP BY TRIM(p.DEPARTMENT)
ORDER BY sales DESC
"""


CATEGORY_AFFINITY_SQL = """
WITH top_department AS (
    SELECT
        TRIM(p.DEPARTMENT) AS department,
        COUNT(DISTINCT t.BASKET_ID) AS basket_count
    FROM transaction_data AS t
    JOIN product AS p USING (PRODUCT_ID)
    WHERE NULLIF(TRIM(p.DEPARTMENT), '') IS NOT NULL
    GROUP BY TRIM(p.DEPARTMENT)
    ORDER BY basket_count DESC
    LIMIT 10
),
basket_department AS (
    SELECT DISTINCT t.BASKET_ID, TRIM(p.DEPARTMENT) AS department
    FROM transaction_data AS t
    JOIN product AS p USING (PRODUCT_ID)
    JOIN top_department AS d ON d.department = TRIM(p.DEPARTMENT)
),
total AS (
    SELECT COUNT(DISTINCT BASKET_ID) AS n_baskets
    FROM transaction_data
),
marginal AS (
    SELECT department, COUNT(*) AS n_baskets
    FROM basket_department
    GROUP BY department
),
pair AS (
    SELECT
        a.department AS department_a,
        b.department AS department_b,
        COUNT(*) AS co_baskets
    FROM basket_department AS a
    JOIN basket_department AS b
      ON a.BASKET_ID = b.BASKET_ID
     AND a.department < b.department
    GROUP BY a.department, b.department
)
SELECT
    p.department_a,
    p.department_b,
    p.co_baskets,
    ma.n_baskets AS baskets_a,
    mb.n_baskets AS baskets_b,
    p.co_baskets * t.n_baskets::DOUBLE / (ma.n_baskets * mb.n_baskets) AS lift
FROM pair AS p
JOIN marginal AS ma ON ma.department = p.department_a
JOIN marginal AS mb ON mb.department = p.department_b
CROSS JOIN total AS t
ORDER BY lift DESC
"""


DISCOUNT_SQL = """
WITH basket AS (
    SELECT
        BASKET_ID,
        SUM(SALES_VALUE) AS net_sales,
        -SUM(RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) AS discount,
        COUNT(DISTINCT PRODUCT_ID) AS products
    FROM transaction_data
    GROUP BY BASKET_ID
),
banded AS (
    SELECT
        *,
        net_sales + discount AS gross_sales,
        CASE
            WHEN discount <= 0 OR gross_sales <= 0 THEN 'No discount'
            WHEN discount / gross_sales <= 0.10 THEN '(0, 10%]'
            WHEN discount / gross_sales <= 0.25 THEN '(10%, 25%]'
            WHEN discount / gross_sales <= 0.50 THEN '(25%, 50%]'
            ELSE '>50%'
        END AS discount_band
    FROM basket
)
SELECT
    discount_band,
    COUNT(*) AS baskets,
    AVG(net_sales) AS avg_net_sales,
    AVG(gross_sales) AS avg_gross_sales,
    MEDIAN(net_sales) AS median_net_sales,
    AVG(products) AS avg_products,
    AVG(discount / NULLIF(gross_sales, 0)) AS avg_discount_rate
FROM banded
GROUP BY discount_band
"""


CAMPAIGN_SQL = """
WITH target AS (
    SELECT
        CAMPAIGN,
        COUNT(DISTINCT household_key) AS targeted_households
    FROM campaign_table
    GROUP BY CAMPAIGN
),
redemption AS (
    SELECT
        CAMPAIGN,
        COUNT(DISTINCT household_key) AS redeeming_households,
        COUNT(*) AS redemptions,
        COUNT(DISTINCT COUPON_UPC) AS redeemed_coupons
    FROM coupon_redempt
    GROUP BY CAMPAIGN
)
SELECT
    d.CAMPAIGN,
    d.DESCRIPTION AS campaign_type,
    d.START_DAY,
    d.END_DAY,
    d.END_DAY - d.START_DAY + 1 AS duration_days,
    t.targeted_households,
    COALESCE(r.redeeming_households, 0) AS redeeming_households,
    COALESCE(r.redemptions, 0) AS redemptions,
    COALESCE(r.redeemed_coupons, 0) AS redeemed_coupons,
    COALESCE(r.redeeming_households, 0)::DOUBLE / NULLIF(t.targeted_households, 0) AS household_redemption_rate
FROM campaign_desc AS d
LEFT JOIN target AS t USING (CAMPAIGN)
LEFT JOIN redemption AS r USING (CAMPAIGN)
ORDER BY d.CAMPAIGN
"""


DEMOGRAPHIC_SQL = """
WITH household AS (
    SELECT
        household_key,
        SUM(SALES_VALUE) AS sales,
        COUNT(DISTINCT BASKET_ID) AS baskets,
        COUNT(DISTINCT WEEK_NO) AS active_weeks,
        SUM(SALES_VALUE) / COUNT(DISTINCT BASKET_ID) AS avg_basket_value
    FROM transaction_data
    GROUP BY household_key
)
SELECT
    d.*,
    h.sales,
    h.baskets,
    h.active_weeks,
    h.avg_basket_value
FROM hh_demographic AS d
JOIN household AS h USING (household_key)
"""


def configure_plot_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update(
        {
            "figure.dpi": 130,
            "savefig.dpi": 180,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
        }
    )


def markdown_table(df: pd.DataFrame) -> str:
    display = df.copy().astype(str)
    headers = list(display.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in display.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def save_csv(data: dict[str, pd.DataFrame]) -> None:
    for name, frame in data.items():
        frame.to_csv(OUTPUT_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")


def plot_weekly(weekly: pd.DataFrame) -> None:
    w = weekly.copy()
    for col in ["sales_per_day", "baskets_per_day", "active_households"]:
        w[f"{col}_ma4"] = w[col].rolling(4, center=True, min_periods=1).mean()

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    specs = [
        ("sales_per_day", "sales_per_day_ma4", "Sales per observed day"),
        ("baskets_per_day", "baskets_per_day_ma4", "Baskets per observed day"),
        ("active_households", "active_households_ma4", "Active households"),
    ]
    for ax, (raw, smooth, label) in zip(axes, specs):
        ax.plot(w["WEEK_NO"], w[raw], color="#9D9D9D", alpha=0.5, linewidth=1)
        ax.plot(w["WEEK_NO"], w[smooth], color="#4C78A8", linewidth=2, label="4-week moving average")
        ax.set_ylabel(label)
        ax.legend(loc="lower right", frameon=False)
    axes[-1].set_xlabel("Week number (day-indexed data; no calendar date)")
    axes[0].set_title("Weekly demand: ramp-up followed by a relatively stable panel")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "01_weekly_trend.png", bbox_inches="tight")
    plt.close(fig)


def plot_customers(customers: pd.DataFrame) -> dict[str, float]:
    c = customers.copy()
    ranked = c.sort_values("sales", ascending=False).reset_index(drop=True)
    ranked["customer_share"] = (np.arange(len(ranked)) + 1) / len(ranked)
    ranked["cumulative_sales_share"] = ranked["sales"].cumsum() / ranked["sales"].sum()
    top10_share = ranked.loc[ranked["customer_share"] <= 0.10, "sales"].sum() / ranked["sales"].sum()
    top20_share = ranked.loc[ranked["customer_share"] <= 0.20, "sales"].sum() / ranked["sales"].sum()

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    scatter = axes[0].scatter(
        c["baskets"],
        c["sales"],
        c=c["category_diversity"],
        cmap="viridis",
        s=18,
        alpha=0.65,
        linewidths=0,
    )
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Customer baskets (log scale)")
    axes[0].set_ylabel("Customer sales (log scale)")
    axes[0].set_title("Frequency, sales, and category diversity move together")
    cbar = fig.colorbar(scatter, ax=axes[0])
    cbar.set_label("Distinct commodity categories")

    axes[1].plot(
        ranked["customer_share"] * 100,
        ranked["cumulative_sales_share"] * 100,
        color="#F58518",
        linewidth=2.5,
    )
    axes[1].plot([0, 100], [0, 100], linestyle="--", color="#777777", linewidth=1)
    axes[1].axvline(10, color="#555555", linewidth=1, alpha=0.6)
    axes[1].axvline(20, color="#555555", linewidth=1, alpha=0.6)
    axes[1].text(10.5, top10_share * 100, f"Top 10% = {top10_share:.1%} of sales", va="center")
    axes[1].text(20.5, top20_share * 100, f"Top 20% = {top20_share:.1%} of sales", va="center")
    axes[1].set_xlabel("Top customers by sales (%)")
    axes[1].set_ylabel("Cumulative sales captured (%)")
    axes[1].set_title("Customer sales concentration")
    axes[1].set_xlim(0, 100)
    axes[1].set_ylim(0, 100)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "02_customer_landscape.png", bbox_inches="tight")
    plt.close(fig)
    return {"top10_sales_share": float(top10_share), "top20_sales_share": float(top20_share)}


def plot_baskets(hourly: pd.DataFrame, basket_size: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    axes[0].bar(hourly["hour_of_day"], hourly["baskets"], color="#4C78A8", alpha=0.9)
    ax2 = axes[0].twinx()
    ax2.plot(hourly["hour_of_day"], hourly["avg_basket_sales"], color="#F58518", marker="o", markersize=3)
    axes[0].set_xlabel("Hour of day")
    axes[0].set_ylabel("Number of baskets", color="#4C78A8")
    ax2.set_ylabel("Average basket sales", color="#F58518")
    axes[0].set_title("Traffic peaks later than basket value")
    axes[0].set_xticks(np.arange(0, 24, 2))

    b = basket_size.sort_values("band_order")
    x = np.arange(len(b))
    axes[1].bar(x, b["avg_basket_sales"], color="#72B7B2")
    axes[1].set_xticks(x, b["product_band"])
    axes[1].set_xlabel("Distinct products in basket")
    axes[1].set_ylabel("Average basket sales")
    axes[1].set_title("Basket value rises nonlinearly with product count")
    for i, row in b.reset_index(drop=True).iterrows():
        axes[1].text(i, row["avg_basket_sales"] + 2, f"{row['avg_basket_sales']:.1f}", ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "03_basket_patterns.png", bbox_inches="tight")
    plt.close(fig)


def plot_categories(departments: pd.DataFrame, affinity: pd.DataFrame) -> None:
    top = departments.head(15).sort_values("sales")
    names = list(
        dict.fromkeys(
            affinity["department_a"].tolist() + affinity["department_b"].tolist()
        )
    )
    # Basket reach 순으로 heatmap 축을 정렬한다.
    reach_order = (
        departments.loc[departments["department"].isin(names)]
        .sort_values("baskets", ascending=False)["department"]
        .tolist()
    )
    matrix = pd.DataFrame(np.nan, index=reach_order, columns=reach_order)
    for row in affinity.itertuples(index=False):
        matrix.loc[row.department_a, row.department_b] = row.lift
        matrix.loc[row.department_b, row.department_a] = row.lift

    fig, axes = plt.subplots(1, 2, figsize=(17, 6.2), gridspec_kw={"width_ratios": [0.9, 1.3]})
    axes[0].barh(top["department"], top["sales"] / 1_000_000, color="#4C78A8")
    axes[0].set_xlabel("Sales (millions)")
    axes[0].set_title("Sales are concentrated in a few departments")
    for i, value in enumerate(top["sales"] / 1_000_000):
        axes[0].text(value + 0.025, i, f"{value:.2f}", va="center", fontsize=8)

    sns.heatmap(
        matrix,
        ax=axes[1],
        cmap="YlGnBu",
        vmin=0.8,
        vmax=min(2.5, float(np.nanmax(matrix.to_numpy()))),
        annot=True,
        fmt=".2f",
        linewidths=0.5,
        cbar_kws={"label": "Basket co-occurrence lift"},
    )
    axes[1].set_title("Top-department basket affinity (>1 means above chance)")
    axes[1].set_xlabel("")
    axes[1].set_ylabel("")
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].tick_params(axis="y", rotation=0)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "04_category_landscape.png", bbox_inches="tight")
    plt.close(fig)


def plot_offers(discount: pd.DataFrame, campaign: pd.DataFrame) -> pd.DataFrame:
    d = discount.set_index("discount_band").loc[DISCOUNT_ORDER].reset_index()
    type_colors = {"TypeA": "#4C78A8", "TypeB": "#72B7B2", "TypeC": "#F58518"}

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2))
    x = np.arange(len(d))
    axes[0].bar(x, d["avg_net_sales"], color="#4C78A8", alpha=0.9)
    ax2 = axes[0].twinx()
    ax2.plot(x, d["avg_products"], color="#F58518", marker="o", linewidth=2)
    axes[0].set_xticks(x, d["discount_band"], rotation=20, ha="right")
    axes[0].set_ylabel("Average net basket sales", color="#4C78A8")
    ax2.set_ylabel("Average distinct products", color="#F58518")
    axes[0].set_title("Discount depth is not monotonically related to basket size")

    for campaign_type, group in campaign.groupby("campaign_type"):
        axes[1].scatter(
            group["targeted_households"],
            group["household_redemption_rate"] * 100,
            s=np.clip(group["duration_days"] * 1.7, 30, 140),
            alpha=0.8,
            label=campaign_type,
            color=type_colors.get(campaign_type),
        )
    for row in campaign.nlargest(5, "household_redemption_rate").itertuples(index=False):
        axes[1].annotate(str(row.CAMPAIGN), (row.targeted_households, row.household_redemption_rate * 100), xytext=(4, 4), textcoords="offset points", fontsize=8)
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Targeted households (log scale)")
    axes[1].set_ylabel("Household redemption rate (%)")
    axes[1].set_title("Campaign scale and redemption vary by type")
    axes[1].legend(title="Campaign type", frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "05_discount_campaign.png", bbox_inches="tight")
    plt.close(fig)

    type_summary = (
        campaign.groupby("campaign_type", as_index=False)
        .agg(
            campaigns=("CAMPAIGN", "count"),
            targeted_households=("targeted_households", "sum"),
            redeeming_households=("redeeming_households", "sum"),
            avg_campaign_rate=("household_redemption_rate", "mean"),
        )
    )
    type_summary["pooled_redemption_rate"] = (
        type_summary["redeeming_households"] / type_summary["targeted_households"]
    )
    return type_summary


def demographic_summaries(demographic: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    age = (
        demographic.groupby("AGE_DESC", as_index=False, observed=True)
        .agg(
            households=("household_key", "count"),
            avg_sales=("sales", "mean"),
            median_sales=("sales", "median"),
            avg_baskets=("baskets", "mean"),
            avg_basket_value=("avg_basket_value", "mean"),
        )
    )
    age["AGE_DESC"] = pd.Categorical(age["AGE_DESC"], AGE_ORDER, ordered=True)
    age = age.sort_values("AGE_DESC").reset_index(drop=True)

    income = (
        demographic.groupby("INCOME_DESC", as_index=False, observed=True)
        .agg(
            households=("household_key", "count"),
            avg_sales=("sales", "mean"),
            median_sales=("sales", "median"),
            avg_baskets=("baskets", "mean"),
            avg_basket_value=("avg_basket_value", "mean"),
        )
    )
    income["INCOME_DESC"] = pd.Categorical(income["INCOME_DESC"], INCOME_ORDER, ordered=True)
    income = income.sort_values("INCOME_DESC").reset_index(drop=True)
    return age, income


def plot_demographics(age: pd.DataFrame, income: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
    axes[0].plot(age["AGE_DESC"].astype(str), age["avg_sales"], marker="o", color="#4C78A8", linewidth=2)
    axes[0].set_xlabel("Age group")
    axes[0].set_ylabel("Average customer sales")
    axes[0].set_title("Customer sales vary by age group")
    for i, row in age.iterrows():
        axes[0].text(i, row["avg_sales"] + 110, f"n={int(row['households'])}", ha="center", fontsize=8)

    axes[1].plot(
        income["INCOME_DESC"].astype(str),
        income["avg_basket_value"],
        marker="o",
        color="#F58518",
        linewidth=2,
    )
    axes[1].set_xlabel("Income group")
    axes[1].set_ylabel("Average basket value")
    axes[1].set_title("Basket value by income (small groups are volatile)")
    axes[1].tick_params(axis="x", rotation=45)
    for i, row in income.iterrows():
        if row["households"] < 20:
            axes[1].text(i, row["avg_basket_value"] + 0.8, f"n={int(row['households'])}", ha="center", fontsize=7)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "06_demographics.png", bbox_inches="tight")
    plt.close(fig)


def build_report(
    data: dict[str, pd.DataFrame],
    customer_stats: dict[str, float],
    campaign_types: pd.DataFrame,
    age: pd.DataFrame,
    income: pd.DataFrame,
) -> str:
    overview = data["overview"].iloc[0]
    weekly = data["weekly_summary"]
    customers = data["customer_summary"]
    hourly = data["hourly_summary"]
    departments = data["department_summary"]
    affinity = data["category_affinity"]
    discount = data["discount_summary"].set_index("discount_band").loc[DISCOUNT_ORDER].reset_index()
    campaign = data["campaign_summary"]

    peak_hour = hourly.loc[hourly["baskets"].idxmax()]
    value_hour = hourly.loc[hourly["avg_basket_sales"].idxmax()]
    peak_week = weekly.loc[weekly["sales_per_day"].idxmax()]
    top_department = departments.iloc[0]
    top5_sales_share = departments.head(5)["sales"].sum() / departments["sales"].sum()
    top_affinity = affinity.loc[affinity["co_baskets"] >= 500].sort_values("lift", ascending=False).iloc[0]
    highest_discount_products = discount.loc[discount["avg_products"].idxmax()]
    best_campaign = campaign.loc[campaign["household_redemption_rate"].idxmax()]
    best_age = age.loc[age["avg_sales"].idxmax()]
    best_income = income.loc[income["avg_basket_value"].idxmax()]
    demographic_coverage = len(data["demographic_customer"]) / overview["households"]

    overview_table = pd.DataFrame(
        {
            "항목": ["거래 행", "장바구니", "고객", "구매 상품", "점포", "관찰 기간", "총매출"],
            "값": [
                f"{int(overview['transaction_lines']):,}",
                f"{int(overview['baskets']):,}",
                f"{int(overview['households']):,}",
                f"{int(overview['purchased_products']):,}",
                f"{int(overview['stores']):,}",
                f"DAY {int(overview['min_day'])}–{int(overview['max_day'])} ({int(overview['max_week'])}주)",
                f"{overview['total_sales']:,.2f}",
            ],
        }
    )
    dept_table = departments.head(10).copy()
    dept_table = pd.DataFrame(
        {
            "부서": dept_table["department"],
            "매출": dept_table["sales"].map(lambda x: f"{x:,.0f}"),
            "구매 고객": dept_table["households"].map(lambda x: f"{int(x):,}"),
            "장바구니": dept_table["baskets"].map(lambda x: f"{int(x):,}"),
        }
    )
    affinity_table = affinity.loc[affinity["co_baskets"] >= 500].head(8).copy()
    affinity_table = pd.DataFrame(
        {
            "카테고리 A": affinity_table["department_a"],
            "카테고리 B": affinity_table["department_b"],
            "동시장바구니": affinity_table["co_baskets"].map(lambda x: f"{int(x):,}"),
            "Lift": affinity_table["lift"].map(lambda x: f"{x:.2f}"),
        }
    )
    campaign_type_table = pd.DataFrame(
        {
            "유형": campaign_types["campaign_type"],
            "캠페인 수": campaign_types["campaigns"].map(lambda x: f"{int(x)}"),
            "타깃 고객 합계": campaign_types["targeted_households"].map(lambda x: f"{int(x):,}"),
            "통합 전환율": campaign_types["pooled_redemption_rate"].map(lambda x: f"{x:.1%}"),
        }
    )

    return f"""# Dunnhumby 가설 발굴용 EDA

분석 코드: `eda.py`  
실행 방법: `python eda.py`  
목적: 패턴을 확정하는 것이 아니라 **검증할 만한 질문을 찾는 것**

## 1. 데이터 개요

{markdown_table(overview_table)}

- 인구통계는 {len(data['demographic_customer']):,}명만 있어 전체 고객의 **{demographic_coverage:.1%}**를 덮는다. 인구통계 결과를 전체 고객으로 일반화하면 안 된다.
- `DAY`와 `WEEK_NO`만 있고 실제 달력 날짜는 없다. 계절성에 이름을 붙이지 않고 주차 패턴으로만 해석했다.
- `KIOSK-GAS`, `MISC SALES TRAN`의 수량은 일반 상품과 단위가 다를 수 있어 수량 중심 비교는 피했다.

## 2. 시간 흐름

![주차별 수요](eda_outputs/01_weekly_trend.png)

초기 약 15–20주는 고객 패널이 유입되며 매출·장바구니·활성 고객이 함께 증가한다. 이후에는 비교적 안정적이지만 주차별 피크가 존재한다. 관찰 일수로 보정한 일평균 매출 최고 주는 **{int(peak_week['WEEK_NO'])}주차({peak_week['sales_per_day']:,.0f})**다.

가설 후보:

1. 안정화 이후의 주차별 매출 변동은 활성 고객 수보다 고객당 장바구니 금액 변화가 더 크게 설명할 것이다.
2. 캠페인이 활성화된 주에는 신규 고객 수보다 기존 고객의 구매 빈도가 더 크게 증가할 것이다.
3. 초기 유입 코호트와 후기 유입 코호트는 장기 잔존율과 카테고리 확장 속도가 다를 것이다.

## 3. 고객 행동

![고객 행동 분포](eda_outputs/02_customer_landscape.png)

- 고객별 장바구니 수와 누적 매출은 강하게 함께 움직이며, 카테고리 다양성도 같이 커지는 모습이다.
- 매출 상위 10% 고객이 전체 매출의 **{customer_stats['top10_sales_share']:.1%}**, 상위 20%가 **{customer_stats['top20_sales_share']:.1%}**를 만든다.
- 고객별 장바구니 수 중앙값은 **{customers['baskets'].median():.0f}회**, 고객 매출 중앙값은 **{customers['sales'].median():,.0f}**다.

가설 후보:

4. 고가치 고객은 평균 장바구니 금액보다 방문 빈도로 더 잘 구분될 것이다.
5. 고객의 카테고리 다양성은 구매 횟수를 통제한 뒤에도 고객 생애 매출과 양의 관계를 가질 것이다.
6. 상위 매출 고객은 할인 의존도가 높아서가 아니라 활성 주차가 길어서 높은 매출을 보일 것이다.

## 4. 장바구니와 구매 시간

![장바구니와 시간대](eda_outputs/03_basket_patterns.png)

- 장바구니 트래픽은 **{int(peak_hour['hour_of_day'])}시({int(peak_hour['baskets']):,}건)**에 가장 많지만, 평균 장바구니 금액은 **{int(value_hour['hour_of_day'])}시({value_hour['avg_basket_sales']:.2f})**에 가장 높다.
- 방문량이 많은 시간과 큰 장바구니가 만들어지는 시간이 같지 않다.

가설 후보:

7. 오전·점심 시간대 고객은 저녁 고객보다 상품 수와 신선식품 비중이 높을 것이다.
8. 1–5개 상품의 소형 장바구니 고객은 특정 시간대·점포·카테고리에 집중될 것이다.
9. 장바구니 상품 수가 늘수록 매출이 선형이 아니라 체감 또는 체증하는 구간이 존재할 것이다.

## 5. 카테고리 구조와 동시구매

![카테고리 구조](eda_outputs/04_category_landscape.png)

상위 10개 부서:

{markdown_table(dept_table)}

- `{top_department['department']}`가 전체 부서 매출의 **{top_department['sales']/departments['sales'].sum():.1%}**를 차지하고, 상위 5개 부서 비중은 **{top5_sales_share:.1%}**다.
- 동시구매 Lift는 두 카테고리가 각각의 인기도만으로 기대되는 수준보다 얼마나 자주 함께 담기는지를 나타낸다. 1보다 크면 우연 기대치보다 많이 동시 구매된 것이다.

동시구매 Lift 상위 조합(동시 장바구니 500건 이상):

{markdown_table(affinity_table)}

가설 후보:

10. `{top_affinity['department_a']}`–`{top_affinity['department_b']}` 조합(Lift {top_affinity['lift']:.2f})은 특정 고객군이나 특정 시간대에서 더 강할 것이다.
11. `DELI`–`PASTRY`, `MEAT`–`PRODUCE`처럼 식사 맥락이 비슷한 카테고리는 교차 진열 시 장바구니 확장 가능성이 높을 것이다.
12. 침투율이 높은 `GROCERY`를 제외하면 고객 세그먼트별 핵심 카테고리 조합이 더 선명해질 것이다.

## 6. 할인과 캠페인

![할인과 캠페인](eda_outputs/05_discount_campaign.png)

- 평균 상품 수가 가장 많은 할인 구간은 **{highest_discount_products['discount_band']}({highest_discount_products['avg_products']:.1f}개)**다. 할인율이 깊어질수록 장바구니가 계속 커지는 단조 관계는 아니다.
- 가장 높은 개별 캠페인 고객 전환율은 캠페인 **{int(best_campaign['CAMPAIGN'])}번({best_campaign['campaign_type']}, {best_campaign['household_redemption_rate']:.1%})**이다.

캠페인 유형별 단순 집계:

{markdown_table(campaign_type_table)}

가설 후보:

13. 중간 수준 할인은 장바구니 확장을 유도하지만, 50% 초과 할인은 소수 미끼상품 구매에 집중될 것이다.
14. Type A 캠페인의 높은 전환율은 유형 자체보다 타깃 규모·기간·쿠폰 수 차이로 설명될 수 있다.
15. 쿠폰을 반복 사용한 고객은 첫 사용 이후 비쿠폰 구매 빈도도 증가할 것이다.

## 7. 인구통계 탐색

![인구통계](eda_outputs/06_demographics.png)

- 표본 내 평균 고객 매출이 가장 높은 연령대는 **{str(best_age['AGE_DESC'])}({best_age['avg_sales']:,.0f})**다.
- 평균 장바구니 금액이 가장 높은 소득 구간은 **{str(best_income['INCOME_DESC'])}({best_income['avg_basket_value']:.2f})**지만, 소득 상위 구간은 표본 수가 매우 작아 변동성이 크다.

가설 후보:

16. 35–44세의 높은 매출은 장바구니 금액보다 방문 빈도와 자녀 동거 여부가 매개할 것이다.
17. 소득이 높을수록 총 방문 횟수보다 회당 장바구니 금액이 증가할 것이다.
18. 연령·소득 효과는 실제로는 가구 구성과 가구원 수를 통제하면 약해질 것이다.

## 다음 분석을 고르는 방법

- **고객 유지/CRM**에 관심이 있으면 가설 3, 4, 6, 15를 우선 검증한다.
- **상품·교차판매**에 관심이 있으면 가설 7, 10, 11, 12를 우선 검증한다.
- **프로모션 효율**에 관심이 있으면 가설 13, 14, 15를 우선 검증한다.
- **고객 세분화**에 관심이 있으면 가설 5, 16, 17, 18을 우선 검증한다.

각 차트의 집계값은 `eda_outputs/*.csv`에 저장되어 있다. EDA의 차이는 인과효과가 아니므로, 선택한 가설은 코호트 정의·통제 변수·통계 검정을 추가해 확인해야 한다.
"""


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DuckDB 파일을 찾을 수 없습니다: {DB_PATH}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    configure_plot_style()

    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET threads = 8")
    try:
        print("[1/4] DuckDB 집계 중...")
        data = {
            "overview": con.sql(OVERVIEW_SQL).fetchdf(),
            "weekly_summary": con.sql(WEEKLY_SQL).fetchdf(),
            "customer_summary": con.sql(CUSTOMER_SQL).fetchdf(),
            "hourly_summary": con.sql(HOURLY_SQL).fetchdf(),
            "basket_size_summary": con.sql(BASKET_SIZE_SQL).fetchdf(),
            "department_summary": con.sql(DEPARTMENT_SQL).fetchdf(),
            "category_affinity": con.sql(CATEGORY_AFFINITY_SQL).fetchdf(),
            "discount_summary": con.sql(DISCOUNT_SQL).fetchdf(),
            "campaign_summary": con.sql(CAMPAIGN_SQL).fetchdf(),
            "demographic_customer": con.sql(DEMOGRAPHIC_SQL).fetchdf(),
        }
    finally:
        con.close()

    print("[2/4] 시각화 생성 중...")
    plot_weekly(data["weekly_summary"])
    customer_stats = plot_customers(data["customer_summary"])
    plot_baskets(data["hourly_summary"], data["basket_size_summary"])
    plot_categories(data["department_summary"], data["category_affinity"])
    campaign_types = plot_offers(data["discount_summary"], data["campaign_summary"])
    age, income = demographic_summaries(data["demographic_customer"])
    plot_demographics(age, income)

    print("[3/4] 집계표 저장 중...")
    data["campaign_type_summary"] = campaign_types
    data["age_summary"] = age
    data["income_summary"] = income
    save_csv(data)

    print("[4/4] Markdown 보고서 작성 중...")
    REPORT_PATH.write_text(
        build_report(data, customer_stats, campaign_types, age, income),
        encoding="utf-8",
    )
    print(f"완료: {REPORT_PATH}")
    print(f"차트 및 집계표: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
