"""일자별 데이터 / 매체별 데이터 로드 유틸리티.

월별 데이터(core/data_cleaning.py)와는 완전히 별도로 관리한다.
- 일자별 데이터: 인보이스 마감 기준이 아니라 광고비 합계가 월별 데이터와 다를 수 있음
- 매체별 데이터: 월별 데이터의 총 광고비에 매체 집행비 외 부대비용이 섞여 있어 합계가 다를 수 있음
따라서 월별 데이터와의 정합성 검증은 하지 않는다.
"""

from __future__ import annotations

import os

import pandas as pd

DAILY_COLUMNS = ["캠페인구분", "일자", "광고비", "DB수", "DB단가"]
MEDIA_COLUMNS = ["캠페인구분", "월", "매체", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]


def _read_table(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    try:
        return pd.read_csv(path, encoding="euc-kr")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8")


def load_daily_data(path: str) -> pd.DataFrame:
    """일자별 데이터 로드: 캠페인구분, 일자, 광고비, DB수, DB단가."""
    df = _read_table(path)
    missing = [c for c in DAILY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}")

    df = df[DAILY_COLUMNS].copy()
    df["캠페인구분"] = df["캠페인구분"].astype(str).str.strip()
    df["일자"] = pd.to_datetime(df["일자"]).dt.date
    for col in ["광고비", "DB수", "DB단가"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.sort_values(["캠페인구분", "일자"]).reset_index(drop=True)


def load_media_data(path: str) -> pd.DataFrame:
    """매체별 데이터 로드: 캠페인구분, 월, 매체, 광고비, DB수, DB단가, 입회수, 입회단가, 입회율."""
    df = _read_table(path)
    missing = [c for c in MEDIA_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}")

    df = df[MEDIA_COLUMNS].copy()
    df["캠페인구분"] = df["캠페인구분"].astype(str).str.strip()
    df["월"] = df["월"].astype(str).str.strip()
    df["매체"] = df["매체"].astype(str).str.strip()
    for col in ["광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.sort_values(["캠페인구분", "월", "매체"]).reset_index(drop=True)
