"""원본 데이터 파싱, 정합성 검증, 이상치 탐지."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

RAW_COLUMNS = ["캠페인구분", "월", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]
NUMERIC_COMMA_COLS = ["광고비", "DB수", "DB단가", "입회단가"]
CAMPAIGN_ORDER = ["키즈", "초등", "중학"]


def _to_number(series: pd.Series) -> pd.Series:
    """콤마 포함 문자열, 콤마 없는 숫자/소수 문자열, 이미 숫자형인 값을 모두 안전하게 float로 변환."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def _to_ratio(series: pd.Series) -> pd.Series:
    """입회율을 0~1 비율로 통일. '23.9%' 문자열, 23.9(퍼센트 숫자), 0.239(이미 비율) 모두 처리."""
    if pd.api.types.is_numeric_dtype(series):
        values = series.astype(float)
    else:
        cleaned = series.astype(str).str.replace("%", "", regex=False).str.strip()
        values = pd.to_numeric(cleaned, errors="coerce")
    # 절대값 기준 1.5를 넘는 값이 하나라도 있으면 퍼센트(0~100) 표기로 판단해 100으로 나눈다.
    if (values.abs() > 1.5).any():
        values = values / 100.0
    return values


def load_raw_data(path: str) -> pd.DataFrame:
    """원본 파일(xlsx 또는 csv)을 읽어 표준 스키마로 정제한다.

    - 캠페인구분 (str)
    - 월 (str, "YYYY-MM")
    - 광고비 (float)
    - DB수 (float)
    - DB단가 (float)
    - 입회수 (int)
    - 입회단가 (float)
    - 입회율 (float, 0~1 비율)
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        try:
            df = pd.read_csv(path, encoding="euc-kr")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="utf-8")

    missing_cols = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"필수 컬럼이 없습니다: {missing_cols}")

    df = df[RAW_COLUMNS].copy()
    df["캠페인구분"] = df["캠페인구분"].astype(str).str.strip()
    df["월"] = df["월"].astype(str).str.strip()

    for col in NUMERIC_COMMA_COLS:
        df[col] = _to_number(df[col])

    df["DB수"] = _to_number(df["DB수"])
    df["입회수"] = _to_number(df["입회수"]).round().astype("Int64")
    df["입회율"] = _to_ratio(df["입회율"])

    df = df.sort_values(["캠페인구분", "월"]).reset_index(drop=True)
    return df


def check_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """캠페인구분×월 조합 중복 행을 찾아 반환한다 (없으면 빈 DataFrame)."""
    dup_mask = df.duplicated(subset=["캠페인구분", "월"], keep=False)
    return df.loc[dup_mask].sort_values(["캠페인구분", "월"])


def validate_consistency(df: pd.DataFrame, tolerance: float = 0.01) -> pd.DataFrame:
    """DB단가/입회단가/입회율의 재계산값과 원본값을 비교해 ±tolerance 초과 시 플래그."""
    df = df.copy()
    df["flag_inconsistent"] = False
    df["reason"] = ""

    db단가_calc = df["광고비"] / df["DB수"].replace(0, np.nan)
    입회단가_calc = df["광고비"] / df["입회수"].replace(0, np.nan)
    입회율_calc = df["입회수"] / df["DB수"].replace(0, np.nan)

    checks = [
        ("DB단가", db단가_calc, "DB단가 불일치(광고비/DB수와 차이)"),
        ("입회단가", 입회단가_calc, "입회단가 불일치(광고비/입회수와 차이)"),
        ("입회율", 입회율_calc, "입회율 불일치(입회수/DB수와 차이)"),
    ]

    for col, calc, reason in checks:
        rel_diff = ((df[col] - calc).abs() / calc.abs().replace(0, np.nan))
        mismatched = rel_diff > tolerance
        mismatched = mismatched.fillna(False)
        df.loc[mismatched, "flag_inconsistent"] = True
        df.loc[mismatched, "reason"] = df.loc[mismatched, "reason"].where(
            df.loc[mismatched, "reason"] == "", df.loc[mismatched, "reason"] + "; "
        ) + reason

    return df


def detect_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """이상치 조건 3가지를 검사해 flag_outlier, outlier_reason 컬럼 추가."""
    df = df.sort_values(["캠페인구분", "월"]).reset_index(drop=True)
    df["flag_outlier"] = False
    df["outlier_reason"] = ""

    def add_reason(mask: pd.Series, reason: str) -> None:
        mask = mask.fillna(False)
        df.loc[mask, "flag_outlier"] = True
        df.loc[mask, "outlier_reason"] = df.loc[mask, "outlier_reason"].where(
            df.loc[mask, "outlier_reason"] == "", df.loc[mask, "outlier_reason"] + "; "
        ) + reason

    # 조건 1: DB단가가 해당 캠페인 최근 3개월 평균 대비 ±50% 이상 벗어남
    for campaign in df["캠페인구분"].unique():
        camp_mask = df["캠페인구분"] == campaign
        idx = df.index[camp_mask]
        db단가 = df.loc[idx, "DB단가"]
        rolling_avg = db단가.shift(1).rolling(window=3, min_periods=1).mean()
        deviation = (db단가 - rolling_avg).abs() / rolling_avg.replace(0, np.nan)
        add_reason(deviation.reindex(df.index) > 0.5, "DB단가가 최근 3개월 평균 대비 ±50% 이상 벗어남")

    # 조건 2: 입회율이 0~100% 범위를 벗어남
    add_reason((df["입회율"] < 0) | (df["입회율"] > 1), "입회율이 0~100% 범위를 벗어남")

    # 조건 3: 광고비/DB수(DB단가)가 전월 대비 ±80% 이상 급변
    for campaign in df["캠페인구분"].unique():
        camp_mask = df["캠페인구분"] == campaign
        idx = df.index[camp_mask]
        db단가 = df.loc[idx, "DB단가"]
        pct_change = db단가.pct_change().abs()
        add_reason(pct_change.reindex(df.index) >= 0.8, "광고비/DB수가 전월 대비 ±80% 이상 급변")

    return df


def calc_mom_yoy(df: pd.DataFrame) -> pd.DataFrame:
    """캠페인별 시계열 정렬 후 MoM/YoY 증감률(%) 계산."""
    df = df.sort_values(["캠페인구분", "월"]).reset_index(drop=True)
    metrics = ["광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]

    for metric in metrics:
        mom_col = f"{metric}_MoM"
        yoy_col = f"{metric}_YoY"
        df[mom_col] = df.groupby("캠페인구분")[metric].pct_change(periods=1) * 100
        # 데이터가 월 단위로 연속(2025-01~2026-05)이라고 가정, 12개월 전 대비
        df[yoy_col] = df.groupby("캠페인구분")[metric].pct_change(periods=12) * 100
        # 2025년 데이터는 12개월 전 데이터가 없으므로 자연스럽게 NaN 처리됨

    return df


def clean_pipeline(path: str) -> dict:
    """전체 정제 파이프라인 실행: load → validate → outlier → mom/yoy.

    반환: {"df": 최종 DataFrame, "duplicates": 중복행 DataFrame,
           "n_inconsistent": int, "n_outlier": int}
    """
    raw = load_raw_data(path)
    duplicates = check_duplicates(raw)

    df = validate_consistency(raw)
    df = detect_outliers(df)
    df = calc_mom_yoy(df)

    return {
        "df": df,
        "duplicates": duplicates,
        "n_inconsistent": int(df["flag_inconsistent"].sum()),
        "n_outlier": int(df["flag_outlier"].sum()),
        "n_rows": len(df),
    }
