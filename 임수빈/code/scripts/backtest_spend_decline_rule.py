from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "spend_decline_rule_rolling_backtest.md"
ORIGINS = [50, 58, 66, 74, 82, 90]
BASELINE_WEEKS = 26
SIGNAL_WEEKS = 8
FOLLOWUP_WEEKS = 8


def safe_divide(numerator, denominator):
    return np.nan if denominator == 0 else numerator / denominator


def build_snapshot(tx, origin):
    baseline_start = origin - BASELINE_WEEKS - SIGNAL_WEEKS + 1
    baseline_end = origin - SIGNAL_WEEKS
    signal_start = origin - SIGNAL_WEEKS + 1
    followup_end = origin + FOLLOWUP_WEEKS

    baseline = tx.loc[tx["WEEK_NO"].between(baseline_start, baseline_end)].copy()
    through_signal = tx.loc[tx["WEEK_NO"].between(baseline_start, origin)].copy()
    recent = tx.loc[tx["WEEK_NO"].between(signal_start, origin)].copy()
    followup = tx.loc[tx["WEEK_NO"].between(origin + 1, followup_end)].copy()

    active_weeks = baseline.groupby("household_key")["WEEK_NO"].nunique()
    eligible = active_weeks.loc[active_weeks >= 8].index
    baseline_revenue = baseline.groupby("household_key")["SALES_VALUE"].sum()
    value_cutoff = baseline_revenue.loc[baseline_revenue.index.isin(eligible)].quantile(0.8)
    high_value = baseline_revenue.loc[
        baseline_revenue.index.isin(eligible) & baseline_revenue.ge(value_cutoff)
    ].index

    purchase_days = baseline[["household_key", "DAY"]].drop_duplicates().sort_values(["household_key", "DAY"])
    purchase_days["gap"] = purchase_days.groupby("household_key")["DAY"].diff()
    median_gap = purchase_days.groupby("household_key")["gap"].median()
    last_day = through_signal.groupby("household_key")["DAY"].max()
    origin_day = int(tx.loc[tx["WEEK_NO"].eq(origin), "DAY"].max())
    gap_ratio = (origin_day - last_day) / median_gap

    diversity_parts = []
    for end_week in range(baseline_start + SIGNAL_WEEKS - 1, baseline_end + 1):
        diversity_parts.append(
            baseline.loc[baseline["WEEK_NO"].between(end_week - SIGNAL_WEEKS + 1, end_week)]
            .groupby("household_key")["COMMODITY_DESC"]
            .nunique()
            .rename(end_week)
        )
    usual_diversity = pd.concat(diversity_parts, axis=1).median(axis=1)
    recent_diversity = recent.groupby("household_key")["COMMODITY_DESC"].nunique()
    diversity_ratio = recent_diversity.reindex(usual_diversity.index, fill_value=0) / usual_diversity

    future_revenue = followup.groupby("household_key")["SALES_VALUE"].sum()
    snapshot = pd.DataFrame(index=high_value)
    snapshot.index.name = "household_key"
    snapshot["origin_week"] = origin
    snapshot["baseline_start_week"] = baseline_start
    snapshot["baseline_end_week"] = baseline_end
    snapshot["baseline_revenue"] = baseline_revenue.reindex(high_value)
    snapshot["baseline_weekly_revenue"] = snapshot["baseline_revenue"] / BASELINE_WEEKS
    snapshot["future_8w_revenue"] = future_revenue.reindex(high_value, fill_value=0)
    snapshot["future_weekly_revenue"] = snapshot["future_8w_revenue"] / FOLLOWUP_WEEKS
    snapshot["future_revenue_ratio"] = snapshot["future_weekly_revenue"] / snapshot["baseline_weekly_revenue"]
    snapshot["spend_decline_30pct"] = snapshot["future_revenue_ratio"] < 0.7
    snapshot["median_gap_days"] = median_gap.reindex(high_value)
    snapshot["gap_ratio"] = gap_ratio.reindex(high_value)
    snapshot["usual_category_diversity"] = usual_diversity.reindex(high_value)
    snapshot["recent_category_diversity"] = recent_diversity.reindex(high_value, fill_value=0)
    snapshot["diversity_ratio"] = diversity_ratio.reindex(high_value)
    snapshot["interval_signal"] = snapshot["gap_ratio"] >= 1.5
    snapshot["diversity_signal"] = snapshot["diversity_ratio"] < 0.7
    snapshot["combined_signal"] = snapshot["interval_signal"] & snapshot["diversity_signal"]
    expected_8w = snapshot["baseline_weekly_revenue"] * FOLLOWUP_WEEKS
    snapshot["revenue_loss"] = (expected_8w - snapshot["future_8w_revenue"]).clip(lower=0)
    snapshot["value_cutoff"] = value_cutoff
    return snapshot.reset_index()


def summarize(snapshot, signal_column, signal_name):
    signal = snapshot[signal_column].fillna(False)
    decline = snapshot["spend_decline_30pct"]
    tp = int((signal & decline).sum())
    fp = int((signal & ~decline).sum())
    fn = int((~signal & decline).sum())
    tn = int((~signal & ~decline).sum())
    total_loss = snapshot.loc[decline, "revenue_loss"].sum()
    captured_loss = snapshot.loc[signal & decline, "revenue_loss"].sum()
    return {
        "origin_week": int(snapshot["origin_week"].iloc[0]),
        "signal": signal_name,
        "high_value_customers": len(snapshot),
        "alerts": int(signal.sum()),
        "declines": int(decline.sum()),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "base_rate": decline.mean(),
        "precision": safe_divide(tp, tp + fp),
        "recall": safe_divide(tp, tp + fn),
        "specificity": safe_divide(tn, tn + fp),
        "precision_lift": safe_divide(safe_divide(tp, tp + fp), decline.mean()),
        "total_revenue_loss": total_loss,
        "captured_revenue_loss": captured_loss,
        "revenue_loss_recall": safe_divide(captured_loss, total_loss),
    }


def main():
    tx = pd.read_csv(
        ROOT / "transaction_data.csv",
        usecols=["household_key", "BASKET_ID", "DAY", "PRODUCT_ID", "SALES_VALUE", "WEEK_NO"],
    )
    products = pd.read_csv(ROOT / "product.csv", usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"])
    tx = tx.merge(products, on="PRODUCT_ID", how="left", validate="many_to_one")
    tx = tx.loc[
        tx["WEEK_NO"].between(17, 101)
        & ~tx["DEPARTMENT"].isin(["KIOSK-GAS", "MISC SALES TRAN", "MISC. TRANS."])
    ].copy()

    snapshots = []
    summaries = []
    signals = [
        ("interval_signal", "방문 간격만"),
        ("diversity_signal", "카테고리 다양성만"),
        ("combined_signal", "결합 규칙"),
    ]
    for origin in ORIGINS:
        snapshot = build_snapshot(tx, origin)
        snapshots.append(snapshot)
        for column, name in signals:
            summaries.append(summarize(snapshot, column, name))

    detail = pd.concat(snapshots, ignore_index=True)
    summary = pd.DataFrame(summaries)
    detail.to_csv(OUT / "spend_decline_rolling_backtest_customers.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT / "spend_decline_rolling_backtest_summary.csv", index=False, encoding="utf-8-sig")

    combined = summary.loc[summary["signal"].eq("결합 규칙")].copy()
    pooled_tp = combined["tp"].sum()
    pooled_alerts = combined["alerts"].sum()
    pooled_declines = combined["declines"].sum()
    pooled_customers = combined["high_value_customers"].sum()
    pooled_precision = pooled_tp / pooled_alerts
    pooled_recall = pooled_tp / pooled_declines
    pooled_base = pooled_declines / pooled_customers
    pooled_lift = pooled_precision / pooled_base
    pooled_loss_recall = combined["captured_revenue_loss"].sum() / combined["total_revenue_loss"].sum()
    stable = (combined["precision_lift"] > 1).sum()
    decision = (
        "규칙은 여러 시점에서 반복적으로 기준 이탈률보다 높은 위험군을 선별했다."
        if stable >= 5 and pooled_lift >= 1.5
        else "규칙의 성능이 시점에 따라 불안정해 현재 형태로 운영 규칙을 확정하기 어렵다."
    )

    lines = [
        "# 지출 감소 조기 탐지 규칙 이동 시점 백테스트",
        "",
        "## 판정",
        "",
        f"> {decision}",
        "",
        "## 사전 고정 설계",
        "",
        "- 기준 시점: W50, W58, W66, W74, W82, W90",
        "- 정상 기준기간: 기준 시점 직전 34주 중 앞 26주",
        "- 신호기간: 기준 시점까지 최근 8주",
        "- 결과기간: 기준 시점 이후 8주",
        "- 대상: 정상 기준기간 활동주차 8주 이상 고객 중 지출 상위 20%",
        "- 방문 간격 신호: 기준 시점 미방문일수 / 개인 기준 중앙 구매간격 >= 1.5",
        "- 다양성 신호: 최근 8주 카테고리 수 / 기준기간 8주 다양성 중앙값 < 0.7",
        "- 정답: 이후 8주 주평균 지출이 기준기간 주평균보다 30% 이상 감소",
        "",
        "## 결합 규칙 전체 결과",
        "",
        f"- 고객-시점 관측치: {pooled_customers:,}",
        f"- 경보: {pooled_alerts:,}",
        f"- 실제 지출 감소: {pooled_declines:,}",
        f"- Precision: {pooled_precision:.1%}",
        f"- Recall: {pooled_recall:.1%}",
        f"- 전체 감소율: {pooled_base:.1%}",
        f"- Precision lift: {pooled_lift:.2f}배",
        f"- 감소 매출 포착률: {pooled_loss_recall:.1%}",
        f"- 기준 이탈률보다 precision이 높았던 시점: {stable}/{len(combined)}",
        "",
        "## 시점별 결합 규칙",
        "",
        "| 기준 주차 | 고가치 고객 | 경보 | 실제 감소 | Precision | Recall | Lift | 감소 매출 포착률 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in combined.itertuples(index=False):
        lines.append(
            f"| {row.origin_week} | {row.high_value_customers} | {row.alerts} | {row.declines} | "
            f"{row.precision:.1%} | {row.recall:.1%} | {row.precision_lift:.2f} | {row.revenue_loss_recall:.1%} |"
        )

    comparison = summary.groupby("signal").agg(
        alerts=("alerts", "sum"), tp=("tp", "sum"), declines=("declines", "sum"),
        customers=("high_value_customers", "sum"), captured_loss=("captured_revenue_loss", "sum"),
        total_loss=("total_revenue_loss", "sum"),
    )
    comparison["precision"] = comparison["tp"] / comparison["alerts"]
    comparison["recall"] = comparison["tp"] / comparison["declines"]
    comparison["base_rate"] = comparison["declines"] / comparison["customers"]
    comparison["lift"] = comparison["precision"] / comparison["base_rate"]
    comparison["loss_recall"] = comparison["captured_loss"] / comparison["total_loss"]
    lines += [
        "",
        "## 신호 구성 비교",
        "",
        "| 신호 | 경보 | Precision | Recall | Lift | 감소 매출 포착률 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in comparison.iterrows():
        lines.append(
            f"| {name} | {int(row.alerts)} | {row.precision:.1%} | {row.recall:.1%} | "
            f"{row.lift:.2f} | {row.loss_recall:.1%} |"
        )
    lines += [
        "",
        "## 해석 주의사항",
        "",
        "- 같은 고객이 여러 기준 시점에 반복 포함될 수 있으므로 전체 합계는 독립 표본에 대한 추론 통계가 아니라 운영 성능 요약이다.",
        "- 고가치 기준과 평소 행동은 매 기준 시점에서 과거 자료만으로 다시 계산해 미래정보 누수를 막았다.",
        "- 현재 단계에서는 고정 임계값의 시간적 재현성만 평가했다. 다음 단계에서 임계값 조합을 탐색할 때는 별도 검증 시점을 남겨야 한다.",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
