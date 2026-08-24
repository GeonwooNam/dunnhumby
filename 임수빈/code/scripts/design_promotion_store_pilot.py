from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
REPORT_PATH = ROOT / "reports" / "promotion_store_pilot_design.md"
CATEGORIES = ["BACON", "LUNCHMEAT", "DINNER SAUSAGE"]
ARMS = ["전단+진열", "전단만", "진열만"]
BASELINE_START = 76
BASELINE_END = 101
PILOT_WEEKS = 8
MIN_ACTIVE_WEEKS = 8
RANDOM_SEED = 42


def select_products(resource_products):
    selected = []
    for category, group in resource_products.loc[
        resource_products["COMMODITY_DESC"].isin(CATEGORIES)
    ].groupby("COMMODITY_DESC"):
        candidates = group.loc[group["coverage_matched_pairs"].ge(50)].sort_values(
            ["conservative_revenue_effect", "coverage_matched_pairs"], ascending=False
        ).head(3).copy()
        candidates["pilot_product_rank"] = np.arange(1, len(candidates) + 1)
        selected.append(candidates)
    return pd.concat(selected, ignore_index=True)


def standardized_mean_difference(frame, arm_a, arm_b, column):
    a = frame.loc[frame["pilot_arm"].eq(arm_a), column].to_numpy(float)
    b = frame.loc[frame["pilot_arm"].eq(arm_b), column].to_numpy(float)
    pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    return 0.0 if pooled == 0 else (a.mean() - b.mean()) / pooled


def imbalance_score(assignment):
    columns = ["baseline_category_revenue", "baseline_total_revenue", "category_active_weeks", "category_trend"]
    scores = []
    for arm in ARMS[1:]:
        for column in columns:
            scores.append(abs(standardized_mean_difference(assignment, ARMS[0], arm, column)))
    return max(scores)


def constrained_randomization(stores, category_seed):
    data = stores.copy()
    data["revenue_stratum"] = pd.qcut(
        data["baseline_category_revenue"].rank(method="first"), q=4, labels=False
    )
    best = None
    best_score = np.inf
    for attempt in range(2000):
        rng = np.random.default_rng(category_seed + attempt)
        parts = []
        for _, stratum in data.groupby("revenue_stratum"):
            shuffled = stratum.sample(frac=1, random_state=int(rng.integers(0, 2**31 - 1))).copy()
            offset = int(rng.integers(0, len(ARMS)))
            shuffled["pilot_arm"] = [ARMS[(i + offset) % len(ARMS)] for i in range(len(shuffled))]
            parts.append(shuffled)
        candidate = pd.concat(parts).sort_values("STORE_ID")
        counts = candidate["pilot_arm"].value_counts()
        if counts.max() - counts.min() > 1:
            continue
        score = imbalance_score(candidate)
        if score < best_score:
            best = candidate
            best_score = score
    if best is None:
        raise RuntimeError("균형 조건을 만족하는 무작위 배정을 찾지 못했습니다.")
    best["randomization_max_abs_smd"] = best_score
    return best


def power_table(store_metrics, category):
    before = store_metrics["pre8_category_revenue"].to_numpy(float)
    after = store_metrics["post8_category_revenue"].to_numpy(float)
    rho = np.corrcoef(before, after)[0, 1] if len(store_metrics) > 2 else 0
    rho = 0 if not np.isfinite(rho) else rho
    residual_sd = after.std(ddof=1) * np.sqrt(max(1 - rho**2, 0.05))
    mean_8w = np.mean(np.r_[before, after])
    alpha_each = 0.025
    z_alpha = norm.ppf(1 - alpha_each / 2)
    z_power = norm.ppf(0.80)
    available_per_arm = len(store_metrics) // 3
    rows = []
    for relative_lift in [0.05, 0.10, 0.15, 0.20]:
        delta = mean_8w * relative_lift
        required = int(np.ceil(2 * (z_alpha + z_power) ** 2 * residual_sd**2 / delta**2)) if delta > 0 else np.nan
        rows.append(
            {
                "COMMODITY_DESC": category,
                "relative_lift": relative_lift,
                "mean_8w_category_revenue": mean_8w,
                "pre_post_correlation": rho,
                "ancova_residual_sd": residual_sd,
                "required_stores_per_arm": required,
                "available_stores_per_arm": available_per_arm,
                "feasible_with_current_panel": available_per_arm >= required,
            }
        )
    mde = (z_alpha + z_power) * residual_sd * np.sqrt(2 / available_per_arm)
    for row in rows:
        row["minimum_detectable_absolute_effect"] = mde
        row["minimum_detectable_relative_lift"] = mde / mean_8w if mean_8w else np.nan
    return pd.DataFrame(rows)


def main():
    resource_products = pd.read_csv(DATA / "promotion_resource_allocation_products.csv")
    selected_products = select_products(resource_products)
    tx = pd.read_csv(
        ROOT / "transaction_data.csv",
        usecols=["STORE_ID", "WEEK_NO", "PRODUCT_ID", "SALES_VALUE", "BASKET_ID"],
    )
    product = pd.read_csv(ROOT / "product.csv", usecols=["PRODUCT_ID", "COMMODITY_DESC"])
    tx = tx.loc[tx["WEEK_NO"].between(BASELINE_START, BASELINE_END)].merge(
        product, on="PRODUCT_ID", how="left", validate="many_to_one"
    )
    total_store = tx.groupby("STORE_ID")["SALES_VALUE"].sum().rename("baseline_total_revenue")

    assignments = []
    power_parts = []
    for category_index, category in enumerate(CATEGORIES):
        category_tx = tx.loc[tx["COMMODITY_DESC"].eq(category)].copy()
        category_store = category_tx.groupby("STORE_ID").agg(
            baseline_category_revenue=("SALES_VALUE", "sum"),
            category_active_weeks=("WEEK_NO", "nunique"),
            category_baskets=("BASKET_ID", "nunique"),
        ).reset_index()
        selected_ids = set(
            selected_products.loc[selected_products["COMMODITY_DESC"].eq(category), "PRODUCT_ID"]
        )
        carried = set(category_tx.loc[category_tx["PRODUCT_ID"].isin(selected_ids), "STORE_ID"])
        category_store = category_store.loc[
            category_store["category_active_weeks"].ge(MIN_ACTIVE_WEEKS)
            & category_store["STORE_ID"].isin(carried)
        ].copy()
        category_store = category_store.merge(total_store, on="STORE_ID", how="left")

        early = category_tx.loc[category_tx["WEEK_NO"].between(BASELINE_START, BASELINE_START + 7)].groupby(
            "STORE_ID"
        )["SALES_VALUE"].sum()
        late = category_tx.loc[category_tx["WEEK_NO"].between(BASELINE_END - 7, BASELINE_END)].groupby(
            "STORE_ID"
        )["SALES_VALUE"].sum()
        category_store["pre8_category_revenue"] = category_store["STORE_ID"].map(early).fillna(0)
        category_store["post8_category_revenue"] = category_store["STORE_ID"].map(late).fillna(0)
        category_store["category_trend"] = (
            category_store["post8_category_revenue"] - category_store["pre8_category_revenue"]
        ) / category_store["pre8_category_revenue"].replace(0, np.nan)
        category_store["category_trend"] = category_store["category_trend"].replace([np.inf, -np.inf], np.nan).fillna(0)
        category_store["COMMODITY_DESC"] = category
        assigned = constrained_randomization(category_store, RANDOM_SEED + category_index * 10000)
        assigned["pilot_duration_weeks"] = PILOT_WEEKS
        assigned["selected_product_ids"] = " | ".join(
            selected_products.loc[selected_products["COMMODITY_DESC"].eq(category), "PRODUCT_ID"].astype(str)
        )
        assignments.append(assigned)
        power_parts.append(power_table(category_store, category))

    assignment = pd.concat(assignments, ignore_index=True)
    power = pd.concat(power_parts, ignore_index=True)
    selected_products.to_csv(DATA / "promotion_pilot_selected_products.csv", index=False, encoding="utf-8-sig")
    assignment.to_csv(DATA / "promotion_pilot_store_assignment.csv", index=False, encoding="utf-8-sig")
    power.to_csv(DATA / "promotion_pilot_power_analysis.csv", index=False, encoding="utf-8-sig")

    tracking_rows = []
    for row in assignment.itertuples(index=False):
        for pilot_week in range(1, PILOT_WEEKS + 1):
            tracking_rows.append(
                {
                    "COMMODITY_DESC": row.COMMODITY_DESC,
                    "STORE_ID": row.STORE_ID,
                    "pilot_arm": row.pilot_arm,
                    "pilot_week": pilot_week,
                    "selected_product_ids": row.selected_product_ids,
                    "category_revenue": np.nan,
                    "selected_product_revenue": np.nan,
                    "category_units": np.nan,
                    "category_baskets": np.nan,
                    "selected_product_baskets": np.nan,
                    "mailer_cost": np.nan,
                    "display_cost": np.nan,
                    "gross_margin_rate": np.nan,
                    "stockout_flag": np.nan,
                    "execution_compliance": np.nan,
                }
            )
    pd.DataFrame(tracking_rows).to_csv(
        DATA / "promotion_pilot_weekly_tracking_template.csv", index=False, encoding="utf-8-sig"
    )

    balance_rows = []
    for category, group in assignment.groupby("COMMODITY_DESC"):
        for comparator in ARMS[1:]:
            for column in ["baseline_category_revenue", "baseline_total_revenue", "category_active_weeks", "category_trend"]:
                balance_rows.append(
                    {
                        "COMMODITY_DESC": category,
                        "comparison": f"전단+진열 - {comparator}",
                        "covariate": column,
                        "smd": standardized_mean_difference(group, "전단+진열", comparator, column),
                    }
                )
    balance = pd.DataFrame(balance_rows)
    balance.to_csv(DATA / "promotion_pilot_randomization_balance.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# 결합 프로모션 상품×매장 파일럿 설계",
        "",
        "## 실험 목적",
        "",
        "> BACON, LUNCHMEAT, DINNER SAUSAGE에서 전단+진열이 전단만과 진열만보다 카테고리 전체 증분이익을 높이는지 검증한다.",
        "",
        "## 설계",
        "",
        f"- 과거 매장 산정기간: W{BASELINE_START}-W{BASELINE_END}",
        f"- 파일럿 기간: {PILOT_WEEKS}주",
        f"- 적격 매장: 카테고리 판매가 {MIN_ACTIVE_WEEKS}주 이상 관측되고 선정 상품을 한 번 이상 판매한 매장",
        "- 실험군: 전단+진열",
        "- 비교군 1: 전단만",
        "- 비교군 2: 진열만",
        "- 무작위화: 카테고리 과거 매출 사분위 내 균형 배정 후 사전 변수 최대 SMD가 가장 작은 배정 선택",
        "- 다중 비교: 결합군 대 두 단독군, 비교별 양측 alpha=0.025",
        "",
        "## 카테고리별 배정",
        "",
        "| 카테고리 | 총 매장 | 결합 | 전단만 | 진열만 | 최대 절대 SMD | 현재 표본 MDE |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, group in assignment.groupby("COMMODITY_DESC", sort=False):
        counts = group["pilot_arm"].value_counts()
        mde = power.loc[power["COMMODITY_DESC"].eq(category), "minimum_detectable_relative_lift"].iloc[0]
        lines.append(
            f"| {category} | {len(group)} | {counts.get('전단+진열', 0)} | {counts.get('전단만', 0)} | "
            f"{counts.get('진열만', 0)} | {balance.loc[balance['COMMODITY_DESC'].eq(category), 'smd'].abs().max():.3f} | {mde:.1%} |"
        )
    lines += [
        "",
        "## 선정 상품",
        "",
        "| 카테고리 | 순위 | PRODUCT_ID | 브랜드 | 보수적 증분매출 | 과거 적용규모 |",
        "| --- | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in selected_products.sort_values(["COMMODITY_DESC", "pilot_product_rank"]).itertuples(index=False):
        lines.append(
            f"| {row.COMMODITY_DESC} | {row.pilot_product_rank} | {row.PRODUCT_ID} | {row.BRAND} | "
            f"{row.conservative_revenue_effect:.3f} | {int(row.coverage_matched_pairs):,} |"
        )
    lines += [
        "",
        "## 표본 수와 탐지 가능 효과",
        "",
        "| 카테고리 | 목표 리프트 | 필요 매장/군 | 보유 매장/군 | 실행 가능 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in power.itertuples(index=False):
        lines.append(
            f"| {row.COMMODITY_DESC} | {row.relative_lift:.0%} | {row.required_stores_per_arm} | "
            f"{row.available_stores_per_arm} | {'예' if row.feasible_with_current_panel else '아니오'} |"
        )
    lines += [
        "",
        "## KPI와 성공 기준",
        "",
        "1. 1차 KPI: 카테고리 전체 매출의 사전 대비 변화. 선정 상품끼리의 잠식을 포함해 측정한다.",
        "2. 공동 1차 비교: 결합-전단만, 결합-진열만. 두 비교가 모두 양수여야 확대한다.",
        "3. 경제성: 카테고리 전체 증분매출×실제 마진 - 전단비 - 진열비가 0보다 커야 한다.",
        "4. 실행 품질: 품절·미진열·전단 누락을 매주 기록하고 per-protocol과 intention-to-treat를 함께 보고한다.",
        "5. 안전장치: 카테고리 전체 매출이 늘지 않고 선정 상품만 증가하면 잠식으로 판정해 확대하지 않는다.",
        "",
        "## 주의사항",
        "",
        "- 현재 표본 수 계산은 패널 매출의 과거 분산과 사전-사후 상관을 이용한 근사치다. 전체 POS를 확보하면 반드시 다시 계산한다.",
        "- 배정표는 분석용 제안이며 실제 매장 운영 가능성·재고·지역 중복을 확인한 뒤 잠근다.",
        "- 배정 확정 후 결과를 보기 전에 분석계획과 제외 기준을 고정해야 한다.",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
