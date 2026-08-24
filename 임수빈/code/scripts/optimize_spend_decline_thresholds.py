from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
INPUT = DATA / "spend_decline_rolling_backtest_customers.csv"
REPORT = ROOT / "reports" / "spend_decline_threshold_validation.md"
DEVELOPMENT_WEEKS = [50, 58, 66, 74]
VALIDATION_WEEKS = [82, 90]
DIVERSITY_THRESHOLDS = np.round(np.arange(0.50, 0.91, 0.05), 2)
GAP_THRESHOLDS = [None, 1.25, 1.50, 1.75, 2.00]
MIN_DEVELOPMENT_ALERTS = 30
MIN_DEVELOPMENT_PRECISION = 0.50
RANDOM_SEED = 42


def apply_rule(data, diversity_threshold, gap_threshold):
    signal = data["diversity_ratio"].lt(diversity_threshold)
    if gap_threshold is not None:
        signal &= data["gap_ratio"].ge(gap_threshold)
    return signal.fillna(False)


def metrics(data, signal, decline_cut=0.70):
    decline = data["future_revenue_ratio"].lt(decline_cut)
    tp = int((signal & decline).sum())
    fp = int((signal & ~decline).sum())
    fn = int((~signal & decline).sum())
    alerts = int(signal.sum())
    declines = int(decline.sum())
    precision = tp / alerts if alerts else np.nan
    recall = tp / declines if declines else np.nan
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else np.nan
    base_rate = decline.mean()
    expected = data["baseline_weekly_revenue"] * 8
    loss = (expected - data["future_8w_revenue"]).clip(lower=0)
    total_loss = loss.loc[decline].sum()
    captured_loss = loss.loc[signal & decline].sum()
    return {
        "observations": len(data),
        "alerts": alerts,
        "declines": declines,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "base_rate": base_rate,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "precision_lift": precision / base_rate if base_rate and np.isfinite(precision) else np.nan,
        "captured_revenue_loss": captured_loss,
        "total_revenue_loss": total_loss,
        "revenue_loss_recall": captured_loss / total_loss if total_loss else np.nan,
        "loss_per_alert": captured_loss / alerts if alerts else np.nan,
    }


def cluster_bootstrap(data, diversity_threshold, gap_threshold, decline_cut=0.70, n_boot=5000):
    working = data.copy()
    working["signal"] = apply_rule(working, diversity_threshold, gap_threshold)
    working["decline"] = working["future_revenue_ratio"].lt(decline_cut)
    expected = working["baseline_weekly_revenue"] * 8
    working["loss"] = (expected - working["future_8w_revenue"]).clip(lower=0)
    working["tp"] = working["signal"] & working["decline"]
    working["captured_loss"] = working["loss"].where(working["tp"], 0)
    working["decline_loss"] = working["loss"].where(working["decline"], 0)
    cluster = working.groupby("household_key").agg(
        alerts=("signal", "sum"), declines=("decline", "sum"), tp=("tp", "sum"),
        captured_loss=("captured_loss", "sum"), total_loss=("decline_loss", "sum")
    ).to_numpy(float)
    rng = np.random.default_rng(RANDOM_SEED)
    values = []
    for _ in range(n_boot):
        sampled = cluster[rng.integers(0, len(cluster), size=len(cluster))].sum(axis=0)
        alerts, declines, tp, captured_loss, total_loss = sampled
        values.append((tp / alerts, tp / declines, captured_loss / total_loss))
    values = np.asarray(values, float)
    return {
        "precision_ci_low": np.nanquantile(values[:, 0], 0.025),
        "precision_ci_high": np.nanquantile(values[:, 0], 0.975),
        "recall_ci_low": np.nanquantile(values[:, 1], 0.025),
        "recall_ci_high": np.nanquantile(values[:, 1], 0.975),
        "loss_recall_ci_low": np.nanquantile(values[:, 2], 0.025),
        "loss_recall_ci_high": np.nanquantile(values[:, 2], 0.975),
    }


def main():
    data = pd.read_csv(INPUT)
    development = data.loc[data["origin_week"].isin(DEVELOPMENT_WEEKS)].copy()
    validation = data.loc[data["origin_week"].isin(VALIDATION_WEEKS)].copy()

    grid_rows = []
    for diversity_threshold in DIVERSITY_THRESHOLDS:
        for gap_threshold in GAP_THRESHOLDS:
            signal = apply_rule(development, diversity_threshold, gap_threshold)
            grid_rows.append(
                {
                    "diversity_threshold": diversity_threshold,
                    "gap_threshold": "none" if gap_threshold is None else gap_threshold,
                    **metrics(development, signal),
                }
            )
    grid = pd.DataFrame(grid_rows)
    eligible = grid.loc[
        grid["alerts"].ge(MIN_DEVELOPMENT_ALERTS) & grid["precision"].ge(MIN_DEVELOPMENT_PRECISION)
    ].copy()
    if eligible.empty:
        raise RuntimeError("사전에 정한 최소 경보 수와 precision을 통과한 임계값 조합이 없습니다.")
    selected = eligible.sort_values(
        ["f1", "revenue_loss_recall", "precision", "alerts"], ascending=False
    ).iloc[0]
    selected_diversity = float(selected["diversity_threshold"])
    selected_gap = None if selected["gap_threshold"] == "none" else float(selected["gap_threshold"])

    validation_signal = apply_rule(validation, selected_diversity, selected_gap)
    validation_result = metrics(validation, validation_signal)
    validation_ci = cluster_bootstrap(validation, selected_diversity, selected_gap)
    reference_signal = apply_rule(validation, 0.70, None)
    reference_result = metrics(validation, reference_signal)

    validation_by_week = []
    for week, group in validation.groupby("origin_week"):
        validation_by_week.append(
            {"origin_week": week, **metrics(group, apply_rule(group, selected_diversity, selected_gap))}
        )
    validation_by_week = pd.DataFrame(validation_by_week)

    sensitivity_rows = []
    for decline_pct, cut in [(20, 0.80), (30, 0.70), (40, 0.60)]:
        sensitivity_rows.append(
            {
                "decline_definition": f"{decline_pct}% 이상 감소",
                **metrics(validation, validation_signal, decline_cut=cut),
            }
        )
    sensitivity = pd.DataFrame(sensitivity_rows)

    grid.to_csv(DATA / "spend_decline_threshold_grid_development.csv", index=False, encoding="utf-8-sig")
    validation_by_week.to_csv(DATA / "spend_decline_threshold_validation_by_week.csv", index=False, encoding="utf-8-sig")
    sensitivity.to_csv(DATA / "spend_decline_threshold_outcome_sensitivity.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{**selected.to_dict(), **validation_result, **validation_ci}]).to_csv(
        DATA / "spend_decline_threshold_selected.csv", index=False, encoding="utf-8-sig"
    )

    gap_label = "사용하지 않음" if selected_gap is None else f"{selected_gap:.2f}배 이상"
    generalizes = (
        validation_result["precision_lift"] >= 2
        and validation_result["precision"] >= MIN_DEVELOPMENT_PRECISION
        and (validation_by_week["precision_lift"] > 1).all()
    )
    decision = (
        "개발 구간에서 선택한 규칙이 미사용 검증 구간에서도 고위험 고객을 안정적으로 선별했다."
        if generalizes
        else "선택 규칙의 성능이 미사용 검증 구간에서 충분히 재현되지 않았다."
    )

    top = eligible.sort_values(["f1", "revenue_loss_recall"], ascending=False).head(10)
    lines = [
        "# 지출 감소 탐지 임계값 선택 및 홀드아웃 검증",
        "",
        "## 판정",
        "",
        f"> {decision}",
        "",
        "## 검증 원칙",
        "",
        "- 개발 시점: W50, W58, W66, W74",
        "- 최종 검증 시점: W82, W90",
        "- 개발 구간에서만 임계값을 선택하고 검증 구간에는 선택된 규칙을 한 번만 적용했다.",
        f"- 후보 조건: 개발 경보 {MIN_DEVELOPMENT_ALERTS}건 이상, precision {MIN_DEVELOPMENT_PRECISION:.0%} 이상",
        "- 선택 기준: 조건을 통과한 후보 중 F1 최대, 동률이면 감소 매출 포착률 우선",
        "",
        "## 선택된 규칙",
        "",
        f"- 카테고리 다양성 비율: {selected_diversity:.0%} 미만",
        f"- 방문 간격 조건: {gap_label}",
        f"- 개발 Precision: {selected['precision']:.1%}",
        f"- 개발 Recall: {selected['recall']:.1%}",
        f"- 개발 F1: {selected['f1']:.3f}",
        f"- 개발 감소 매출 포착률: {selected['revenue_loss_recall']:.1%}",
        "",
        "## 미사용 검증 구간 결과",
        "",
        f"- 고객-시점 관측치: {validation_result['observations']:,}",
        f"- 경보: {validation_result['alerts']:,}",
        f"- 실제 30% 이상 감소: {validation_result['declines']:,}",
        f"- Precision: {validation_result['precision']:.1%} (cluster bootstrap 95% CI {validation_ci['precision_ci_low']:.1%}-{validation_ci['precision_ci_high']:.1%})",
        f"- Recall: {validation_result['recall']:.1%} (95% CI {validation_ci['recall_ci_low']:.1%}-{validation_ci['recall_ci_high']:.1%})",
        f"- 기준 감소율: {validation_result['base_rate']:.1%}",
        f"- Precision lift: {validation_result['precision_lift']:.2f}배",
        f"- 감소 매출 포착률: {validation_result['revenue_loss_recall']:.1%} (95% CI {validation_ci['loss_recall_ci_low']:.1%}-{validation_ci['loss_recall_ci_high']:.1%})",
        f"- 경보 1건당 포착된 감소 매출: {validation_result['loss_per_alert']:,.2f}",
        "",
        "## 기존 70% 규칙과 비교",
        "",
        f"- 기존 다양성 70% 규칙 검증 Precision: {reference_result['precision']:.1%}",
        f"- 기존 다양성 70% 규칙 검증 Recall: {reference_result['recall']:.1%}",
        f"- 기존 다양성 70% 규칙 검증 Lift: {reference_result['precision_lift']:.2f}배",
        f"- 기존 다양성 70% 규칙 검증 감소 매출 포착률: {reference_result['revenue_loss_recall']:.1%}",
        "- 85% 규칙은 더 많이 포착하지만 사전 precision 기준을 통과하지 못했다. 따라서 70%는 개입 후보, 85%는 저비용 관찰 후보로 구분하는 것이 안전하다.",
        "",
        "## 검증 시점별 결과",
        "",
        "| 기준 주차 | 경보 | 실제 감소 | Precision | Recall | Lift | 감소 매출 포착률 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in validation_by_week.itertuples(index=False):
        lines.append(
            f"| {row.origin_week} | {row.alerts} | {row.declines} | {row.precision:.1%} | "
            f"{row.recall:.1%} | {row.precision_lift:.2f} | {row.revenue_loss_recall:.1%} |"
        )
    lines += [
        "",
        "## 지출 감소 정의 민감도",
        "",
        "| 정답 정의 | Precision | Recall | Lift | 감소 매출 포착률 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in sensitivity.itertuples(index=False):
        lines.append(
            f"| {row.decline_definition} | {row.precision:.1%} | {row.recall:.1%} | "
            f"{row.precision_lift:.2f} | {row.revenue_loss_recall:.1%} |"
        )
    lines += [
        "",
        "## 개발 구간 상위 후보",
        "",
        "| 다양성 기준 | 방문 간격 | 경보 | Precision | Recall | F1 | 감소 매출 포착률 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in top.itertuples(index=False):
        gap = "없음" if row.gap_threshold == "none" else str(row.gap_threshold)
        lines.append(
            f"| {row.diversity_threshold:.0%} | {gap} | {row.alerts} | {row.precision:.1%} | "
            f"{row.recall:.1%} | {row.f1:.3f} | {row.revenue_loss_recall:.1%} |"
        )
    lines += [
        "",
        "## 해석",
        "",
        "- 임계값 선택은 개발 시점에만 의존했으므로 검증 성능이 실제 일반화 가능성에 대한 핵심 근거다.",
        "- 같은 고객이 두 검증 시점에 포함될 수 있어 신뢰구간은 고객 단위 군집 부트스트랩으로 계산했다.",
        "- 경보 비용과 실제 방어 가능한 매출 비율은 데이터에 없으므로, 경보 1건당 포착 감소 매출은 개입 손익의 상한 참고치다.",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
