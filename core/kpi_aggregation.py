"""캠페인/전체 KPI 집계, MoM·YoY, 목표 대비 달성률."""

from __future__ import annotations

import os

import pandas as pd

METRICS = ["광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]
TARGETS_FILENAMES = ["Targets.csv", "Targets.xlsx", "targets.csv", "targets.xlsx"]


def _add_mom_yoy(df: pd.DataFrame, group_col: str | None, metrics: list[str]) -> pd.DataFrame:
    """월 기준 정렬 후 MoM(전월 대비)/YoY(전년 동월 대비) 증감률(%) 컬럼 추가."""
    df = df.sort_values(([group_col] if group_col else []) + ["월"]).reset_index(drop=True)
    grouped = df.groupby(group_col) if group_col else None

    for metric in metrics:
        if metric not in df.columns:
            continue
        series = grouped[metric] if grouped is not None else df[metric]
        df[f"{metric}_MoM"] = series.pct_change(periods=1) * 100
        df[f"{metric}_YoY"] = series.pct_change(periods=12) * 100

    return df


def aggregate_by_campaign_month(df: pd.DataFrame) -> pd.DataFrame:
    """캠페인×월 단위 KPI 집계 (광고비/DB수/입회수는 합, 단가는 가중평균으로 재계산)."""
    grouped = df.groupby(["캠페인구분", "월"], as_index=False).agg(
        광고비=("광고비", "sum"),
        DB수=("DB수", "sum"),
        입회수=("입회수", "sum"),
    )
    grouped["DB단가"] = grouped["광고비"] / grouped["DB수"]
    grouped["입회단가"] = grouped["광고비"] / grouped["입회수"]
    grouped["입회율"] = grouped["입회수"] / grouped["DB수"]

    grouped = _add_mom_yoy(grouped, group_col="캠페인구분", metrics=METRICS)
    return grouped.sort_values(["캠페인구분", "월"]).reset_index(drop=True)


def aggregate_overall_by_month(df: pd.DataFrame) -> pd.DataFrame:
    """3개 캠페인 합계 기준 월별 전체 트렌드."""
    grouped = df.groupby("월", as_index=False).agg(
        광고비=("광고비", "sum"),
        DB수=("DB수", "sum"),
        입회수=("입회수", "sum"),
    )
    grouped["DB단가"] = grouped["광고비"] / grouped["DB수"]
    grouped["입회단가"] = grouped["광고비"] / grouped["입회수"]
    grouped["입회율"] = grouped["입회수"] / grouped["DB수"]

    grouped = _add_mom_yoy(grouped, group_col=None, metrics=METRICS)
    return grouped.sort_values("월").reset_index(drop=True)


def find_targets_file(search_dirs: list[str]) -> str | None:
    """context/data 폴더 등에서 Targets 파일을 자동 탐색 (fallback)."""
    for d in search_dirs:
        for fname in TARGETS_FILENAMES:
            candidate = os.path.join(d, fname)
            if os.path.exists(candidate):
                return candidate
    return None


def load_targets_file(path: str) -> pd.DataFrame:
    """Targets 파일 로드. 컬럼: 캠페인구분, 목표DB수, 목표DB단가, 월배정예산."""
    if path.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    return pd.read_csv(path)


def calc_target_achievement(agg_df: pd.DataFrame, targets: dict) -> pd.DataFrame:
    """targets = {캠페인명: {"목표DB수":, "목표DB단가":, "월배정예산":}} 형태.

    캠페인별 목표가 없으면 해당 캠페인 행의 달성률은 NaN(= "목표 미입력")으로 남긴다.
    """
    df = agg_df.copy()
    df["목표DB수"] = df["캠페인구분"].map(lambda c: targets.get(c, {}).get("목표DB수"))
    df["목표DB단가"] = df["캠페인구분"].map(lambda c: targets.get(c, {}).get("목표DB단가"))
    df["월배정예산"] = df["캠페인구분"].map(lambda c: targets.get(c, {}).get("월배정예산"))

    df["DB수_달성률"] = df["DB수"] / df["목표DB수"]
    # DB단가는 낮을수록 좋으므로 목표/실제로 계산 (1.0 이상이면 목표보다 효율적)
    df["DB단가_달성률"] = df["목표DB단가"] / df["DB단가"]
    df["예산_달성률"] = df["광고비"] / df["월배정예산"]

    return df


def build_kpi_summary(df: pd.DataFrame, targets: dict | None = None) -> dict:
    """KPI 집계 결과 묶음. session_state["kpi_summary"]에 저장할 딕셔너리."""
    campaign_monthly = aggregate_by_campaign_month(df)
    overall_monthly = aggregate_overall_by_month(df)

    if targets:
        campaign_monthly = calc_target_achievement(campaign_monthly, targets)

    return {
        "campaign_monthly": campaign_monthly,
        "overall_monthly": overall_monthly,
        "targets": targets or {},
    }
