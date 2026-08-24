from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
CAUSAL_PATH = ROOT / "causal_data.csv"
COUNT_OUTPUT = DATA / "promotion_group_counts.csv"
DIAGNOSTIC_OUTPUT = DATA / "promotion_synergy_identifiability.csv"

counts = {"무프로모션": 0, "진열만": 0, "전단만": 0, "전단+진열": 0}
dtype = {"display": "string", "mailer": "string"}
for chunk in pd.read_csv(CAUSAL_PATH, usecols=["display", "mailer"], chunksize=1_000_000, dtype=dtype):
    display = chunk["display"].fillna("0").ne("0")
    mailer = chunk["mailer"].fillna("0").ne("0")
    counts["무프로모션"] += int((~display & ~mailer).sum())
    counts["진열만"] += int((display & ~mailer).sum())
    counts["전단만"] += int((~display & mailer).sum())
    counts["전단+진열"] += int((display & mailer).sum())

group_counts = pd.DataFrame(
    [{"promotion_group": group, "rows": rows, "share": rows / sum(counts.values())} for group, rows in counts.items()]
)
group_counts.to_csv(COUNT_OUTPUT, index=False, encoding="utf-8-sig")

diagnostic = pd.DataFrame(
    [
        {
            "question": "결합 효과가 전단 효과와 진열 효과의 합보다 큰가?",
            "required_estimand": "결합 - 진열만 - 전단만 + 무프로모션",
            "required_baseline": "동일하거나 비교 가능한 상품·매장·주차의 무프로모션 성과",
            "available_no_promotion_rows": counts["무프로모션"],
            "identifiable_with_current_data": False,
            "reason": "causal_data에 display=0이면서 mailer=0인 무프로모션 행이 0개이므로 기본 판매수준을 분리할 수 없음",
            "what_is_currently_supported": "결합 프로모션은 진열만 및 전단만 각각보다 판매성과가 높게 관찰됨",
            "next_best_action": "무프로모션 주차가 포함된 원자료 확보 또는 2×2 요인 실험(무프로모션·진열만·전단만·결합) 실시",
        }
    ]
)
diagnostic.to_csv(DIAGNOSTIC_OUTPUT, index=False, encoding="utf-8-sig")

print(group_counts.to_string(index=False))
print(diagnostic.to_string(index=False))
