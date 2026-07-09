"""캠페인별 광고비 대비 DB수/DB단가 회귀 모델 및 예산 추천."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PEAK_MONTHS = {1, 2, 7, 8}
RIDGE_ALPHA = 1.0
DEGREE2_IMPROVEMENT_THRESHOLD = 0.95  # 2차 모델의 LOOCV MAE가 1차보다 5% 이상 개선돼야 채택


def _is_peak(월_series: pd.Series) -> np.ndarray:
    month_num = 월_series.str.slice(5, 7).astype(int)
    return month_num.isin(PEAK_MONTHS).astype(float).to_numpy()


def _design_matrix(ad_spend: np.ndarray, is_peak: np.ndarray, degree: int) -> np.ndarray:
    cols = [ad_spend]
    if degree >= 2:
        cols.append(ad_spend ** 2)
    cols.append(is_peak)
    return np.column_stack(cols)


def _fit_degree(ad_spend: np.ndarray, is_peak: np.ndarray, y: np.ndarray, degree: int) -> dict:
    X = _design_matrix(ad_spend, is_peak, degree)
    pipeline = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA))

    loo_preds = cross_val_predict(pipeline, X, y, cv=LeaveOneOut())
    loocv_mae = mean_absolute_error(y, loo_preds)
    loocv_r2 = r2_score(y, loo_preds)

    pipeline.fit(X, y)
    in_sample_r2 = pipeline.score(X, y)

    return {
        "pipeline": pipeline,
        "degree": degree,
        "loocv_mae": loocv_mae,
        "loocv_r2": loocv_r2,
        "in_sample_r2": in_sample_r2,
    }


def fit_campaign_model(camp_df: pd.DataFrame) -> dict:
    """캠페인 1개의 월별 데이터로 DB수 ~ 광고비(+성수기 더미) 회귀모델 학습.

    1차/2차 다항회귀 중 LOOCV MAE가 5% 이상 개선되는 경우에만 2차를 채택
    (17개월 데이터로는 2차가 쉽게 과적합되므로 기본은 1차를 선호).
    """
    camp_df = camp_df.sort_values("월")
    ad_spend = camp_df["광고비"].to_numpy(dtype=float)
    y = camp_df["DB수"].to_numpy(dtype=float)
    is_peak = _is_peak(camp_df["월"])

    deg1 = _fit_degree(ad_spend, is_peak, y, degree=1)
    deg2 = _fit_degree(ad_spend, is_peak, y, degree=2)

    if deg2["loocv_mae"] < deg1["loocv_mae"] * DEGREE2_IMPROVEMENT_THRESHOLD:
        chosen, alt = deg2, deg1
    else:
        chosen, alt = deg1, deg2

    chosen = dict(chosen)
    chosen["campaign"] = camp_df["캠페인구분"].iloc[0]
    chosen["n_obs"] = len(camp_df)
    chosen["alt_degree"] = alt["degree"]
    chosen["alt_loocv_mae"] = alt["loocv_mae"]
    chosen["alt_loocv_r2"] = alt["loocv_r2"]
    return chosen


def predict_db_count(model_info: dict, budget, is_peak: float = 0.0) -> np.ndarray:
    budget = np.atleast_1d(np.asarray(budget, dtype=float))
    is_peak_arr = np.full_like(budget, is_peak)
    X = _design_matrix(budget, is_peak_arr, model_info["degree"])
    pred = model_info["pipeline"].predict(X)
    return np.clip(pred, 1.0, None)  # 0 나누기 방지를 위해 최소 1로 클리핑


def predict_db_price(model_info: dict, budget, is_peak: float = 0.0) -> np.ndarray:
    budget = np.atleast_1d(np.asarray(budget, dtype=float))
    db_count = predict_db_count(model_info, budget, is_peak)
    return budget / db_count


def get_current_budget(camp_df: pd.DataFrame, method: str = "avg3") -> float:
    """현재예산 산출. method='avg3'(최근 3개월 평균, 기본값) 또는 'latest'(최근월)."""
    camp_df = camp_df.sort_values("월")
    if method == "latest":
        return float(camp_df["광고비"].iloc[-1])
    return float(camp_df["광고비"].tail(3).mean())


def reference_db_price(camp_df: pd.DataFrame, target_price: float | None = None, lookback: int = 12) -> float:
    """캠페인 간 효율 비교의 기준값(그 캠페인 자신의 '정상' DB단가 수준).

    캠페인마다 시장 특성상 DB단가 절대 수준이 다르므로, 캠페인 간 비교는 항상 이 기준값
    대비 상대적으로 계산해야 함. 목표DB단가가 입력되어 있으면 그 값을, 없으면 최근
    `lookback`개월의 가중평균 DB단가(광고비합/DB수합)를 기준으로 사용.
    """
    if target_price:
        return float(target_price)
    recent = camp_df.sort_values("월").tail(lookback)
    return float(recent["광고비"].sum() / recent["DB수"].sum())


def _budget_grid(camp_df: pd.DataFrame, n: int = 300) -> np.ndarray:
    max_budget = camp_df["광고비"].max()
    return np.linspace(max_budget * 0.2, max_budget * 2.5, n)


def max_grid_budget(camp_df: pd.DataFrame) -> float:
    """탐색 그리드의 최대 예산값(회귀모델로 추정 가능한 상한, 참고용)."""
    return float(_budget_grid(camp_df).max())


def min_budget_for_db_count(
    model_info: dict, camp_df: pd.DataFrame, min_db_count: float, is_peak: float = 0.0
) -> float | None:
    """최소 DB목표(min_db_count)를 만족하는 최소 예산. 그리드 내에서 불가능하면 None."""
    grid = _budget_grid(camp_df)
    counts = predict_db_count(model_info, grid, is_peak)
    feasible = grid[counts >= min_db_count]
    if len(feasible) == 0:
        return None
    return float(feasible.min())


def recommend_by_target_price(
    model_info: dict, camp_df: pd.DataFrame, target_db_price: float, is_peak: float = 0.0
) -> float | None:
    """목표 DB단가를 만족하는 예산 구간 중 최대 예산(=DB수를 가장 많이 확보하는 지점)."""
    grid = _budget_grid(camp_df)
    prices = predict_db_price(model_info, grid, is_peak)
    feasible = grid[prices <= target_db_price]
    if len(feasible) == 0:
        return None
    return float(feasible.max())


def recommend_by_inflection(model_info: dict, camp_df: pd.DataFrame, is_peak: float = 0.0) -> float:
    """DB단가(광고비/DB수) 급등 변곡점(elbow) 탐색.

    kneedle 방식: 예산-DB단가 곡선을 0~1로 정규화한 뒤, 시작점-끝점을 잇는 직선에서
    수직거리가 가장 먼 지점을 변곡점으로 판단.
    """
    grid = _budget_grid(camp_df)
    prices = predict_db_price(model_info, grid, is_peak)

    x = (grid - grid.min()) / (grid.max() - grid.min())
    y = (prices - prices.min()) / (prices.max() - prices.min() + 1e-9)

    x0, y0, x1, y1 = x[0], y[0], x[-1], y[-1]
    line_vec = np.array([x1 - x0, y1 - y0])
    line_len = np.linalg.norm(line_vec)
    line_unit = line_vec / line_len if line_len > 0 else np.array([1.0, 0.0])

    points = np.column_stack([x - x0, y - y0])
    proj_len = points @ line_unit
    proj_points = np.outer(proj_len, line_unit)
    dist = np.linalg.norm(points - proj_points, axis=1)

    elbow_idx = int(np.argmax(dist))
    return float(grid[elbow_idx])


def build_model_report(df: pd.DataFrame) -> pd.DataFrame:
    """캠페인별 모델 성능(R², MAE) 리포트."""
    rows = []
    for campaign in sorted(df["캠페인구분"].unique()):
        camp_df = df[df["캠페인구분"] == campaign]
        m = fit_campaign_model(camp_df)
        rows.append({
            "캠페인구분": campaign,
            "선택모델": "2차(다항)" if m["degree"] == 2 else "1차(선형)",
            "LOOCV_R2": m["loocv_r2"],
            "LOOCV_MAE": m["loocv_mae"],
            "인샘플_R2": m["in_sample_r2"],
            "데이터포인트수": m["n_obs"],
        })
    return pd.DataFrame(rows)


def build_budget_recommendations(
    df: pd.DataFrame,
    method: str = "target_price",
    target_prices: dict | None = None,
    current_budget_method: str = "avg3",
    target_month: str | None = None,
) -> pd.DataFrame:
    """캠페인별 회귀모델 학습 + 예산 추천 결과.

    method: "target_price"(목표 DB단가를 만족하는 최대 예산) 또는 "inflection"(DB단가 급등 변곡점)
    target_prices: {캠페인명: 목표DB단가}. 미지정 캠페인은 최근 3개월 실제 DB단가를 목표로 사용.
    target_month: 예측 대상월("YYYY-MM"), 성수기(1,2,7,8월) 여부 판단에 사용. 미지정 시 비성수기 기준.
    """
    target_prices = target_prices or {}

    if target_month:
        month_num = int(target_month.split("-")[1])
        is_peak_target = 1.0 if month_num in PEAK_MONTHS else 0.0
    else:
        is_peak_target = 0.0

    rows = []
    for campaign in sorted(df["캠페인구분"].unique()):
        camp_df = df[df["캠페인구분"] == campaign]
        model_info = fit_campaign_model(camp_df)
        current_budget = get_current_budget(camp_df, method=current_budget_method)

        notes = []
        if method == "inflection":
            recommended_budget = recommend_by_inflection(model_info, camp_df, is_peak_target)
        else:
            target_price = target_prices.get(campaign)
            if not target_price:
                target_price = float(camp_df["광고비"].tail(3).sum() / camp_df["DB수"].tail(3).sum())
                notes.append("목표 DB단가 미입력 → 최근 3개월 실제 DB단가를 목표로 사용")
            recommended_budget = recommend_by_target_price(model_info, camp_df, target_price, is_peak_target)
            if recommended_budget is None:
                recommended_budget = current_budget
                notes.append("목표 DB단가를 만족하는 예산 구간을 찾지 못해 현재예산 유지")
        note = "; ".join(notes)

        expected_db = float(predict_db_count(model_info, recommended_budget, is_peak_target)[0])
        expected_price = float(predict_db_price(model_info, recommended_budget, is_peak_target)[0])

        rows.append({
            "캠페인구분": campaign,
            "현재예산": current_budget,
            "추천예산": recommended_budget,
            "예상DB수": expected_db,
            "예상DB단가": expected_price,
            "모델신뢰도(R2)": model_info["loocv_r2"],
            "모델차수": model_info["degree"],
            "비고": note,
        })

    return pd.DataFrame(rows)


@st.cache_data(show_spinner="회귀 모델 학습 및 예산 추천 계산 중...")
def cached_budget_recommendations(
    df: pd.DataFrame,
    method: str = "target_price",
    target_prices: dict | None = None,
    current_budget_method: str = "avg3",
    target_month: str | None = None,
) -> pd.DataFrame:
    return build_budget_recommendations(df, method, target_prices, current_budget_method, target_month)
