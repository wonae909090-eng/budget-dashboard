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
FIXED_COST_COLUMNS = ["캠페인구분", "월", "고정비용"]

# 자연유입/브랜드 채널: 광고비를 늘린다고 DB수가 늘지 않고, 연도별 수요·브랜드 쿼리 추세를 따라감.
# 그래서 "광고비 → DB수" 회귀에서 제외하고 자체 추세로 별도 예측한다.
ORGANIC_MEDIA = ["네이버BS", "스마트올HP", "씽크빅HP", "키즈 SNS", "초등 SNS"]


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


def load_fixed_cost_data(path: str) -> pd.DataFrame:
    """고정비용(제작비 등) 데이터 로드: 캠페인구분, 월, 고정비용.

    매체 집행비와 무관하게 매달 나가는 제작비 등 부대비용. 예산 시뮬레이션에서
    유료 매체 예산 풀과는 별도로 "총예산" 표시에만 더해지는 통과 비용으로 취급한다.
    """
    df = _read_table(path)
    missing = [c for c in FIXED_COST_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}")

    df = df[FIXED_COST_COLUMNS].copy()
    df["캠페인구분"] = df["캠페인구분"].astype(str).str.strip()
    df["월"] = df["월"].astype(str).str.strip()
    df["고정비용"] = pd.to_numeric(df["고정비용"], errors="coerce")

    return df.sort_values(["캠페인구분", "월"]).reset_index(drop=True)


def build_paid_monthly(media_df: pd.DataFrame) -> pd.DataFrame:
    """자연유입 채널을 제외한 유료 확장형 매체만 캠페인×월로 합산 (광고비, DB수).

    기존 core/data_cleaning.py의 월별 데이터와 동일한 컬럼 구조(캠페인구분, 월, 광고비, DB수)로
    반환해서 core/budget_model.py의 회귀 로직을 그대로 재사용할 수 있게 한다.
    """
    paid = media_df[~media_df["매체"].isin(ORGANIC_MEDIA)]
    return (
        paid.groupby(["캠페인구분", "월"], as_index=False)
        .agg(광고비=("광고비", "sum"), DB수=("DB수", "sum"))
        .sort_values(["캠페인구분", "월"])
        .reset_index(drop=True)
    )


def build_organic_monthly(media_df: pd.DataFrame) -> pd.DataFrame:
    """자연유입/브랜드 채널만 캠페인×월로 합산 (DB수). 광고비 대비 반응이 아니라 추세 예측용."""
    organic = media_df[media_df["매체"].isin(ORGANIC_MEDIA)]
    return (
        organic.groupby(["캠페인구분", "월"], as_index=False)
        .agg(DB수=("DB수", "sum"))
        .sort_values(["캠페인구분", "월"])
        .reset_index(drop=True)
    )


# 캠페인별로 "효율이 좋았던 달"을 판단할 때 기준으로 삼는 핵심 채널.
# 담당자 판단 기준 — 캠페인 전체 매체 믹스가 아니라 이 채널들의 실적으로 효율 우수월을 가른다.
EFFICIENCY_KEY_CHANNELS = {
    "키즈": ["메타", "네이버GFA"],
    "초등": ["메타"],
    "중학": ["메타", "GDN"],
}


def build_key_channel_monthly(media_df: pd.DataFrame, campaign: str) -> pd.DataFrame | None:
    """캠페인의 효율 판단 핵심 채널(EFFICIENCY_KEY_CHANNELS)만 모아 월별 합산 (광고비, DB수).

    핵심 채널이 정의되지 않았거나 데이터가 없으면 None을 반환한다.
    """
    channels = EFFICIENCY_KEY_CHANNELS.get(campaign)
    if not channels:
        return None
    sub = media_df[
        (media_df["캠페인구분"] == campaign) & (media_df["매체"].isin(channels))
    ].dropna(subset=["광고비", "DB수"])
    if sub.empty:
        return None
    return (
        sub.groupby("월", as_index=False)
        .agg(광고비=("광고비", "sum"), DB수=("DB수", "sum"))
        .sort_values("월")
        .reset_index(drop=True)
    )


def estimate_fixed_cost(fixed_cost_df: pd.DataFrame, campaign: str, n: int = 3) -> float:
    """캠페인의 최근 n개월 평균 고정비용으로 다음 달 고정비용을 추정 (자동 기본값, 사용자가 조정 가능)."""
    camp_df = fixed_cost_df[fixed_cost_df["캠페인구분"] == campaign].sort_values("월")
    if camp_df.empty:
        return 0.0
    return float(camp_df["고정비용"].tail(n).mean())
