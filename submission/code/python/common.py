"""공통 로더 · Phase 0 전처리 정책 · 시각화 팔레트.

노트북에서도 `from common import *` 로 그대로 쓸 수 있게 구성.
Phase 0 정책(phase0_agreements.md)이 확정되면 이 파일의 기본값만 고치면 됨.
"""
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)

# --- Phase 0 정책 ---------------------------------------------------------
# #4 비(非)장보기 거래: 주유·기타결제는 '장보기'가 아니므로 카테고리/바스켓 분석에서 제외
NON_SHOPPING_DEPTS = ("KIOSK-GAS", "MISC SALES TRAN")

# #2 실구매가: SALES_VALUE = 매장 매출(할인 반영 후). 분석 전반의 '매출' 표준 컬럼.
SALES_COL = "SALES_VALUE"

# #5 분석 대상 기간 (Phase 1에서 확정)
#   W1~16  = 가구 패널 편입 램프업 구간 (W18까지 99.4% 가구가 최초 등장)
#   W102   = 6일만 존재하는 절단 주차 (W1도 5일)
#   → 안정 구간 W17~W101 (85주). 30개 캠페인 전부 이 구간 안에 들어옴.
ANALYSIS_WEEKS = (17, 101)


def load_products() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "product.csv")


def load_transactions(
    exclude_non_shopping: bool = True,
    positive_sales_only: bool = False,
    analysis_window: bool = False,
    products: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """거래 데이터 로드 + Phase 0 정책 적용.

    exclude_non_shopping: KIOSK-GAS / MISC SALES TRAN 부문 제외 (정책 #4)
    positive_sales_only:  SALES_VALUE <= 0 (반품/증정) 제외 (정책 #1)
    analysis_window:      W17~W101 로 제한 (정책 #5) — Phase 2 이후 분석은 True 권장
    """
    tx = pd.read_csv(DATA_DIR / "transaction_data.csv")
    # OneDrive 동기화 중에는 read_csv가 헤더만 읽어 빈 프레임이 돌아올 수 있다.
    # 조용히 통과시키면 이후 모든 집계가 0이 되므로 즉시 중단.
    if len(tx) < 2_000_000:
        raise RuntimeError(
            f"transaction_data.csv 를 {len(tx):,}행만 읽었습니다 (기대 2,595,732행). "
            "OneDrive 동기화가 끝난 뒤 다시 실행하세요.")
    if exclude_non_shopping:
        if products is None:
            products = load_products()
        dept = products.set_index("PRODUCT_ID")["DEPARTMENT"]
        tx["DEPARTMENT"] = tx["PRODUCT_ID"].map(dept)
        tx = tx[~tx["DEPARTMENT"].isin(NON_SHOPPING_DEPTS)]
    if positive_sales_only:
        tx = tx[tx[SALES_COL] > 0]
    if analysis_window:
        lo, hi = ANALYSIS_WEEKS
        tx = tx[tx["WEEK_NO"].between(lo, hi)]
    return tx.reset_index(drop=True)


# --- 팔레트 (dataviz 검증 팔레트, light surface) --------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
# 카테고리 슬롯 — 고정 순서, 순환 금지
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def setup_style() -> None:
    """한글 폰트 + recessive 그리드/축 스타일."""
    for font in ("Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"):
        if any(f.name == font for f in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = font
            break
    plt.rcParams.update({
        "axes.unicode_minus": False,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.labelsize": 9.5,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "lines.linewidth": 2,
        "figure.dpi": 130,
    })
    for side in ("top", "right"):
        plt.rcParams[f"axes.spines.{side}"] = False
