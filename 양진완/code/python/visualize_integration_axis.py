"""Create product-response and customer-product integration charts."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "integration_axis_outputs"

COMPARISONS = [
    "display_only_vs_none",
    "mailer_only_vs_none",
    "both_vs_none",
]
LABELS = {
    "display_only_vs_none": "특별 진열만",
    "mailer_only_vs_none": "전단만",
    "both_vs_none": "전단+진열",
    "both_vs_additive": "병행 시너지",
}
COLORS = {
    "display_only_vs_none": "#4C78A8",
    "mailer_only_vs_none": "#F58518",
    "both_vs_none": "#54A24B",
    "both_vs_additive": "#B279A2",
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
        }
    )


def plot_product_response_consistency() -> None:
    data = pd.read_csv(OUTPUT_DIR / "product_response_profile.csv")
    data = data.loc[
        data["comparison"].isin(COMPARISONS)
        & (data["support_tier"] == "multi_store_repeated")
    ].copy()

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), sharex=True, sharey=True)
    for ax, comparison in zip(axes, COMPARISONS):
        subset = data.loc[data["comparison"] == comparison]
        non_candidate = subset.loc[subset["is_repeated_any_positive"] == 0]
        candidate = subset.loc[subset["is_repeated_any_positive"] == 1]
        sizes_non = 18 + 5 * non_candidate["eligible_stores"].clip(upper=12)
        sizes_yes = 22 + 5 * candidate["eligible_stores"].clip(upper=12)
        ax.scatter(
            non_candidate["positive_spv_store_pct"],
            non_candidate["positive_bpr_store_pct"],
            s=sizes_non,
            color="#A7AFBC",
            alpha=0.55,
            label="혼합·비반응",
        )
        ax.scatter(
            candidate["positive_spv_store_pct"],
            candidate["positive_bpr_store_pct"],
            s=sizes_yes,
            color=COLORS[comparison],
            alpha=0.8,
            edgecolor="white",
            linewidth=0.4,
            label="반복 긍정 후보",
        )
        ax.axvline(60, color="#5A5A5A", linewidth=0.8, linestyle="--")
        ax.axhline(60, color="#5A5A5A", linewidth=0.8, linestyle="--")
        ax.set_xlim(-2, 102)
        ax.set_ylim(-2, 102)
        ax.set_title(
            f"{LABELS[comparison]}\n후보 {len(candidate)} / 분석상품 {len(subset)}"
        )
        ax.set_xlabel("방문자당 매출 양수 점포 비율 (%)")
    axes[0].set_ylabel("구매 침투율 양수 점포 비율 (%)")
    axes[-1].legend(frameon=False, loc="lower right", fontsize=8)
    fig.suptitle(
        "상품별 프로모션 반응의 점포 간 반복성 — 상태별 3주·3개 점포 이상",
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "01_product_response_consistency.png", bbox_inches="tight")
    plt.close(fig)


def plot_candidate_commodity_heatmap() -> None:
    data = pd.read_csv(OUTPUT_DIR / "product_commodity_response.csv")
    data = data.loc[data["comparison"].isin(COMPARISONS)].copy()
    rate_all = data.pivot(
        index="COMMODITY_DESC",
        columns="comparison",
        values="repeated_any_positive_product_pct",
    ).reindex(columns=COMPARISONS)
    numerator_all = data.pivot(
        index="COMMODITY_DESC",
        columns="comparison",
        values="repeated_any_positive_products",
    ).reindex(columns=COMPARISONS)
    denominator_all = data.pivot(
        index="COMMODITY_DESC",
        columns="comparison",
        values="multistore_profiled_products",
    ).reindex(columns=COMPARISONS)
    eligible = denominator_all.dropna().loc[
        denominator_all.dropna().min(axis=1) >= 3
    ]
    commodities = (
        numerator_all.loc[eligible.index]
        .sum(axis=1)
        .sort_values(ascending=False)
        .head(12)
        .index.tolist()
    )
    rate = rate_all.reindex(index=commodities, columns=COMPARISONS)
    numerator = numerator_all.reindex(index=commodities, columns=COMPARISONS)
    denominator = denominator_all.reindex(index=commodities, columns=COMPARISONS)

    values = rate.to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(8.5, 6.8))
    image = ax.imshow(values, cmap="YlGnBu", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(
        np.arange(len(COMPARISONS)), [LABELS[value] for value in COMPARISONS]
    )
    ax.set_yticks(np.arange(len(commodities)), commodities)
    ax.set_title("상품유형별 반복 긍정 후보 비율")
    for row in range(len(commodities)):
        for col in range(len(COMPARISONS)):
            value = values[row, col]
            if not np.isfinite(value):
                continue
            n = int(numerator.iloc[row, col])
            d = int(denominator.iloc[row, col])
            ax.text(
                col,
                row,
                f"{value:.0f}%\n({n}/{d})",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if value >= 60 else "black",
            )
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("반복 긍정 후보 상품 비율 (%)")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "02_candidate_commodity_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def plot_customer_product_fit_coverage() -> None:
    data = pd.read_csv(OUTPUT_DIR / "customer_product_fit_summary.csv")
    data = data.set_index("comparison").loc[COMPARISONS].reset_index()
    series = [
        ("avg_profiled_weight", "상품 프로필 있음", "#A7AFBC"),
        ("avg_multistore_profiled_weight", "3개 점포 이상", "#4C78A8"),
        ("avg_any_positive_weight", "반복 긍정 후보", "#54A24B"),
        ("avg_home_store_profiled_weight", "홈스토어 직접 비교", "#B279A2"),
    ]
    x = np.arange(len(data))
    width = 0.19
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    for idx, (column, label, color) in enumerate(series):
        values = 100 * data[column]
        bars = ax.bar(
            x + (idx - 1.5) * width,
            values,
            width=width,
            label=label,
            color=color,
        )
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.5,
                f"{value:.1f}%",
                ha="center",
                va="bottom",
                fontsize=7,
            )
    ax.set_xticks(x, [LABELS[value] for value in data["comparison"]])
    ax.set_ylabel("고객 선호가중치 중 평균 비중 (%)")
    ax.set_title("상품 반응 프로필을 고객 선호상품에 연결했을 때의 커버리지")
    ax.legend(frameon=False, ncol=2)
    ax.set_ylim(0, max(100 * data["avg_profiled_weight"]) * 1.25)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "03_customer_product_fit_coverage.png", bbox_inches="tight")
    plt.close(fig)


def plot_customer_fit_sensitivity() -> None:
    data = pd.read_csv(OUTPUT_DIR / "customer_fit_support_sensitivity.csv")
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    for comparison in COMPARISONS:
        subset = data.loc[data["comparison"] == comparison].sort_values("min_weeks")
        ax.plot(
            subset["min_weeks"],
            100 * subset["avg_any_positive_weight"],
            marker="o",
            linewidth=2,
            color=COLORS[comparison],
            label=LABELS[comparison],
        )
    ax.axvline(3, color="#5A5A5A", linewidth=0.8, linestyle="--")
    ax.text(3.05, ax.get_ylim()[1] * 0.92, "주 기준", fontsize=8)
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.set_xlabel("각 상태의 최소 관측 주 수")
    ax.set_ylabel("반복 긍정 후보가 차지한 평균 선호가중치 (%)")
    ax.set_title("관측 지지도를 강화할수록 고객–상품 연결 커버리지가 급감")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "04_customer_fit_sensitivity.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    configure_style()
    plot_product_response_consistency()
    plot_candidate_commodity_heatmap()
    plot_customer_product_fit_coverage()
    plot_customer_fit_sensitivity()
    print(f"Integration charts written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
