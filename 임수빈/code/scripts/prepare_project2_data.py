#!/usr/bin/env python3
"""Prepare reproducible analysis tables for the Dunnhumby Complete Journey data.

The source directory is read-only. All generated files are written below the
project's data/processed and reports directories.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


EXPECTED_COLUMNS = {
    "campaign_desc.csv": ["DESCRIPTION", "CAMPAIGN", "START_DAY", "END_DAY"],
    "campaign_table.csv": ["DESCRIPTION", "household_key", "CAMPAIGN"],
    "causal_data.csv": ["PRODUCT_ID", "STORE_ID", "WEEK_NO", "display", "mailer"],
    "coupon.csv": ["COUPON_UPC", "PRODUCT_ID", "CAMPAIGN"],
    "coupon_redempt.csv": ["household_key", "DAY", "COUPON_UPC", "CAMPAIGN"],
    "hh_demographic.csv": [
        "AGE_DESC", "MARITAL_STATUS_CODE", "INCOME_DESC", "HOMEOWNER_DESC",
        "HH_COMP_DESC", "HOUSEHOLD_SIZE_DESC", "KID_CATEGORY_DESC", "household_key",
    ],
    "product.csv": [
        "PRODUCT_ID", "MANUFACTURER", "DEPARTMENT", "BRAND", "COMMODITY_DESC",
        "SUB_COMMODITY_DESC", "CURR_SIZE_OF_PRODUCT",
    ],
    "transaction_data.csv": [
        "household_key", "BASKET_ID", "DAY", "PRODUCT_ID", "QUANTITY", "SALES_VALUE",
        "STORE_ID", "RETAIL_DISC", "TRANS_TIME", "WEEK_NO", "COUPON_DISC",
        "COUPON_MATCH_DISC",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--chunksize", type=int, default=1_000_000)
    return parser.parse_args()


def require_files(source: Path) -> None:
    missing = [name for name in EXPECTED_COLUMNS if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing source files: {missing}")
    for name, expected in EXPECTED_COLUMNS.items():
        actual = pd.read_csv(source / name, nrows=0).columns.tolist()
        if actual != expected:
            raise ValueError(f"Unexpected schema for {name}: {actual}")


def profile_small_file(path: Path, key_columns: list[str]) -> dict:
    frame = pd.read_csv(path)
    duplicate_rows = int(frame.duplicated().sum())
    duplicate_keys = int(frame.duplicated(key_columns).sum()) if key_columns else None
    return {
        "file": path.name,
        "rows": len(frame),
        "columns": len(frame.columns),
        "duplicate_rows": duplicate_rows,
        "duplicate_keys": duplicate_keys,
        "missing_cells": int(frame.isna().sum().sum()),
        "missing_by_column": json.dumps(frame.isna().sum().astype(int).to_dict(), ensure_ascii=False),
    }


def load_transactions(path: Path) -> pd.DataFrame:
    dtypes = {
        "household_key": "int32", "BASKET_ID": "int64", "DAY": "int16",
        "PRODUCT_ID": "int32", "QUANTITY": "int32", "SALES_VALUE": "float32",
        "STORE_ID": "int32", "RETAIL_DISC": "float32", "TRANS_TIME": "int16",
        "WEEK_NO": "int16", "COUPON_DISC": "float32", "COUPON_MATCH_DISC": "float32",
    }
    return pd.read_csv(path, dtype=dtypes)


def build_customer_week(tx: pd.DataFrame) -> pd.DataFrame:
    tx = tx.copy()
    tx["total_discount"] = -(
        tx["RETAIL_DISC"] + tx["COUPON_DISC"] + tx["COUPON_MATCH_DISC"]
    )
    result = (
        tx.groupby(["household_key", "WEEK_NO"], observed=True)
        .agg(
            revenue=("SALES_VALUE", "sum"),
            baskets=("BASKET_ID", "nunique"),
            shopping_days=("DAY", "nunique"),
            items=("QUANTITY", "sum"),
            total_discount=("total_discount", "sum"),
            unique_products=("PRODUCT_ID", "nunique"),
            unique_stores=("STORE_ID", "nunique"),
        )
        .reset_index()
        .sort_values(["household_key", "WEEK_NO"])
    )
    result["avg_basket_value"] = result["revenue"] / result["baskets"].replace(0, np.nan)
    result["discount_to_sales_ratio"] = result["total_discount"] / (
        result["revenue"] + result["total_discount"]
    ).replace(0, np.nan)
    return result


def build_customer_features(tx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    dataset_end = int(tx["DAY"].max())
    validation_days = 56
    cutoff = dataset_end - validation_days

    basket_days = (
        tx[["household_key", "BASKET_ID", "DAY"]]
        .drop_duplicates()
        .sort_values(["household_key", "DAY", "BASKET_ID"])
    )
    visit_days = basket_days[["household_key", "DAY"]].drop_duplicates()
    visit_days["gap_days"] = visit_days.groupby("household_key")["DAY"].diff()
    intervals = visit_days.dropna(subset=["gap_days"]).copy()

    hist = tx.loc[tx["DAY"] <= cutoff].copy()
    future_households = set(tx.loc[tx["DAY"] > cutoff, "household_key"].unique())
    hist["total_discount"] = -(
        hist["RETAIL_DISC"] + hist["COUPON_DISC"] + hist["COUPON_MATCH_DISC"]
    )
    base = hist.groupby("household_key", observed=True).agg(
        first_day=("DAY", "min"),
        last_day=("DAY", "max"),
        active_days=("DAY", "nunique"),
        baskets=("BASKET_ID", "nunique"),
        revenue=("SALES_VALUE", "sum"),
        items=("QUANTITY", "sum"),
        total_discount=("total_discount", "sum"),
        unique_products=("PRODUCT_ID", "nunique"),
        unique_stores=("STORE_ID", "nunique"),
    )
    gap_stats = (
        intervals.loc[intervals["DAY"] <= cutoff]
        .groupby("household_key")["gap_days"]
        .agg(median_gap_days="median", mean_gap_days="mean", p75_gap_days=lambda x: x.quantile(0.75))
    )
    features = base.join(gap_stats, how="left").reset_index()
    features["recency_at_cutoff"] = cutoff - features["last_day"]
    features["avg_basket_value"] = features["revenue"] / features["baskets"].replace(0, np.nan)
    features["discount_to_sales_ratio"] = features["total_discount"] / (
        features["revenue"] + features["total_discount"]
    ).replace(0, np.nan)
    features["recency_to_gap_ratio"] = features["recency_at_cutoff"] / features[
        "median_gap_days"
    ].replace(0, np.nan)
    features["churn_56d_label"] = (~features["household_key"].isin(future_households)).astype("int8")
    features["risk_rule_1_5x_gap"] = (
        (features["recency_to_gap_ratio"] >= 1.5) & (features["recency_at_cutoff"] >= 14)
    ).astype("int8")
    features = features.sort_values("household_key")

    meta = {"dataset_end_day": dataset_end, "feature_cutoff_day": cutoff, "label_window_days": validation_days}
    return features, intervals, meta


def profile_causal(path: Path, chunksize: int) -> tuple[dict, pd.DataFrame]:
    rows = 0
    missing = defaultdict(int)
    distinct = {col: set() for col in ["PRODUCT_ID", "STORE_ID", "WEEK_NO", "display", "mailer"]}
    summaries = []
    causal_dtypes = {
        "PRODUCT_ID": "int32", "STORE_ID": "int32", "WEEK_NO": "int16",
        "display": "string", "mailer": "string",
    }
    for chunk in pd.read_csv(path, chunksize=chunksize, dtype=causal_dtypes):
        rows += len(chunk)
        for col, count in chunk.isna().sum().items():
            missing[col] += int(count)
        for col in distinct:
            distinct[col].update(chunk[col].dropna().unique().tolist())
        summaries.append(
            chunk.groupby(["WEEK_NO", "display", "mailer"], dropna=False).size().rename("rows").reset_index()
        )
    weekly = (
        pd.concat(summaries)
        .groupby(["WEEK_NO", "display", "mailer"], dropna=False)["rows"]
        .sum()
        .reset_index()
        .sort_values(["WEEK_NO", "display", "mailer"], na_position="last")
    )
    profile = {
        "file": path.name,
        "rows": rows,
        "columns": 5,
        "duplicate_rows": np.nan,
        "duplicate_keys": np.nan,
        "missing_cells": sum(missing.values()),
        "missing_by_column": json.dumps(dict(missing), ensure_ascii=False),
    }
    for col, values in distinct.items():
        profile[f"distinct_{col}"] = len(values)
    return profile, weekly


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    project = args.project.resolve()
    processed = project / "data" / "processed"
    reports = project / "reports"
    processed.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    require_files(source)

    keys = {
        "campaign_desc.csv": ["CAMPAIGN"],
        "campaign_table.csv": ["household_key", "CAMPAIGN"],
        "coupon.csv": ["COUPON_UPC", "PRODUCT_ID", "CAMPAIGN"],
        "coupon_redempt.csv": ["household_key", "DAY", "COUPON_UPC", "CAMPAIGN"],
        "hh_demographic.csv": ["household_key"],
        "product.csv": ["PRODUCT_ID"],
    }
    profiles = [profile_small_file(source / name, key) for name, key in keys.items()]

    tx = load_transactions(source / "transaction_data.csv")
    profiles.append({
        "file": "transaction_data.csv",
        "rows": len(tx),
        "columns": len(tx.columns),
        "duplicate_rows": int(tx.duplicated().sum()),
        "duplicate_keys": int(tx.duplicated(["household_key", "BASKET_ID", "PRODUCT_ID", "DAY"]).sum()),
        "missing_cells": int(tx.isna().sum().sum()),
        "missing_by_column": json.dumps(tx.isna().sum().astype(int).to_dict()),
    })
    causal_profile, causal_week = profile_causal(source / "causal_data.csv", args.chunksize)
    profiles.append(causal_profile)

    customer_week = build_customer_week(tx)
    customer_features, purchase_intervals, meta = build_customer_features(tx)

    products = pd.read_csv(source / "product.csv", usecols=["PRODUCT_ID"])
    demographics = pd.read_csv(source / "hh_demographic.csv", usecols=["household_key"])
    campaign_table = pd.read_csv(source / "campaign_table.csv")
    campaign_desc = pd.read_csv(source / "campaign_desc.csv")
    coupons = pd.read_csv(source / "coupon.csv")
    redemptions = pd.read_csv(source / "coupon_redempt.csv")
    tx_households = set(tx["household_key"].unique())
    tx_products = set(tx["PRODUCT_ID"].unique())
    campaign_ids = set(campaign_desc["CAMPAIGN"].unique())
    coupon_ids = set(coupons["COUPON_UPC"].unique())
    join_quality = pd.DataFrame([
        ["transactions -> product", len(tx), int(tx["PRODUCT_ID"].isin(set(products["PRODUCT_ID"])).sum())],
        ["transactions -> demographics", tx["household_key"].nunique(), len(tx_households & set(demographics["household_key"]))],
        ["campaign households -> transactions", campaign_table["household_key"].nunique(), len(set(campaign_table["household_key"]) & tx_households)],
        ["campaign table -> campaign desc", len(campaign_table), int(campaign_table["CAMPAIGN"].isin(campaign_ids).sum())],
        ["coupon products -> product", len(coupons), int(coupons["PRODUCT_ID"].isin(set(products["PRODUCT_ID"])).sum())],
        ["redemptions -> coupon", len(redemptions), int(redemptions["COUPON_UPC"].isin(coupon_ids).sum())],
        ["redemption households -> transactions", redemptions["household_key"].nunique(), len(set(redemptions["household_key"]) & tx_households)],
    ], columns=["join", "left_count", "matched_count"])
    join_quality["match_rate"] = join_quality["matched_count"] / join_quality["left_count"]

    pd.DataFrame(profiles).sort_values("file").to_csv(processed / "file_profile.csv", index=False)
    join_quality.to_csv(processed / "join_quality.csv", index=False)
    customer_week.to_csv(processed / "customer_week.csv", index=False)
    customer_features.to_csv(processed / "customer_features.csv", index=False)
    purchase_intervals.to_csv(processed / "purchase_intervals.csv", index=False)
    causal_week.to_csv(processed / "causal_week_summary.csv", index=False)

    summary = {
        **meta,
        "transaction_rows": len(tx),
        "households": int(tx["household_key"].nunique()),
        "baskets": int(tx["BASKET_ID"].nunique()),
        "products_purchased": int(tx["PRODUCT_ID"].nunique()),
        "stores": int(tx["STORE_ID"].nunique()),
        "sales_value_sum": round(float(tx["SALES_VALUE"].sum()), 2),
        "negative_sales_rows": int((tx["SALES_VALUE"] < 0).sum()),
        "zero_sales_rows": int((tx["SALES_VALUE"] == 0).sum()),
        "nonpositive_quantity_rows": int((tx["QUANTITY"] <= 0).sum()),
        "customer_week_rows": len(customer_week),
        "labeled_customers": len(customer_features),
        "churn_56d_rate": round(float(customer_features["churn_56d_label"].mean()), 6),
        "risk_rule_rate": round(float(customer_features["risk_rule_1_5x_gap"].mean()), 6),
    }
    (reports / "preprocessing_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
