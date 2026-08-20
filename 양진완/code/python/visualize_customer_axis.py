"""Create customer-axis charts from exported DuckDB summary marts."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "customer_axis_outputs"

COLORS = {
    "any_feature": "#4C78A8",
    "feature_mailer": "#F58518",
    "display": "#54A24B",
    "both": "#B279A2",
    "neutral": "#8A94A6",
    "negative": "#E45756",
}

EXPOSURE_LABELS = {
    "any_feature": "전단 또는 진열",
    "feature_mailer": "순수 전단",
    "display": "특별 진열",
    "both": "전단+진열",
    "coupon_mailer": "전단 쿠폰",
    "free_mailer": "무료상품 오퍼",
    "any_mailer": "모든 전단 코드",
}

GAP_LABELS = {
    "01_1_week": "1주",
    "02_2_weeks": "2주",
    "03_3_4_weeks": "3–4주",
    "04_5plus_weeks": "5주 이상",
}


def configure_style() -> None:
    available = {item.name for item in font_manager.fontManager.ttflist}
    if "Malgun Gothic" in available:
        plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams.update(
        {
            "axes.unicode_minus": False,
            "figure.dpi": 130,
            "savefig.dpi": 180,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.grid": False,
        }
    )


def annotate_vertical_bars(ax: plt.Axes, fmt: str = "{:.2f}") -> None:
    for bar in ax.patches:
        value = bar.get_height()
        if not np.isfinite(value):
            continue
        offset = 4 if value >= 0 else -13
        ax.annotate(
            fmt.format(value),
            (bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, offset),
            textcoords="offset points",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=8,
        )


def plot_sample_diagnostics() -> None:
    flow = pd.read_csv(OUTPUT_DIR / "sample_flow.csv")
    flow = flow.loc[flow["step_no"] <= 7].sort_values("step_no")
    labels = {
        "all_panel_households": "전체 패널",
        "baseline_purchase_observed": "기준기간 구매 관측",
        "baseline_baskets_5plus": "장바구니 5회 이상",
        "candidate_home_store_in_causal": "홈스토어 로그 연결",
        "candidate_baseline_weeks_8plus": "구매 관측 8주 이상",
        "primary_before_preference": "홈스토어 비중 50% 이상",
        "primary_final": "적격 선호상품 5개 이상",
    }
    weeks = pd.read_csv(OUTPUT_DIR / "baseline_weeks.csv")
    week_labels = {
        "01_1_4": "1–4주",
        "02_5_7": "5–7주",
        "03_8_13": "8–13주",
        "04_14_26": "14–26주",
    }

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    y = np.arange(len(flow))
    axes[0].barh(y, flow["households"], color=COLORS["any_feature"])
    axes[0].set_yticks(y, [labels[value] for value in flow["step"]])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("고객 수")
    axes[0].set_title("주 분석 표본 구성")
    for i, value in enumerate(flow["households"]):
        axes[0].text(value + 25, i, f"{value:,}명", va="center", fontsize=8)
    axes[0].set_xlim(0, flow["households"].max() * 1.18)

    bars = axes[1].bar(
        [week_labels[value] for value in weeks["baseline_week_band"]],
        weeks["households"],
        color=COLORS["neutral"],
    )
    axes[1].set_ylabel("후보 고객 수")
    axes[1].set_xlabel("1–26주 중 구매가 관측된 주차 수")
    axes[1].set_title("기준 특성의 관측 길이")
    for bar, value in zip(bars, weeks["households"]):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:,}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    fig.suptitle("고객축 표본 진단", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "01_sample_diagnostics.png", bbox_inches="tight")
    plt.close(fig)


def plot_exposure_diagnostics() -> None:
    hist = pd.read_csv(OUTPUT_DIR / "exposure_histogram.csv")
    by_type = pd.read_csv(OUTPUT_DIR / "exposure_by_type.csv")
    types = ["any_feature", "feature_mailer", "display", "both"]
    by_type = by_type.set_index("exposure_type").loc[types].reset_index()
    hist["share"] = 100 * hist["household_weeks"] / hist["household_weeks"].sum()

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].bar(
        hist["exposure_bin_start"],
        hist["share"],
        width=0.045,
        align="edge",
        color=COLORS["any_feature"],
    )
    axes[0].set_xlabel("선호상품 중 전단 또는 진열 노출 가중치")
    axes[0].set_ylabel("고객–주 비율 (%)")
    axes[0].set_title("고정 분모 노출지표 분포")

    x = np.arange(len(by_type))
    means = 100 * by_type["mean_exposure"]
    zeros = 100 * by_type["zero_exposure_rate"]
    width = 0.36
    axes[1].bar(x - width / 2, means, width, label="평균 노출 가중치", color="#4C78A8")
    axes[1].bar(x + width / 2, zeros, width, label="무노출 고객–주", color="#8A94A6")
    axes[1].set_xticks(x, [EXPOSURE_LABELS[value] for value in by_type["exposure_type"]])
    axes[1].set_ylabel("비율 (%)")
    axes[1].set_title("프로모션 구성별 관측 가능성")
    axes[1].legend(frameon=False)
    fig.suptitle("선호상품 프로모션 노출 진단", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "02_exposure_diagnostics.png", bbox_inches="tight")
    plt.close(fig)


def plot_within_customer_response() -> None:
    data = pd.read_csv(OUTPUT_DIR / "within_customer_high_low.csv")
    types = ["any_feature", "feature_mailer", "display", "both"]
    data = data.set_index("exposure_type").loc[types].reset_index()
    labels = [EXPOSURE_LABELS[value] for value in data["exposure_type"]]
    x = np.arange(len(data))
    width = 0.36

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.1))
    axes[0].bar(
        x - width / 2,
        data["mean_visit_difference_pct_point"],
        width,
        yerr=data["visit_difference_standard_error_pct_point"],
        capsize=4,
        label="전 점포 방문",
        color="#8A94A6",
    )
    axes[0].bar(
        x + width / 2,
        data["mean_home_store_visit_difference_pct_point"],
        width,
        yerr=data["home_store_visit_difference_standard_error_pct_point"],
        capsize=4,
        label="홈스토어 방문",
        color="#4C78A8",
    )
    axes[0].set_title("높은 주 – 낮은 주")
    axes[0].set_ylabel("방문율 차이 (%p, 오차막대=단순 SE)")

    axes[1].bar(
        x - width / 2,
        data["net_calendar_visit_difference_pct_point"],
        width,
        yerr=data["net_calendar_visit_difference_standard_error_pct_point"],
        capsize=4,
        label="전 점포 방문",
        color="#8A94A6",
    )
    axes[1].bar(
        x + width / 2,
        data["net_calendar_home_store_visit_difference_pct_point"],
        width,
        yerr=data[
            "net_calendar_home_store_visit_difference_standard_error_pct_point"
        ],
        capsize=4,
        label="홈스토어 방문",
        color="#54A24B",
    )
    axes[1].set_title("달력주 placebo 차감 후")
    axes[1].set_ylabel("순 방문율 차이 (%p, 오차막대=단순 SE)")
    for ax in axes:
        ax.axhline(0, color="#5A5A5A", linewidth=0.8)
        ax.set_xticks(x, labels)
        ax.legend(frameon=False)
    fig.suptitle("동일 고객 안의 프로모션 노출 비교", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "03_within_customer_response.png", bbox_inches="tight")
    plt.close(fig)


def plot_visit_gap_response() -> None:
    raw = pd.read_csv(OUTPUT_DIR / "visit_gap_exposure_response.csv")
    raw = raw.loc[
        (raw["campaign_segment"] == "all_weeks")
        & raw["visit_gap_band"].isin(GAP_LABELS)
    ].copy()
    pivot = raw.pivot(
        index="visit_gap_band", columns="exposure_quartile", values="visit_rate"
    ).reindex(GAP_LABELS)
    values = 100 * pivot.to_numpy(dtype=float)
    within = pd.read_csv(OUTPUT_DIR / "visit_gap_within_response.csv")
    within = within.set_index("visit_gap_band").reindex(GAP_LABELS).reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.0))
    image = axes[0].imshow(values, cmap="YlGnBu", aspect="auto")
    axes[0].set_xticks(range(4), ["낮음", "중하", "중상", "높음"])
    axes[0].set_yticks(range(len(pivot)), [GAP_LABELS[value] for value in pivot.index])
    axes[0].set_xlabel("노출 사분위")
    axes[0].set_ylabel("직전 방문 이후 공백")
    axes[0].set_title("당주 방문율 (%)")
    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            axes[0].text(col, row, f"{values[row, col]:.1f}", ha="center", va="center", fontsize=8)
    cbar = fig.colorbar(image, ax=axes[0])
    cbar.set_label("방문율 (%)")

    bars = axes[1].bar(
        [GAP_LABELS[value] for value in within["visit_gap_band"]],
        within["mean_visit_difference_pct_point"],
        yerr=within["visit_difference_standard_error_pct_point"],
        capsize=4,
        color="#8A94A6",
    )
    axes[1].axhline(0, color="#5A5A5A", linewidth=0.8)
    axes[1].set_ylabel("방문율 차이 (%p, 오차막대=단순 SE)")
    axes[1].set_xlabel("직전 방문 이후 공백")
    axes[1].set_title("같은 고객·공백 구간 내부 차이")
    for bar, value in zip(bars, within["mean_visit_difference_pct_point"]):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:+.2f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=8,
        )
    fig.suptitle("방문 공백에 따른 노출–재방문 관계", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "04_visit_gap_response.png", bbox_inches="tight")
    plt.close(fig)


def plot_department_response() -> None:
    data = pd.read_csv(OUTPUT_DIR / "department_within_response.csv")
    order = ["preferred_top3", "other_purchased"]
    labels = {"preferred_top3": "주력 상위 3개", "other_purchased": "그 밖의 과거 구매 부문"}
    data = data.set_index("department_relation").loc[order].reset_index()
    x = np.arange(len(data))

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.7))
    axes[0].bar(
        x,
        data["mean_purchase_difference_pct_point"],
        yerr=data["purchase_difference_standard_error_pct_point"],
        capsize=4,
        color="#54A24B",
    )
    axes[0].set_xticks(x, [labels[value] for value in data["department_relation"]])
    axes[0].set_ylabel("구매율 차이 (%p, 오차막대=단순 SE)")
    axes[0].set_title("부문 구매 여부")
    axes[0].axhline(0, color="#5A5A5A", linewidth=0.8)
    annotate_vertical_bars(axes[0], "{:+.2f}")

    axes[1].bar(
        x,
        data["mean_sales_value_difference"],
        yerr=data["sales_difference_standard_error"],
        capsize=4,
        color="#4C78A8",
    )
    axes[1].set_xticks(x, [labels[value] for value in data["department_relation"]])
    axes[1].set_ylabel("수취액 차이 (오차막대=단순 SE)")
    axes[1].set_title("부문 소매업체 수취액")
    axes[1].axhline(0, color="#5A5A5A", linewidth=0.8)
    annotate_vertical_bars(axes[1], "{:+.2f}")
    fig.suptitle("같은 고객–부문 안의 프로모션 노출 비교", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "05_department_response.png", bbox_inches="tight")
    plt.close(fig)


def plot_campaign_sensitivity() -> None:
    data = pd.read_csv(OUTPUT_DIR / "campaign_sensitivity.csv")
    order = [
        "all_primary_weeks",
        "campaign_inactive_weeks",
        "campaign_active_weeks",
        "never_campaign_recipient",
    ]
    labels = {
        "all_primary_weeks": "전체 주",
        "campaign_inactive_weeks": "캠페인 비활성 주",
        "campaign_active_weeks": "캠페인 활성 주",
        "never_campaign_recipient": "캠페인 비수령 고객",
    }
    data = data.set_index("campaign_segment").loc[order].reset_index()
    x = np.arange(len(data))

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    axes[0].bar(
        x,
        data["mean_visit_difference_pct_point"],
        yerr=data["visit_difference_standard_error_pct_point"],
        capsize=4,
        color="#8A94A6",
    )
    axes[0].set_xticks(x, [labels[value] for value in data["campaign_segment"]], rotation=15, ha="right")
    axes[0].set_ylabel("방문율 차이 (%p, 오차막대=단순 SE)")
    axes[0].set_title("전 점포 방문")
    axes[0].axhline(0, color="#5A5A5A", linewidth=0.8)
    annotate_vertical_bars(axes[0], "{:+.2f}")

    axes[1].bar(
        x,
        data["mean_home_store_visit_difference_pct_point"],
        yerr=data["home_store_visit_difference_standard_error_pct_point"],
        capsize=4,
        color="#4C78A8",
    )
    axes[1].set_xticks(x, [labels[value] for value in data["campaign_segment"]], rotation=15, ha="right")
    axes[1].set_ylabel("방문율 차이 (%p, 오차막대=단순 SE)")
    axes[1].set_title("홈스토어 방문")
    axes[1].axhline(0, color="#5A5A5A", linewidth=0.8)
    annotate_vertical_bars(axes[1], "{:+.2f}")
    fig.suptitle("캠페인 중첩에 따른 결과 민감도", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "06_campaign_sensitivity.png", bbox_inches="tight")
    plt.close(fig)


def plot_sample_sensitivity() -> None:
    data = pd.read_csv(OUTPUT_DIR / "sample_sensitivity.csv")
    order = [
        "baseline_history_eligible5",
        "all_weeks_history_eligible5",
        "no_history_filter_eligible5",
        "home70_top20",
        "primary_top10",
    ]
    labels = {
        "baseline_history_eligible5": "기준기간 등재",
        "all_weeks_history_eligible5": "전체기간 등재",
        "no_history_filter_eligible5": "등재 필터 없음",
        "home70_top20": "홈스토어 70%+",
        "primary_top10": "상위 10개 가중치",
    }
    data = data.set_index("sample_definition").loc[order].reset_index()
    x = np.arange(len(data))

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    axes[0].bar(
        x,
        data["mean_visit_difference_pct_point"],
        yerr=data["visit_difference_standard_error_pct_point"],
        capsize=4,
        color="#8A94A6",
    )
    axes[0].set_xticks(x, [labels[value] for value in data["sample_definition"]], rotation=15, ha="right")
    axes[0].set_ylabel("방문율 차이 (%p, 오차막대=단순 SE)")
    axes[0].set_title("전 점포 방문")
    axes[0].axhline(0, color="#5A5A5A", linewidth=0.8)
    annotate_vertical_bars(axes[0], "{:+.2f}")

    axes[1].bar(
        x,
        data["mean_home_store_visit_difference_pct_point"],
        yerr=data["home_store_visit_difference_standard_error_pct_point"],
        capsize=4,
        color="#4C78A8",
    )
    axes[1].set_xticks(x, [labels[value] for value in data["sample_definition"]], rotation=15, ha="right")
    axes[1].set_ylabel("방문율 차이 (%p, 오차막대=단순 SE)")
    axes[1].set_title("홈스토어 방문")
    axes[1].axhline(0, color="#5A5A5A", linewidth=0.8)
    annotate_vertical_bars(axes[1], "{:+.2f}")
    fig.suptitle("표본·선호상품 정의에 따른 민감도", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "07_sample_sensitivity.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    configure_style()
    plot_sample_diagnostics()
    plot_exposure_diagnostics()
    plot_within_customer_response()
    plot_visit_gap_response()
    plot_department_response()
    plot_campaign_sensitivity()
    plot_sample_sensitivity()
    print(f"Charts written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
