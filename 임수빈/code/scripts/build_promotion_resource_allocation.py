from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
REPORT_PATH = ROOT / "reports" / "promotion_resource_allocation_analysis.md"
MARGINS = [0.20, 0.30, 0.40]
UNIT_COST_SCENARIOS = [0.01, 0.025, 0.05]


def minmax(series):
    low, high = series.min(), series.max()
    if high == low:
        return pd.Series(1.0, index=series.index)
    return (series - low) / (high - low)


def main():
    categories = pd.read_csv(DATA / "priority_category_robustness_summary.csv")
    products = pd.read_csv(DATA / "promotion_priority_products.csv")

    products["panel_incremental_revenue_opportunity"] = (
        products["conservative_revenue_effect"].clip(lower=0) * products["coverage_matched_pairs"]
    )
    for margin in MARGINS:
        suffix = int(margin * 100)
        products[f"break_even_cost_per_execution_m{suffix}"] = products["conservative_revenue_effect"] * margin
        products[f"panel_incremental_gross_profit_m{suffix}"] = (
            products["panel_incremental_revenue_opportunity"] * margin
        )

    product_reliability = products[[
        "PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC", "BRAND", "SUB_COMMODITY_DESC",
        "rank_within_category", "conservative_sales_effect", "conservative_revenue_effect",
        "coverage_matched_pairs", "panel_incremental_revenue_opportunity",
        "break_even_cost_per_execution_m20", "break_even_cost_per_execution_m30",
        "break_even_cost_per_execution_m40", "panel_incremental_gross_profit_m30",
    ]].copy()
    product_reliability["product_action"] = np.select(
        [
            product_reliability["rank_within_category"].le(3)
            & product_reliability["conservative_revenue_effect"].gt(0)
            & product_reliability["coverage_matched_pairs"].ge(200),
            product_reliability["rank_within_category"].le(10)
            & product_reliability["conservative_revenue_effect"].gt(0),
        ],
        ["1차 상품", "예비 상품"],
        default="보류",
    )

    portfolio = products.groupby(["DEPARTMENT", "COMMODITY_DESC"]).agg(
        candidate_products=("PRODUCT_ID", "nunique"),
        covered_matched_pairs=("coverage_matched_pairs", "sum"),
        weighted_conservative_revenue_effect=(
            "conservative_revenue_effect",
            lambda x: np.average(x, weights=products.loc[x.index, "coverage_matched_pairs"]),
        ),
        panel_incremental_revenue_opportunity=("panel_incremental_revenue_opportunity", "sum"),
        panel_incremental_gross_profit_m20=("panel_incremental_gross_profit_m20", "sum"),
        panel_incremental_gross_profit_m30=("panel_incremental_gross_profit_m30", "sum"),
        panel_incremental_gross_profit_m40=("panel_incremental_gross_profit_m40", "sum"),
    ).reset_index()
    portfolio = categories.merge(portfolio, on=["DEPARTMENT", "COMMODITY_DESC"], how="left", validate="one_to_one")
    portfolio["reliability_rate"] = portfolio["passed_checks"] / portfolio["checks"]
    portfolio["opportunity_score"] = (
        minmax(portfolio["panel_incremental_revenue_opportunity"]) * 0.40
        + minmax(portfolio["weighted_conservative_revenue_effect"]) * 0.30
        + portfolio["reliability_rate"] * 0.30
    )
    portfolio["allocation_group"] = np.select(
        [
            portfolio["final_recommendation"].eq("최우선 적용") & portfolio["reliability_rate"].eq(1),
            portfolio["final_recommendation"].eq("파일럿"),
        ],
        ["통제된 확대", "제한 파일럿"],
        default="보류",
    )
    portfolio = portfolio.sort_values(
        ["allocation_group", "opportunity_score"],
        key=lambda s: s.map({"통제된 확대": 0, "제한 파일럿": 1, "보류": 2}) if s.name == "allocation_group" else -s,
    )
    positive_opportunity = portfolio["panel_incremental_revenue_opportunity"].clip(lower=0)
    portfolio["panel_opportunity_share"] = positive_opportunity / positive_opportunity.sum()
    for margin in MARGINS:
        portfolio[f"break_even_cost_per_execution_m{int(margin * 100)}"] = (
            portfolio["weighted_conservative_revenue_effect"] * margin
        )

    scenario_rows = []
    for row in products.itertuples(index=False):
        for margin in MARGINS:
            gross_profit = row.panel_incremental_revenue_opportunity * margin
            for unit_cost in UNIT_COST_SCENARIOS:
                extra_cost = row.coverage_matched_pairs * unit_cost
                scenario_rows.append(
                    {
                        "PRODUCT_ID": row.PRODUCT_ID,
                        "DEPARTMENT": row.DEPARTMENT,
                        "COMMODITY_DESC": row.COMMODITY_DESC,
                        "margin_rate": margin,
                        "extra_cost_per_execution": unit_cost,
                        "panel_incremental_revenue_opportunity": row.panel_incremental_revenue_opportunity,
                        "panel_incremental_gross_profit": gross_profit,
                        "panel_extra_cost": extra_cost,
                        "panel_net_incremental_profit": gross_profit - extra_cost,
                        "profitable_in_panel_scenario": gross_profit > extra_cost,
                    }
                )
    scenarios = pd.DataFrame(scenario_rows)
    category_scenarios = scenarios.groupby(
        ["DEPARTMENT", "COMMODITY_DESC", "margin_rate", "extra_cost_per_execution"]
    ).agg(
        products=("PRODUCT_ID", "nunique"),
        profitable_products=("profitable_in_panel_scenario", "sum"),
        panel_incremental_revenue_opportunity=("panel_incremental_revenue_opportunity", "sum"),
        panel_incremental_gross_profit=("panel_incremental_gross_profit", "sum"),
        panel_extra_cost=("panel_extra_cost", "sum"),
        panel_net_incremental_profit=("panel_net_incremental_profit", "sum"),
    ).reset_index()
    category_scenarios["profitable_product_share"] = (
        category_scenarios["profitable_products"] / category_scenarios["products"]
    )

    portfolio.to_csv(DATA / "promotion_resource_allocation_categories.csv", index=False, encoding="utf-8-sig")
    product_reliability.to_csv(DATA / "promotion_resource_allocation_products.csv", index=False, encoding="utf-8-sig")
    category_scenarios.to_csv(DATA / "promotion_resource_allocation_scenarios.csv", index=False, encoding="utf-8-sig")

    base_scenario = category_scenarios.loc[
        category_scenarios["margin_rate"].eq(0.30)
        & category_scenarios["extra_cost_per_execution"].eq(0.025)
    ].merge(
        portfolio[["DEPARTMENT", "COMMODITY_DESC", "allocation_group"]],
        on=["DEPARTMENT", "COMMODITY_DESC"], how="left"
    ).sort_values("panel_net_incremental_profit", ascending=False)
    top_products = product_reliability.loc[product_reliability["product_action"].eq("1차 상품")].sort_values(
        "panel_incremental_gross_profit_m30", ascending=False
    )
    lines = [
        "# 결합 프로모션 자원배분 및 손익분기 분석",
        "",
        "## 해석 단위",
        "",
        "- 거래 데이터는 전체 점포 POS가 아니라 2,500개 패널 가구의 구매 기록이다.",
        "- 따라서 아래 증분매출·이익은 실제 점포 ROI가 아니라 패널 관측 범위의 상대적 기회규모다.",
        "- 상품별 보수적 증분매출은 `진열만 대비`와 `전단만 대비` 중 더 작은 효과를 사용했다.",
        "- 적용 가능 규모는 두 비교 중 더 작은 매칭 수를 사용했다.",
        "- 손익분기 비용은 결합 프로모션 1회당 추가로 허용 가능한 비용의 패널 기준 상한이다.",
        "",
        "## 카테고리 자원배분",
        "",
        "| 카테고리 | 판정 | 안정성 | 후보 상품 | 적용규모 | 보수적 매출효과 | 패널 기회매출 | 30% 마진 기회이익 | 30% 마진 손익분기 비용/회 | 패널 기회비중 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in portfolio.itertuples(index=False):
        lines.append(
            f"| {row.COMMODITY_DESC} | {row.allocation_group} | {row.passed_checks}/{row.checks} | "
            f"{int(row.candidate_products)} | {int(row.covered_matched_pairs):,} | "
            f"{row.weighted_conservative_revenue_effect:.3f} | {row.panel_incremental_revenue_opportunity:,.1f} | "
            f"{row.panel_incremental_gross_profit_m30:,.1f} | {row.break_even_cost_per_execution_m30:.3f} | "
            f"{row.panel_opportunity_share:.1%} |"
        )
    lines += [
        "",
        "## 기준 비용 시나리오",
        "",
        "아래는 마진 30%, 결합 프로모션 추가비용 0.025/상품×매장×주를 가정한 패널 기준 민감도다. 실제 비용·마진이 아니라 비교를 위한 가정이다.",
        "",
        "| 카테고리 | 판정 | 수익 상품 비율 | 패널 증분이익 |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in base_scenario.itertuples(index=False):
        lines.append(
            f"| {row.COMMODITY_DESC} | {row.allocation_group} | {row.profitable_product_share:.1%} | "
            f"{row.panel_net_incremental_profit:,.1f} |"
        )
    lines += [
        "",
        "## 1차 상품 후보",
        "",
        "| 카테고리 | PRODUCT_ID | 브랜드 | 보수적 매출효과 | 적용규모 | 30% 마진 손익분기 비용/회 | 30% 마진 기회이익 |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in top_products.head(20).itertuples(index=False):
        lines.append(
            f"| {row.COMMODITY_DESC} | {row.PRODUCT_ID} | {row.BRAND} | {row.conservative_revenue_effect:.3f} | "
            f"{int(row.coverage_matched_pairs):,} | {row.break_even_cost_per_execution_m30:.3f} | "
            f"{row.panel_incremental_gross_profit_m30:,.1f} |"
        )
    lines += [
        "",
        "## 실행안",
        "",
        "- BACON, LUNCHMEAT, DINNER SAUSAGE는 통제된 확대 후보로 두되 실제 매장 비용을 넣어 손익분기 조건을 다시 계산한다.",
        "- 나머지 네 카테고리는 제한 파일럿으로 유지하고, 기준 비용 시나리오에서 손익이 양수인 구체 상품만 사용한다.",
        "- 패널 기회비중은 관측 규모를 포함한 상대 지표이며 예산 배분 비율이 아니다. 안정성 등급을 넘어 파일럿 카테고리에 대규모 예산을 배정하는 근거로 사용하지 않는다.",
        "- 실제 의사결정 전 전체 POS 매출, 상품 마진, 전단 제작·배포비, 진열 운영비를 입력해야 한다.",
        "- 고객 위험 명단과 연결하지 않고 상품×매장 단위 무작위 실험으로 증분이익을 측정한다.",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
