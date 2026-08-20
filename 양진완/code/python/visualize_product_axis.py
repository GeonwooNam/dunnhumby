"""Create product-axis charts from the exported DuckDB summary marts."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "product_axis_outputs"

PROMO_ORDER = ["none", "display_only", "mailer_only", "both"]
PROMO_LABELS = {
    "none": "명시적 비프로모션",
    "display_only": "진열만",
    "mailer_only": "전단만",
    "both": "전단+진열",
}
COLORS = {
    "none": "#8A94A6",
    "display_only": "#4C78A8",
    "mailer_only": "#F58518",
    "both": "#54A24B",
}

CATEGORY_LABELS = {
    "BAG SNACKS": "봉지 스낵",
    "BAKED BREAD/BUNS/ROLLS": "빵·번·롤",
    "CANNED JUICES": "캔 주스",
    "CHEESE": "치즈",
    "COLD CEREAL": "시리얼",
    "CRACKERS/MISC BKD FD": "크래커·기타 베이커리",
    "DINNER MXS:DRY": "건조 간편식",
    "ISOTONIC DRINKS": "스포츠음료",
    "MEAT - SHELF STABLE": "상온보관 육류",
    "SALD DRSNG/SNDWCH SPRD": "드레싱·스프레드",
    "SOUP": "수프",
    "VEGETABLES - SHELF STABLE": "상온보관 채소",
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


def annotate_bars(ax: plt.Axes, fmt: str) -> None:
    for patch in ax.patches:
        value = patch.get_height()
        if not np.isfinite(value):
            continue
        ax.annotate(
            fmt.format(value),
            (patch.get_x() + patch.get_width() / 2, value),
            xytext=(0, 4 if value >= 0 else -12),
            textcoords="offset points",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=8,
        )


def plot_promo_2x2() -> None:
    data = pd.read_csv(OUTPUT_DIR / "promo_2x2_summary.csv")
    data = (
        data.loc[data["sample_definition"] == "active_8_visitors_10plus"]
        .set_index("promo_group")
        .loc[PROMO_ORDER]
        .reset_index()
    )

    x = np.arange(len(data))
    labels = [PROMO_LABELS[value] for value in data["promo_group"]]
    colors = [COLORS[value] for value in data["promo_group"]]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

    axes[0].bar(x, data["avg_sales_per_visitor"], color=colors)
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("패널 방문자당 상품 매출")
    axes[0].set_title("프로모션 조합별 방문자당 매출")
    annotate_bars(axes[0], "{:.3f}")

    penetration = 100 * data["avg_buyer_penetration_rate"]
    axes[1].bar(x, penetration, color=colors)
    axes[1].set_xticks(x, labels)
    axes[1].set_ylabel("패널 구매 침투율 (%)")
    axes[1].set_title("프로모션 조합별 방문자 중 구매 비율")
    annotate_bars(axes[1], "{:.2f}%")

    fig.suptitle(
        "전단·특별 진열 2×2 트래픽 보정 비교 — 방문 패널 10명 이상",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "promo_2x2.png", bbox_inches="tight")
    plt.close(fig)


def plot_within_pair() -> None:
    data = pd.read_csv(OUTPUT_DIR / "within_pair_summary.csv")
    order = [
        "display_only_vs_none",
        "mailer_only_vs_none",
        "both_vs_none",
        "both_increment_over_additive",
    ]
    labels = {
        "display_only_vs_none": "진열만 – 비프로모션",
        "mailer_only_vs_none": "전단만 – 비프로모션",
        "both_vs_none": "병행 – 비프로모션",
        "both_increment_over_additive": "병행 – 단순 가산 기대치",
    }
    data = data.set_index("comparison").loc[order].reset_index()
    y = np.arange(len(data))

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].barh(y, data["sales_per_visitor_lift_pct"], color="#4C78A8")
    axes[0].axvline(0, color="#5A5A5A", linewidth=0.8)
    axes[0].set_yticks(y, [labels[value] for value in data["comparison"]])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("동일 상품–점포 내부 평균 상승률 (%)")
    axes[0].set_title("상태별 평균 매출 차이")
    for i, value in enumerate(data["sales_per_visitor_lift_pct"]):
        axes[0].text(value + (1 if value >= 0 else -1), i, f"{value:.1f}%", va="center",
                     ha="left" if value >= 0 else "right", fontsize=8)

    axes[1].barh(y, data["pairs_with_positive_spv_difference_pct"], color="#54A24B")
    axes[1].axvline(50, color="#5A5A5A", linewidth=0.8, linestyle="--")
    axes[1].set_yticks(y, [labels[value] for value in data["comparison"]])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("성과가 더 높았던 상품–점포 비율 (%)")
    axes[1].set_title("상품–점포별 차이의 방향")
    for i, value in enumerate(data["pairs_with_positive_spv_difference_pct"]):
        axes[1].text(value + 0.7, i, f"{value:.1f}%", va="center", fontsize=8)

    fig.suptitle("동일 상품–점포 내부 방문자당 매출 비교", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "within_pair_comparison.png", bbox_inches="tight")
    plt.close(fig)


def plot_position_heatmap() -> None:
    data = pd.read_csv(OUTPUT_DIR / "position_heatmap.csv")
    data["mailer_code"] = data["mailer_code"].astype(str)
    data["display_code"] = data["display_code"].astype(str)
    pivot = data.pivot(index="mailer_code", columns="display_code", values="avg_sales_per_visitor")
    pivot = pivot.reindex(index=[c for c in ["A", "C", "D", "F", "H", "L"] if c in pivot.index])
    columns = [c for c in ["1", "2", "3", "4", "5", "6", "7", "9", "A"] if c in pivot.columns]
    pivot = pivot.reindex(columns=columns)

    values = pivot.to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    image = ax.imshow(values, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(np.arange(len(pivot.columns)), pivot.columns)
    ax.set_yticks(np.arange(len(pivot.index)), pivot.index)
    ax.set_xlabel("특별 진열 코드")
    ax.set_ylabel("전단 위치 코드")
    ax.set_title("전단 위치 × 특별 진열 위치 방문자당 매출")

    finite = values[np.isfinite(values)]
    midpoint = np.nanmedian(finite) if finite.size else 0
    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            value = values[row, col]
            if np.isfinite(value):
                ax.text(
                    col,
                    row,
                    f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white" if value > midpoint else "black",
                )
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("패널 방문자당 상품 매출")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "position_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def plot_department_lift() -> None:
    data = pd.read_csv(OUTPUT_DIR / "category_brand_summary.csv")
    data = data.loc[data["segment_type"] == "department"].copy()
    complete = (
        data.groupby("segment_value")["promo_group"]
        .nunique()
        .loc[lambda x: x == 4]
        .index
    )
    data = data.loc[data["segment_value"].isin(complete)]
    none_size = (
        data.loc[data["promo_group"] == "none", ["segment_value", "pair_weeks"]]
        .nlargest(8, "pair_weeks")["segment_value"]
        .tolist()
    )
    data = data.loc[
        data["segment_value"].isin(none_size)
        & data["promo_group"].isin(["display_only", "mailer_only", "both"])
    ]
    pivot = data.pivot(
        index="segment_value", columns="promo_group", values="sales_per_visitor_lift_pct"
    )
    pivot = pivot.reindex(index=none_size)

    groups = ["display_only", "mailer_only", "both"]
    y = np.arange(len(pivot.index))
    height = 0.23
    fig, ax = plt.subplots(figsize=(10.5, max(4.8, 0.55 * len(pivot.index))))
    for offset, group in enumerate(groups):
        ax.barh(
            y + (offset - 1) * height,
            pivot[group],
            height=height,
            label=PROMO_LABELS[group],
            color=COLORS[group],
        )
    ax.axvline(0, color="#5A5A5A", linewidth=0.8)
    ax.set_yticks(y, pivot.index)
    ax.invert_yaxis()
    ax.set_xlabel("부문 내 명시적 비프로모션 대비 방문자당 매출 차이 (%)")
    ax.set_title("주요 상품 부문별 트래픽 보정 프로모션 차이")
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "promo_lift_by_department.png", bbox_inches="tight")
    plt.close(fig)


def plot_event_trend() -> None:
    data = pd.read_csv(OUTPUT_DIR / "weekly_event_trend.csv")
    event_counts = data.loc[data["relative_week"] == 0, ["event_group", "clean_events"]]
    if len(event_counts) < 3 or (event_counts["clean_events"] < 100).any():
        fig, ax = plt.subplots(figsize=(8, 4.5))
        labels = [PROMO_LABELS.get(value, value) for value in event_counts["event_group"]]
        bars = ax.bar(labels, event_counts["clean_events"], color="#8A94A6")
        ax.set_ylabel("조건을 충족한 이벤트 수")
        ax.set_title("명시적 비프로모션 기준 행사 전후 분석 표본 점검")
        for bar, value in zip(bars, event_counts["clean_events"]):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"{int(value):,}건",
                ha="center",
                va="bottom",
            )
        ax.text(
            0.5,
            0.88,
            "전후 4주가 모두 명시적으로 관측된 이벤트가 부족해 추이 분석 제외",
            transform=ax.transAxes,
            ha="center",
        )
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / "weekly_event_trend.png", bbox_inches="tight")
        plt.close(fig)
        return

    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    for group in ["display_only", "mailer_only", "both"]:
        subset = data.loc[data["event_group"] == group].sort_values("relative_week")
        if subset.empty:
            continue
        ax.plot(
            subset["relative_week"],
            subset["pre_period_sales_per_visitor_index"],
            marker="o",
            linewidth=2,
            label=PROMO_LABELS[group],
            color=COLORS[group],
        )
    ax.axhline(100, color="#5A5A5A", linewidth=0.8, linestyle="--")
    ax.axvline(0, color="#5A5A5A", linewidth=0.8)
    ax.set_xticks(range(-4, 5))
    ax.set_xlabel("프로모션 주 기준 상대 주차")
    ax.set_ylabel("행사 전 4주 평균 = 100")
    ax.set_title("고립된 1주 프로모션 전후 방문자당 매출 추이")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "weekly_event_trend.png", bbox_inches="tight")
    plt.close(fig)


def plot_mailer_product_week() -> None:
    data = pd.read_csv(OUTPUT_DIR / "mailer_within_product_summary.csv")
    order = ["all_product_weeks", "no_display_any_store"]
    labels = {
        "all_product_weeks": "전체 상품–주",
        "no_display_any_store": "진열 없는 상품–주",
    }
    data = data.set_index("sample_definition").loc[order].reset_index()
    x = np.arange(len(data))

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    axes[0].bar(x, data["sales_per_visitor_lift_pct"], color="#F58518")
    axes[0].set_xticks(x, [labels[value] for value in data["sample_definition"]])
    axes[0].set_ylabel("비전단 대비 차이 (%)")
    axes[0].set_title("방문자당 매출")
    axes[0].axhline(0, color="#5A5A5A", linewidth=0.8)
    annotate_bars(axes[0], "{:.1f}%")

    axes[1].bar(
        x, data["products_with_positive_spv_difference_pct"], color="#4C78A8"
    )
    axes[1].set_xticks(x, [labels[value] for value in data["sample_definition"]])
    axes[1].set_ylabel("상품 비율 (%)")
    axes[1].set_title("전단 주 방문자당 매출이 더 높은 상품")
    axes[1].axhline(50, color="#5A5A5A", linewidth=0.8, linestyle="--")
    annotate_bars(axes[1], "{:.1f}%")

    fig.suptitle("동일 상품 내부 전단 주와 비전단 주 비교", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "mailer_product_week.png", bbox_inches="tight")
    plt.close(fig)


def plot_traffic_strata() -> None:
    data = pd.read_csv(OUTPUT_DIR / "promo_traffic_strata.csv")
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    for group in PROMO_ORDER:
        subset = data.loc[data["promo_group"] == group].sort_values("traffic_quartile")
        ax.plot(
            subset["traffic_quartile"],
            100 * subset["avg_buyer_penetration_rate"],
            marker="o",
            linewidth=2,
            color=COLORS[group],
            label=PROMO_LABELS[group],
        )
    ax.set_xticks([1, 2, 3, 4], ["낮음", "중하", "중상", "높음"])
    ax.set_xlabel("점포–주 패널 방문자 수 구간")
    ax.set_ylabel("패널 구매 침투율 (%)")
    ax.set_title("점포 트래픽 구간별 프로모션 그룹 비교")
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "traffic_strata_comparison.png", bbox_inches="tight")
    plt.close(fig)


def plot_category_promotion_matrix() -> None:
    data = pd.read_csv(OUTPUT_DIR / "category_promotion_matrix.csv")
    data["category_label"] = data["COMMODITY_DESC"].map(CATEGORY_LABELS).fillna(
        data["COMMODITY_DESC"]
    )

    columns = [
        ("display_response", "display_stable_3week", "특별 진열"),
        ("mailer_response", "mailer_stable_3week", "전단"),
        ("both_response", "both_stable_3week", "전단+진열"),
        ("synergy_response", "synergy_stable_3week", "병행 추가분\n(vs 단순 가산)"),
    ]
    response_value = {
        "mixed_or_nonpositive": 0,
        "sales_only": 1,
        "penetration_only": 2,
        "sales_and_penetration": 3,
        "insufficient_support": 4,
    }
    response_text = {
        "mixed_or_nonpositive": "혼합/비양수",
        "sales_only": "매출",
        "penetration_only": "침투",
        "sales_and_penetration": "매출+침투",
        "insufficient_support": "표본 부족",
    }

    matrix = np.zeros((len(data), len(columns)), dtype=int)
    annotations: list[list[str]] = []
    for row_idx, row in data.iterrows():
        row_text: list[str] = []
        for col_idx, (response_col, stable_col, _) in enumerate(columns):
            response = row.get(response_col, "insufficient_support")
            if pd.isna(response):
                response = "insufficient_support"
            matrix[row_idx, col_idx] = response_value[response]
            suffix = ""
            if response not in ("mixed_or_nonpositive", "insufficient_support"):
                suffix = " ★" if row.get(stable_col, 0) == 1 else " †"
            row_text.append(response_text[response] + suffix)
        annotations.append(row_text)

    cmap = ListedColormap(["#E2E5E9", "#F4A261", "#4C78A8", "#59A14F", "#FFFFFF"])
    fig, ax = plt.subplots(figsize=(11.2, 7.2))
    ax.imshow(matrix, cmap=cmap, vmin=-0.5, vmax=4.5, aspect="auto")
    ax.set_xticks(np.arange(len(columns)), [item[2] for item in columns])
    ax.set_yticks(np.arange(len(data)), data["category_label"])
    ax.tick_params(axis="x", bottom=False, top=True, labelbottom=False, labeltop=True)

    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            value = matrix[row_idx, col_idx]
            ax.text(
                col_idx,
                row_idx,
                annotations[row_idx][col_idx],
                ha="center",
                va="center",
                fontsize=8.2,
                color="white" if value in (2, 3) else "#222222",
            )

    ax.set_xticks(np.arange(-0.5, len(columns), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(data), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.axvline(2.5, color="#4A4A4A", linewidth=1.4)
    ax.set_title(
        "상품군별 유망 프로모션 탐색 — 동일 상품·점포 내부 비교",
        pad=36,
    )

    legend_items = [
        Patch(facecolor="#59A14F", label="매출·침투 모두 양의 방향"),
        Patch(facecolor="#F4A261", label="매출만 양의 방향"),
        Patch(facecolor="#4C78A8", label="침투만 양의 방향"),
        Patch(facecolor="#E2E5E9", label="혼합 또는 비양수"),
    ]
    ax.legend(
        handles=legend_items,
        frameon=False,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.055),
    )
    fig.text(
        0.5,
        0.005,
        "★ 3주 기준에서도 후보 · † 2주 기준에서만 후보/3주 표본 부족 · 병행 추가분은 프로모션 선택이 아닌 시너지 진단",
        ha="center",
        fontsize=8.5,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(OUTPUT_DIR / "category_promotion_signal_matrix.png", bbox_inches="tight")
    plt.close(fig)


def plot_category_promotion_sensitivity() -> None:
    response = pd.read_csv(
        OUTPUT_DIR / "category_promotion_response_sensitivity.csv"
    )
    matrix = pd.read_csv(OUTPUT_DIR / "category_promotion_matrix.csv")
    categories = set(matrix["COMMODITY_DESC"])
    direct = response.loc[
        response["COMMODITY_DESC"].isin(categories)
        & response["comparison"].isin(
            ["display_only_vs_none", "mailer_only_vs_none", "both_vs_none"]
        )
    ]
    summary = (
        direct.groupby("min_weeks")
        .agg(
            support_cells=("has_adequate_support", "sum"),
            promising_cells=("is_promising", "sum"),
        )
        .reindex([1, 2, 3])
        .fillna(0)
    )

    x = np.arange(len(summary))
    width = 0.34
    fig, ax = plt.subplots(figsize=(8.3, 4.6))
    bars_support = ax.bar(
        x - width / 2,
        summary["support_cells"],
        width,
        color="#8A94A6",
        label="분석 가능 셀",
    )
    bars_candidate = ax.bar(
        x + width / 2,
        summary["promising_cells"],
        width,
        color="#59A14F",
        label="유망 후보 셀",
    )
    ax.set_xticks(x, [f"각 상태 {week}주 이상" for week in summary.index])
    ax.set_ylabel("상품군 × 프로모션 셀 수")
    ax.set_ylim(0, 39)
    ax.set_title("관측 주 기준에 따른 상품군 후보 민감도")
    ax.legend(frameon=False)
    for bars in (bars_support, bars_candidate):
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.7,
                f"{int(bar.get_height())}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "category_promotion_support_sensitivity.png",
        bbox_inches="tight",
    )
    plt.close(fig)


def main() -> None:
    configure_style()
    plot_promo_2x2()
    plot_within_pair()
    plot_position_heatmap()
    plot_department_lift()
    plot_event_trend()
    plot_mailer_product_week()
    plot_traffic_strata()
    plot_category_promotion_matrix()
    plot_category_promotion_sensitivity()
    print(f"Charts written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
