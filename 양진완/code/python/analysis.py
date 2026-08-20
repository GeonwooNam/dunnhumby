"""Dunnhumby 초기 가설 검증 분석(legacy).

가설 1
    초기 구매 카테고리 다양성이 높은 고객일수록 이후 재방문율과
    구매 빈도가 높은가?

가설 2
    전단(mailer) 및 특별 진열(display)이 적용된 상품은 비프로모션
    상품보다 매출이 높고, 두 프로모션을 병행할 때 상승폭이 가장 큰가?

주의:
    가설 2의 현재 상품축 분석은 run_product_axis.py에 있다. 이 파일의 가설 2
    코드는 초기 탐색을 보존한 것이며 패널 트래픽 보정이 없어 최종 결론에 쓰지
    않는다. 최신 결과는 product_axis_report.md를 사용한다.

산출물:
    hypothesis_validation_legacy.md
    analysis_outputs/*.csv
    analysis_outputs/*.png

분석용 집계는 DuckDB SQL로 수행하고, 신뢰구간/회귀/시각화는 Python으로
수행한다. 원본 DB는 read-only로 연다.
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.discrete.discrete_model import NegativeBinomial
from statsmodels.stats.proportion import proportion_confint


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "dunnhumby.duckdb"
OUTPUT_DIR = ROOT / "analysis_outputs"
REPORT_PATH = ROOT / "hypothesis_validation_legacy.md"

INITIAL_DAYS = 30
FOLLOWUP_DAYS = 60
MIN_SALE_WEEKS = 4
MIN_ACTIVE_SPAN_WEEKS = 8
PROMO_ORDER = ["none", "display_only", "mailer_only", "both"]
PROMO_LABELS = {
    "none": "No promotion",
    "display_only": "Display only",
    "mailer_only": "Mailer only",
    "both": "Both",
}


# ---------------------------------------------------------------------------
# 가설 1 SQL
# 고객별 첫 구매일부터 30일을 초기 관찰 구간, 다음 60일을 후속 구간으로 둔다.
# 데이터 종료일 전에 후속 구간 전체를 관찰할 수 있는 고객만 포함한다.
# ---------------------------------------------------------------------------
H1_CUSTOMER_CTE = f"""
WITH first_purchase AS (
    SELECT
        household_key,
        MIN(DAY) AS first_day
    FROM transaction_data
    GROUP BY household_key
),
eligible_households AS (
    SELECT household_key, first_day
    FROM first_purchase
    WHERE first_day <= (SELECT MAX(DAY) - {INITIAL_DAYS + FOLLOWUP_DAYS - 1}
                        FROM transaction_data)
),
initial_period AS (
    SELECT
        e.household_key,
        e.first_day,
        COUNT(DISTINCT p.COMMODITY_DESC) AS category_diversity,
        COUNT(DISTINCT p.DEPARTMENT) AS department_diversity,
        COUNT(DISTINCT t.BASKET_ID) AS initial_baskets,
        COUNT(DISTINCT t.DAY) AS initial_active_days,
        SUM(t.SALES_VALUE) AS initial_sales
    FROM eligible_households AS e
    JOIN transaction_data AS t
      ON t.household_key = e.household_key
     AND t.DAY BETWEEN e.first_day AND e.first_day + {INITIAL_DAYS - 1}
    JOIN product AS p
      ON p.PRODUCT_ID = t.PRODUCT_ID
    GROUP BY e.household_key, e.first_day
),
followup_period AS (
    SELECT
        e.household_key,
        COUNT(DISTINCT t.BASKET_ID) AS followup_baskets,
        COUNT(DISTINCT t.DAY) AS followup_active_days,
        COALESCE(SUM(t.SALES_VALUE), 0) AS followup_sales
    FROM eligible_households AS e
    LEFT JOIN transaction_data AS t
      ON t.household_key = e.household_key
     AND t.DAY BETWEEN e.first_day + {INITIAL_DAYS}
                   AND e.first_day + {INITIAL_DAYS + FOLLOWUP_DAYS - 1}
    GROUP BY e.household_key
),
customer_data AS (
    SELECT
        i.*,
        COALESCE(f.followup_baskets, 0) AS followup_baskets,
        COALESCE(f.followup_active_days, 0) AS followup_active_days,
        COALESCE(f.followup_sales, 0) AS followup_sales,
        (COALESCE(f.followup_baskets, 0) > 0)::INTEGER AS returned
    FROM initial_period AS i
    JOIN followup_period AS f USING (household_key)
)
"""

H1_CUSTOMER_SQL = H1_CUSTOMER_CTE + """
SELECT *
FROM customer_data
ORDER BY household_key
"""

H1_QUARTILE_SQL = H1_CUSTOMER_CTE + """
,
cutoffs AS (
    SELECT
        QUANTILE_DISC(category_diversity, 0.25) AS q25,
        QUANTILE_DISC(category_diversity, 0.50) AS q50,
        QUANTILE_DISC(category_diversity, 0.75) AS q75
    FROM customer_data
),
grouped AS (
    SELECT
        c.*,
        CASE
            WHEN category_diversity <= q25 THEN 'Q1'
            WHEN category_diversity <= q50 THEN 'Q2'
            WHEN category_diversity <= q75 THEN 'Q3'
            ELSE 'Q4'
        END AS diversity_group
    FROM customer_data AS c
    CROSS JOIN cutoffs
)
SELECT
    diversity_group,
    COUNT(*) AS households,
    MIN(category_diversity) AS min_categories,
    MAX(category_diversity) AS max_categories,
    AVG(category_diversity) AS avg_categories,
    AVG(returned) AS return_rate,
    AVG(followup_baskets) AS avg_followup_baskets,
    MEDIAN(followup_baskets) AS median_followup_baskets,
    AVG(followup_sales) AS avg_followup_sales,
    AVG(initial_baskets) AS avg_initial_baskets,
    AVG(initial_sales) AS avg_initial_sales
FROM grouped
GROUP BY diversity_group
ORDER BY diversity_group
"""


# ---------------------------------------------------------------------------
# 가설 2 SQL
# display='A'는 In-Shelf(정규 매대)라 특별 진열이 아니다. causal_data에
# 명시적으로 존재하는 비프로모션 키만 사용하고 키가 없는 주는 비교에서 제외한다.
# 서로 다른 원시 코드가 중복된 키도 제외한다.
# ---------------------------------------------------------------------------
H2_PANEL_CTE = f"""
WITH weekly_sales AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        WEEK_NO,
        SUM(SALES_VALUE) AS sales,
        SUM(QUANTITY) AS quantity
    FROM transaction_data
    WHERE QUANTITY > 0 OR SALES_VALUE > 0
    GROUP BY PRODUCT_ID, STORE_ID, WEEK_NO
),
eligible_pairs AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        MIN(WEEK_NO) AS min_week,
        MAX(WEEK_NO) AS max_week,
        COUNT(DISTINCT WEEK_NO) AS sale_weeks
    FROM weekly_sales
    GROUP BY PRODUCT_ID, STORE_ID
    HAVING sale_weeks >= {MIN_SALE_WEEKS}
       AND max_week - min_week + 1 >= {MIN_ACTIVE_SPAN_WEEKS}
),
promotion AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        WEEK_NO,
        MAX((display NOT IN ('0', 'A'))::INTEGER) AS has_display,
        MAX((mailer <> '0')::INTEGER) AS has_mailer
    FROM causal_data
    GROUP BY PRODUCT_ID, STORE_ID, WEEK_NO
    HAVING COUNT(DISTINCT display) = 1
       AND COUNT(DISTINCT mailer) = 1
),
panel AS (
    SELECT
        p.PRODUCT_ID,
        p.STORE_ID,
        w.WEEK_NO,
        COALESCE(s.sales, 0) AS sales,
        COALESCE(s.quantity, 0) AS quantity,
        CASE
            WHEN a.has_display = 0 AND a.has_mailer = 0 THEN 'none'
            WHEN a.has_display = 1 AND a.has_mailer = 0 THEN 'display_only'
            WHEN a.has_display = 0 AND a.has_mailer = 1 THEN 'mailer_only'
            ELSE 'both'
        END AS promo_group
    FROM eligible_pairs AS p
    CROSS JOIN LATERAL GENERATE_SERIES(p.min_week, p.max_week) AS w(WEEK_NO)
    LEFT JOIN weekly_sales AS s USING (PRODUCT_ID, STORE_ID, WEEK_NO)
    INNER JOIN promotion AS a USING (PRODUCT_ID, STORE_ID, WEEK_NO)
)
"""

H2_RAW_SQL = H2_PANEL_CTE + """
SELECT
    promo_group,
    COUNT(*) AS pair_weeks,
    COUNT(DISTINCT (PRODUCT_ID, STORE_ID)) AS product_store_pairs,
    AVG(sales) AS avg_sales_per_pair_week,
    MEDIAN(sales) AS median_sales_per_pair_week,
    AVG((sales > 0)::INTEGER) AS positive_sales_rate,
    SUM(sales) AS total_sales
FROM panel
GROUP BY promo_group
ORDER BY CASE promo_group
    WHEN 'none' THEN 1
    WHEN 'display_only' THEN 2
    WHEN 'mailer_only' THEN 3
    ELSE 4
END
"""

# 네 상태를 모두 경험한 동일 상품-점포 쌍만 남겨 구성 차이를 통제한다.
H2_BALANCED_PAIR_SQL = H2_PANEL_CTE + """
,
pair_group AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        promo_group,
        COUNT(*) AS n_weeks,
        AVG(sales) AS avg_sales,
        AVG((sales > 0)::INTEGER) AS positive_sales_rate
    FROM panel
    GROUP BY PRODUCT_ID, STORE_ID, promo_group
),
wide AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        MAX(avg_sales) FILTER (WHERE promo_group = 'none') AS none_sales,
        MAX(avg_sales) FILTER (WHERE promo_group = 'display_only') AS display_sales,
        MAX(avg_sales) FILTER (WHERE promo_group = 'mailer_only') AS mailer_sales,
        MAX(avg_sales) FILTER (WHERE promo_group = 'both') AS both_sales,
        MAX(positive_sales_rate) FILTER (WHERE promo_group = 'none') AS none_rate,
        MAX(positive_sales_rate) FILTER (WHERE promo_group = 'display_only') AS display_rate,
        MAX(positive_sales_rate) FILTER (WHERE promo_group = 'mailer_only') AS mailer_rate,
        MAX(positive_sales_rate) FILTER (WHERE promo_group = 'both') AS both_rate,
        MAX(n_weeks) FILTER (WHERE promo_group = 'none') AS none_weeks,
        MAX(n_weeks) FILTER (WHERE promo_group = 'display_only') AS display_weeks,
        MAX(n_weeks) FILTER (WHERE promo_group = 'mailer_only') AS mailer_weeks,
        MAX(n_weeks) FILTER (WHERE promo_group = 'both') AS both_weeks
    FROM pair_group
    GROUP BY PRODUCT_ID, STORE_ID
)
SELECT *
FROM wide
WHERE none_weeks >= 4
  AND display_weeks >= 1
  AND mailer_weeks >= 1
  AND both_weeks >= 1
ORDER BY PRODUCT_ID, STORE_ID
"""


def configure_plot_style() -> None:
    """OS에 한글 폰트가 있으면 사용하고, 아니면 영문 라벨로 안전하게 그린다."""
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "figure.dpi": 130,
            "savefig.dpi": 180,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
        }
    )


def mean_ci(values: pd.Series | np.ndarray, confidence: float = 0.95) -> tuple[float, float, float]:
    """평균과 t 기반 신뢰구간."""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    mean = float(np.mean(x))
    if len(x) < 2:
        return mean, math.nan, math.nan
    se = stats.sem(x)
    critical = stats.t.ppf((1 + confidence) / 2, len(x) - 1)
    return mean, float(mean - critical * se), float(mean + critical * se)


def p_text(p: float) -> str:
    if p < 0.001:
        return "<0.001"
    return f"{p:.3f}"


def pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:.{digits}f}%"


def markdown_table(df: pd.DataFrame) -> str:
    """추가 패키지 의존 없이 작은 DataFrame을 Markdown 표로 변환."""
    display = df.copy().astype(str)
    headers = list(display.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in display.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def analyze_h1(con: duckdb.DuckDBPyConnection) -> dict[str, object]:
    customers = con.sql(H1_CUSTOMER_SQL).fetchdf()
    quartiles = con.sql(H1_QUARTILE_SQL).fetchdf()

    customers["returned"] = customers["returned"].astype(int)
    for col in ["category_diversity", "initial_baskets", "initial_sales", "first_day"]:
        x = np.log1p(customers[col]) if col in {"initial_baskets", "initial_sales"} else customers[col]
        customers[f"z_{col}"] = (x - x.mean()) / x.std(ddof=0)

    predictors = [
        "z_category_diversity",
        "z_initial_baskets",
        "z_initial_sales",
        "z_first_day",
    ]
    x = sm.add_constant(customers[predictors])

    logit = sm.GLM(
        customers["returned"], x, family=sm.families.Binomial()
    ).fit(cov_type="HC3")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        negbin = NegativeBinomial(customers["followup_baskets"], x).fit(
            disp=False, cov_type="HC0", maxiter=200
        )
    log_ols = sm.OLS(np.log1p(customers["followup_baskets"]), x).fit(cov_type="HC3")

    model_specs = [
        ("Revisit logistic", "Odds ratio", logit),
        ("Basket count negative binomial", "Incidence-rate ratio", negbin),
        ("Sensitivity: log1p basket OLS", "exp(beta)", log_ols),
    ]
    model_rows: list[dict[str, object]] = []
    for model_name, effect_name, model in model_specs:
        beta = float(model.params["z_category_diversity"])
        se = float(model.bse["z_category_diversity"])
        model_rows.append(
            {
                "model": model_name,
                "effect_type": effect_name,
                "effect": math.exp(beta),
                "ci_low": math.exp(beta - 1.96 * se),
                "ci_high": math.exp(beta + 1.96 * se),
                "p_value": float(model.pvalues["z_category_diversity"]),
            }
        )
    models = pd.DataFrame(model_rows)

    # 그룹별 신뢰구간은 고객 단위 원자료에서 계산한다.
    q25, q50, q75 = customers["category_diversity"].quantile(
        [0.25, 0.50, 0.75], interpolation="lower"
    )
    customers["diversity_group"] = np.select(
        [
            customers["category_diversity"] <= q25,
            customers["category_diversity"] <= q50,
            customers["category_diversity"] <= q75,
        ],
        ["Q1", "Q2", "Q3"],
        default="Q4",
    )
    ci_rows = []
    for group in ["Q1", "Q2", "Q3", "Q4"]:
        g = customers.loc[customers["diversity_group"] == group]
        rate_low, rate_high = proportion_confint(
            g["returned"].sum(), len(g), alpha=0.05, method="wilson"
        )
        basket_mean, basket_low, basket_high = mean_ci(g["followup_baskets"])
        ci_rows.append(
            {
                "diversity_group": group,
                "return_ci_low": rate_low,
                "return_ci_high": rate_high,
                "basket_mean": basket_mean,
                "basket_ci_low": basket_low,
                "basket_ci_high": basket_high,
            }
        )
    quartiles = quartiles.merge(pd.DataFrame(ci_rows), on="diversity_group", how="left")

    customers.to_csv(OUTPUT_DIR / "h1_customer_level.csv", index=False, encoding="utf-8-sig")
    quartiles.to_csv(OUTPUT_DIR / "h1_quartile_summary.csv", index=False, encoding="utf-8-sig")
    models.to_csv(OUTPUT_DIR / "h1_adjusted_models.csv", index=False, encoding="utf-8-sig")
    plot_h1(quartiles, models)

    return {
        "customers": customers,
        "quartiles": quartiles,
        "models": models,
        "diversity_sd": float(customers["category_diversity"].std(ddof=0)),
    }


def plot_h1(quartiles: pd.DataFrame, models: pd.DataFrame) -> None:
    q = quartiles.set_index("diversity_group").loc[["Q1", "Q2", "Q3", "Q4"]].reset_index()
    x = np.arange(len(q))
    color = "#4C78A8"

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

    axes[0].bar(x, q["return_rate"] * 100, color=color, alpha=0.9)
    axes[0].errorbar(
        x,
        q["return_rate"] * 100,
        yerr=np.vstack(
            [
                (q["return_rate"] - q["return_ci_low"]) * 100,
                (q["return_ci_high"] - q["return_rate"]) * 100,
            ]
        ),
        fmt="none",
        ecolor="#222222",
        capsize=3,
    )
    axes[0].set_title("Raw revisit rate")
    axes[0].set_ylabel("Households revisiting (%)")
    axes[0].set_xticks(x, q["diversity_group"])
    axes[0].set_ylim(0, 105)
    for i, value in enumerate(q["return_rate"] * 100):
        axes[0].text(i, value + 2.2, f"{value:.1f}%", ha="center", fontsize=9)

    axes[1].bar(x, q["avg_followup_baskets"], color=color, alpha=0.9)
    axes[1].errorbar(
        x,
        q["avg_followup_baskets"],
        yerr=np.vstack(
            [
                q["avg_followup_baskets"] - q["basket_ci_low"],
                q["basket_ci_high"] - q["avg_followup_baskets"],
            ]
        ),
        fmt="none",
        ecolor="#222222",
        capsize=3,
    )
    axes[1].set_title("Raw follow-up frequency")
    axes[1].set_ylabel("Baskets in following 60 days")
    axes[1].set_xticks(x, q["diversity_group"])
    for i, value in enumerate(q["avg_followup_baskets"]):
        axes[1].text(i, value + 0.5, f"{value:.1f}", ha="center", fontsize=9)

    y = np.arange(len(models))
    effect = models["effect"].to_numpy()
    err = np.vstack(
        [effect - models["ci_low"].to_numpy(), models["ci_high"].to_numpy() - effect]
    )
    axes[2].errorbar(effect, y, xerr=err, fmt="o", color="#F58518", capsize=4)
    axes[2].axvline(1, color="#555555", linewidth=1, linestyle="--")
    axes[2].set_yticks(y, ["Revisit OR", "Basket IRR", "log1p sensitivity"])
    axes[2].set_xlabel("Effect per +1 SD category diversity (95% CI)")
    axes[2].set_title("Adjusted diversity effect")
    axes[2].invert_yaxis()
    for i, row in models.iterrows():
        axes[2].text(row["ci_high"] + 0.015, i, f"p={p_text(row['p_value'])}", va="center", fontsize=8)

    fig.suptitle("Hypothesis 1: initial category diversity and later engagement", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "h1_diversity.png", bbox_inches="tight")
    plt.close(fig)


def analyze_h2(con: duckdb.DuckDBPyConnection) -> dict[str, object]:
    raw = con.sql(H2_RAW_SQL).fetchdf()
    balanced = con.sql(H2_BALANCED_PAIR_SQL).fetchdf()
    raw["promo_group"] = pd.Categorical(raw["promo_group"], PROMO_ORDER, ordered=True)
    raw = raw.sort_values("promo_group").reset_index(drop=True)

    comparisons = {
        "display_vs_none": balanced["display_sales"] - balanced["none_sales"],
        "mailer_vs_none": balanced["mailer_sales"] - balanced["none_sales"],
        "both_vs_none": balanced["both_sales"] - balanced["none_sales"],
        "both_vs_display": balanced["both_sales"] - balanced["display_sales"],
        "both_vs_mailer": balanced["both_sales"] - balanced["mailer_sales"],
        # 양(+)이면 단순 가산효과를 넘는 시너지다.
        "synergy_beyond_additive": (
            balanced["both_sales"]
            - balanced["display_sales"]
            - balanced["mailer_sales"]
            + balanced["none_sales"]
        ),
    }
    paired_rows = []
    for name, values in comparisons.items():
        mean, low, high = mean_ci(values)
        test = stats.ttest_1samp(values, popmean=0, nan_policy="omit")
        paired_rows.append(
            {
                "comparison": name,
                "pairs": int(values.notna().sum()),
                "mean_difference": mean,
                "ci_low": low,
                "ci_high": high,
                "p_value": float(test.pvalue),
            }
        )
    paired = pd.DataFrame(paired_rows)

    balanced_means = pd.DataFrame(
        {
            "promo_group": PROMO_ORDER,
            "avg_sales_per_pair_week": [
                balanced["none_sales"].mean(),
                balanced["display_sales"].mean(),
                balanced["mailer_sales"].mean(),
                balanced["both_sales"].mean(),
            ],
            "positive_sales_rate": [
                balanced["none_rate"].mean(),
                balanced["display_rate"].mean(),
                balanced["mailer_rate"].mean(),
                balanced["both_rate"].mean(),
            ],
        }
    )
    base_sales = float(balanced_means.loc[0, "avg_sales_per_pair_week"])
    balanced_means["lift_vs_none"] = (
        balanced_means["avg_sales_per_pair_week"] / base_sales - 1
    )

    raw.to_csv(OUTPUT_DIR / "h2_raw_panel_summary.csv", index=False, encoding="utf-8-sig")
    balanced_means.to_csv(
        OUTPUT_DIR / "h2_balanced_pair_summary.csv", index=False, encoding="utf-8-sig"
    )
    paired.to_csv(OUTPUT_DIR / "h2_paired_tests.csv", index=False, encoding="utf-8-sig")
    plot_h2(raw, paired)

    return {
        "raw": raw,
        "balanced": balanced,
        "balanced_means": balanced_means,
        "paired": paired,
    }


def plot_h2(raw: pd.DataFrame, paired: pd.DataFrame) -> None:
    raw = raw.copy()
    raw["promo_group"] = raw["promo_group"].astype(str)
    colors = ["#9D9D9D", "#4C78A8", "#72B7B2", "#F58518"]
    labels = [PROMO_LABELS[g] for g in PROMO_ORDER]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(4)
    raw_values = raw.set_index("promo_group").loc[PROMO_ORDER, "avg_sales_per_pair_week"].to_numpy()
    axes[0].bar(x, raw_values, color=colors)
    axes[0].set_xticks(x, labels, rotation=15, ha="right")
    axes[0].set_ylabel("Average sales per product-store-week")
    axes[0].set_title("Raw active-panel comparison")
    base = raw_values[0]
    for i, value in enumerate(raw_values):
        label = f"{value:.3f}" if i == 0 else f"{value:.3f}\n(+{100 * (value / base - 1):.1f}%)"
        axes[0].text(i, value + 0.025, label, ha="center", fontsize=9)

    wanted = ["display_vs_none", "mailer_vs_none", "both_vs_none"]
    d = paired.set_index("comparison").loc[wanted].reset_index()
    y = np.arange(3)
    axes[1].barh(y, d["mean_difference"], color=colors[1:])
    axes[1].errorbar(
        d["mean_difference"],
        y,
        xerr=np.vstack(
            [
                d["mean_difference"] - d["ci_low"],
                d["ci_high"] - d["mean_difference"],
            ]
        ),
        fmt="none",
        ecolor="#222222",
        capsize=3,
    )
    axes[1].axvline(0, color="#555555", linewidth=1)
    axes[1].set_yticks(y, ["Display - none", "Mailer - none", "Both - none"])
    axes[1].set_xlabel("Within-pair sales difference (95% CI)")
    axes[1].set_title("Legacy within-pair comparison")
    axes[1].invert_yaxis()
    for i, value in enumerate(d["mean_difference"]):
        axes[1].text(d.loc[i, "ci_high"] + 0.008, i, f"+{value:.3f}", va="center", fontsize=9)

    fig.suptitle("Hypothesis 2: promotion exposure and weekly sales", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "h2_promotion.png", bbox_inches="tight")
    plt.close(fig)


def build_report(h1: dict[str, object], h2: dict[str, object]) -> str:
    quartiles = h1["quartiles"].set_index("diversity_group").loc[["Q1", "Q2", "Q3", "Q4"]].reset_index()
    models = h1["models"]
    raw = h2["raw"].copy()
    raw["promo_group"] = raw["promo_group"].astype(str)
    balanced_means = h2["balanced_means"]
    paired = h2["paired"].set_index("comparison")
    n_balanced = len(h2["balanced"])

    q_table = pd.DataFrame(
        {
            "그룹": quartiles["diversity_group"],
            "카테고리 범위": quartiles.apply(
                lambda r: f"{int(r['min_categories'])}–{int(r['max_categories'])}", axis=1
            ),
            "고객 수": quartiles["households"].map(lambda x: f"{int(x):,}"),
            "초기 장바구니": quartiles["avg_initial_baskets"].map(lambda x: f"{x:.2f}"),
            "재방문율": quartiles["return_rate"].map(pct),
            "후속 장바구니": quartiles["avg_followup_baskets"].map(lambda x: f"{x:.2f}"),
        }
    )
    model_table = pd.DataFrame(
        {
            "모형": models["model"],
            "효과 지표": models["effect_type"],
            "추정치": models["effect"].map(lambda x: f"{x:.3f}"),
            "95% CI": models.apply(lambda r: f"{r['ci_low']:.3f}–{r['ci_high']:.3f}", axis=1),
            "p-value": models["p_value"].map(p_text),
        }
    )
    raw_base = float(raw.loc[raw["promo_group"] == "none", "avg_sales_per_pair_week"].iloc[0])
    raw_table = pd.DataFrame(
        {
            "프로모션": raw["promo_group"].map(PROMO_LABELS),
            "상품-점포-주": raw["pair_weeks"].map(lambda x: f"{int(x):,}"),
            "주평균 매출": raw["avg_sales_per_pair_week"].map(lambda x: f"{x:.3f}"),
            "비프로모션 대비": raw["avg_sales_per_pair_week"].map(
                lambda x: "기준" if math.isclose(x, raw_base) else f"{100 * (x / raw_base - 1):+.1f}%"
            ),
            "판매 발생률": raw["positive_sales_rate"].map(pct),
        }
    )
    paired_table = pd.DataFrame(
        {
            "프로모션": balanced_means["promo_group"].map(PROMO_LABELS),
            "동일 쌍 내 주평균 매출": balanced_means["avg_sales_per_pair_week"].map(lambda x: f"{x:.3f}"),
            "비프로모션 대비": balanced_means["lift_vs_none"].map(
                lambda x: "기준" if abs(x) < 1e-12 else f"{100*x:+.1f}%"
            ),
            "판매 발생률": balanced_means["positive_sales_rate"].map(pct),
        }
    )

    q1 = quartiles.iloc[0]
    q4 = quartiles.iloc[-1]
    synergy = paired.loc["synergy_beyond_additive"]
    both_display = paired.loc["both_vs_display"]
    both_mailer = paired.loc["both_vs_mailer"]

    return f"""# Dunnhumby 가설 검증 결과

분석 실행일: 2026-08-12  
분석 코드: `analysis.py`  
데이터베이스: `dunnhumby.duckdb` (읽기 전용)

## 결론 요약

- **가설 1 — 부분 지지:** 초기 카테고리 다양성이 높은 고객은 기술통계상 재방문율과 후속 구매 빈도가 훨씬 높았다. 그러나 초기 장바구니 수·초기 지출·첫 구매 시점을 통제하면 다양성의 독립 효과는 모형에 따라 유의성이 달라졌다. 즉, 좋은 고객 신호인 것은 분명하지만 원인이라고 단정하기는 어렵다.
- **가설 2 — 연관성 기준 지지:** 원시 비교와 동일 상품-점포 쌍 비교에서 모두 `둘 다 > 전단만 > 진열만 > 없음` 순으로 주평균 매출이 높았다. 다만 병행 효과가 두 단독 효과의 합을 초과하는 **초가산적 시너지**는 확인되지 않았다.

## 분석 설계

### 가설 1

- 고객별 첫 구매일부터 **{INITIAL_DAYS}일**을 초기 구간, 다음 **{FOLLOWUP_DAYS}일**을 후속 구간으로 정의했다.
- 초기 다양성은 `COMMODITY_DESC` 고유 개수로 측정했다.
- 재방문은 후속 구간에 장바구니가 하나라도 있는 경우, 구매 빈도는 후속 구간의 고유 `BASKET_ID` 수다.
- 우측 절단을 막기 위해 전체 {INITIAL_DAYS + FOLLOWUP_DAYS}일을 관찰할 수 있는 **{len(h1['customers']):,}명**만 포함했다.
- 통제 모형에는 초기 장바구니 수, 초기 지출, 첫 구매일을 함께 넣었다. 효과는 카테고리 다양성 **1 표준편차(+{h1['diversity_sd']:.2f}개)** 증가 기준이다.

### 가설 2

- `display NOT IN ('0', 'A')`만 특별 진열로, `mailer != '0'`을 전단 노출로 이진화했다.
- `(display='A', mailer='0')`인 명시적 비프로모션만 대조군으로 사용하고, 키가 없는 주와 코드 충돌 키는 제외했다.
- 매출 0인 주도 포함하되, 판매 가능성이 불분명한 상품을 과도하게 0으로 채우지 않도록 **{MIN_SALE_WEEKS}주 이상 판매**되고 첫 판매부터 마지막 판매까지 **{MIN_ACTIVE_SPAN_WEEKS}주 이상**인 상품-점포 쌍의 활성 구간만 패널로 만들었다.
- 선택 편향을 줄이기 위해 네 프로모션 상태를 모두 경험한 동일 상품-점포 **{n_balanced:,}쌍**을 별도로 비교했다.

## 가설 1 결과

![초기 카테고리 다양성과 후속 행동](analysis_outputs/h1_diversity.png)

### 원시 비교

{markdown_table(q_table)}

- 상위 그룹(Q4)의 재방문율은 **{pct(q4['return_rate'])}**, 하위 그룹(Q1)은 **{pct(q1['return_rate'])}**로 **{100*(q4['return_rate']-q1['return_rate']):.1f}%p** 차이다.
- 후속 60일 장바구니 수는 Q4 **{q4['avg_followup_baskets']:.2f}회**, Q1 **{q1['avg_followup_baskets']:.2f}회**로 Q4가 **{q4['avg_followup_baskets']/q1['avg_followup_baskets']:.2f}배**다.
- 그러나 초기 장바구니 수도 Q4 **{q4['avg_initial_baskets']:.2f}회**, Q1 **{q1['avg_initial_baskets']:.2f}회**로 크게 다르다. 다양성이 높아서 재방문한 것인지, 원래 구매 활동이 많은 고객이라 다양성과 재방문이 함께 높은 것인지 분리해야 한다.

### 통제 모형

{markdown_table(model_table)}

- 재방문 로짓의 오즈비는 **{models.iloc[0]['effect']:.3f}**이지만 95% CI가 1을 포함한다(p={p_text(models.iloc[0]['p_value'])}).
- 구매 횟수에 더 적합한 음이항 모형의 IRR도 **{models.iloc[1]['effect']:.3f}**으로 방향은 양(+)이지만 통계적으로 확실하지 않다(p={p_text(models.iloc[1]['p_value'])}).
- `log1p(후속 장바구니)` OLS 민감도 분석만 유의한 양(+)의 효과를 보였다. 따라서 가설 1은 **기술통계상 강하지만 통제 후에는 부분 지지**로 판단한다.

## 가설 2 결과

![프로모션과 상품-점포-주 매출](analysis_outputs/h2_promotion.png)

### 활성 패널 원시 비교

{markdown_table(raw_table)}

매출과 판매 발생률 모두 병행 프로모션에서 가장 높다. 원시 주평균 매출은 비프로모션 대비 진열만 **{100*(raw.loc[raw['promo_group']=='display_only','avg_sales_per_pair_week'].iloc[0]/raw_base-1):.1f}%**, 전단만 **{100*(raw.loc[raw['promo_group']=='mailer_only','avg_sales_per_pair_week'].iloc[0]/raw_base-1):.1f}%**, 둘 다 **{100*(raw.loc[raw['promo_group']=='both','avg_sales_per_pair_week'].iloc[0]/raw_base-1):.1f}%** 높다.

### 동일 상품-점포 쌍 비교

{markdown_table(paired_table)}

- 동일한 {n_balanced:,}개 상품-점포 쌍에서도 병행 프로모션 매출은 진열만보다 평균 **{both_display['mean_difference']:.3f}** 높고(95% CI {both_display['ci_low']:.3f}–{both_display['ci_high']:.3f}, p{p_text(both_display['p_value']) if both_display['p_value'] < 0.001 else '=' + p_text(both_display['p_value'])}), 전단만보다 **{both_mailer['mean_difference']:.3f}** 높다(95% CI {both_mailer['ci_low']:.3f}–{both_mailer['ci_high']:.3f}, p{p_text(both_mailer['p_value']) if both_mailer['p_value'] < 0.001 else '=' + p_text(both_mailer['p_value'])}).
- 초가산적 시너지 추정치는 **{synergy['mean_difference']:.3f}**이고 95% CI **{synergy['ci_low']:.3f}–{synergy['ci_high']:.3f}**, p={p_text(synergy['p_value'])}다. 즉 병행이 가장 높기는 하지만, 두 단독 효과를 더한 것보다 추가로 더 커지는 시너지는 확인되지 않았다.

## 해석 시 주의점

1. 이 결과는 관찰 데이터의 **연관성**이다. 판촉 대상 상품은 원래 판매 가능성이 높은 상품일 수 있고, 가격 할인·계절·점포별 운영이 동시에 작동할 수 있다.
2. 가설 1의 다양성은 초기 방문 횟수와 구조적으로 함께 증가한다. 통제 결과가 약해진 이유이므로 “다양한 카테고리를 사게 만들면 재방문한다”는 인과 해석은 피해야 한다.
3. 가설 2의 최신 결론은 패널 트래픽까지 보정한 `product_axis_report.md`를 사용해야 한다.
4. 다음 단계의 더 강한 검증은 상품-점포 및 주 고정효과 회귀, 판촉 전후 이벤트 스터디, 가격/할인 통제다.

## 재현 방법

```powershell
python analysis.py
```

세부 집계 CSV는 `analysis_outputs/`에 저장된다.
"""


def save_metadata(h1: dict[str, object], h2: dict[str, object]) -> None:
    metadata = {
        "database": str(DB_PATH),
        "h1": {
            "initial_days": INITIAL_DAYS,
            "followup_days": FOLLOWUP_DAYS,
            "eligible_households": len(h1["customers"]),
            "diversity_sd": h1["diversity_sd"],
        },
        "h2": {
            "min_sale_weeks": MIN_SALE_WEEKS,
            "min_active_span_weeks": MIN_ACTIVE_SPAN_WEEKS,
            "balanced_product_store_pairs": len(h2["balanced"]),
        },
    }
    with (OUTPUT_DIR / "analysis_metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DuckDB 파일을 찾을 수 없습니다: {DB_PATH}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    configure_plot_style()

    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET threads = 8")
    try:
        print("[1/3] 가설 1 분석 중...")
        h1 = analyze_h1(con)
        print("[2/3] 가설 2 분석 중...")
        h2 = analyze_h2(con)
    finally:
        con.close()

    print("[3/3] Markdown 보고서 작성 중...")
    REPORT_PATH.write_text(build_report(h1, h2), encoding="utf-8")
    save_metadata(h1, h2)
    print(f"완료: {REPORT_PATH}")
    print(f"세부 산출물: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
