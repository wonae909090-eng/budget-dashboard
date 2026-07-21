"""캠페인별 광고비 대비 DB수/DB단가 회귀 모델 및 예산 추천."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from core.daily_media_data import EFFICIENCY_KEY_CHANNELS, build_key_channel_monthly

PEAK_MONTHS = {1, 2, 7, 8}  # 캠페인별 실제 패턴을 감지할 수 없을 때만 쓰는 대체값(fallback)
RIDGE_ALPHA = 1.0
DEGREE2_IMPROVEMENT_THRESHOLD = 0.95  # 2차 모델의 LOOCV MAE가 1차보다 5% 이상 개선돼야 채택
MIN_CALENDAR_MONTHS_FOR_SEASONALITY = 4  # 이보다 캘린더월 종류가 적으면 자동감지를 못 하고 fallback
LOW_SPEND_EXCLUDE_RATIO = 0.5  # 평균 대비 이 비율 미만으로 쓴 달은 "저예산이라 단가가 낮아 보이는 착시"로 보고 제외


def detect_peak_months(camp_df: pd.DataFrame, top_n: int = 4, metric: str = "광고비") -> set[int]:
    """캠페인의 실제 월별 패턴에서 상위 top_n개 달을 성수기(집행성수기)로 자동 감지.

    내부적으로 "성수기"는 광고비를 많이 집행하는 달을 의미한다(회귀의 성수기 더미 변수 용도,
    metric="광고비"가 기본값). DB단가 효율과는 별개 개념 — 오히려 성수기는 경쟁이 치열해져
    DB단가가 나빠지는 경향이 있다(아래 detect_efficiency_months 참고).
    자연유입 채널처럼 광고비 컬럼이 없는 데이터(DB수만 존재)에는 metric="DB수"로 호출한다.
    캠페인마다 다를 수 있어 실제 데이터 기반으로 판단하며, 데이터가 너무 적어 캘린더월 종류가
    부족하면 PEAK_MONTHS로 대체한다.
    """
    month_num = camp_df["월"].str.slice(5, 7).astype(int)
    monthly_avg = camp_df.assign(_월num=month_num).groupby("_월num")[metric].mean()
    if len(monthly_avg) < MIN_CALENDAR_MONTHS_FOR_SEASONALITY:
        return set(PEAK_MONTHS)
    top_months = monthly_avg.sort_values(ascending=False).head(top_n).index.tolist()
    return {int(m) for m in top_months}


def detect_efficiency_months(camp_df: pd.DataFrame, top_n: int = 4) -> set[int]:
    """캠페인의 실제 월별 DB단가(광고비/DB수) 패턴에서 효율이 가장 좋은(단가가 낮은) top_n개 달 감지.

    "성수기(광고비 집행이 많은 달)"와는 별개 개념 — 오히려 성수기는 경쟁이 치열해져 DB단가가
    나빠지는 경향이 있어, 광고비를 상대적으로 덜 쓰는 시기 중에서 효율이 가장 좋은 달을 찾는다.
    다만 평균 대비 지나치게 적게 쓴 달(LOW_SPEND_EXCLUDE_RATIO 미만)은 "단가가 우연히 낮아 보이는
    착시"일 수 있어 제외하고 판단한다 (참고용 인사이트, 회귀 계산 자체에는 쓰이지 않음).
    """
    camp_df = camp_df.copy()
    avg_spend = camp_df["광고비"].mean()
    if not avg_spend or avg_spend <= 0:
        return set()
    filtered = camp_df[camp_df["광고비"] >= avg_spend * LOW_SPEND_EXCLUDE_RATIO]

    month_num = filtered["월"].str.slice(5, 7).astype(int)
    db단가 = filtered["광고비"] / filtered["DB수"]
    monthly_avg = db단가.groupby(month_num).mean()
    if len(monthly_avg) < MIN_CALENDAR_MONTHS_FOR_SEASONALITY:
        return set()
    top_months = monthly_avg.sort_values(ascending=True).head(top_n).index.tolist()
    return {int(m) for m in top_months}


def _campaign_efficiency_months(
    camp_df: pd.DataFrame, campaign: str, media_df: pd.DataFrame | None
) -> set[int]:
    """효율 우수월 판단. media_df가 있고 이 캠페인의 핵심 채널(EFFICIENCY_KEY_CHANNELS)이 정의돼
    있으면 그 채널들의 실적만으로 판단하고, 없으면 df 전체 평균으로 판단한다(fallback)."""
    if media_df is not None and campaign in EFFICIENCY_KEY_CHANNELS:
        key_channel_df = build_key_channel_monthly(media_df, campaign)
        if key_channel_df is not None:
            return detect_efficiency_months(key_channel_df)
    return detect_efficiency_months(camp_df)


def _is_peak(월_series: pd.Series, peak_months: set[int] | None = None) -> np.ndarray:
    peak_months = peak_months if peak_months is not None else PEAK_MONTHS
    month_num = 월_series.str.slice(5, 7).astype(int)
    return month_num.isin(peak_months).astype(float).to_numpy()


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


def fit_campaign_model(camp_df: pd.DataFrame, peak_months: set[int] | None = None) -> dict:
    """캠페인 1개의 월별 데이터로 DB수 ~ 광고비(+성수기 더미) 회귀모델 학습.

    1차/2차 다항회귀 중 LOOCV MAE가 5% 이상 개선되는 경우에만 2차를 채택
    (17개월 데이터로는 2차가 쉽게 과적합되므로 기본은 1차를 선호).
    peak_months를 지정하지 않으면 이 캠페인의 실제 DB수 패턴에서 자동 감지한다.
    """
    camp_df = camp_df.sort_values("월")
    if peak_months is None:
        peak_months = detect_peak_months(camp_df)

    ad_spend = camp_df["광고비"].to_numpy(dtype=float)
    y = camp_df["DB수"].to_numpy(dtype=float)
    is_peak = _is_peak(camp_df["월"], peak_months)

    deg1 = _fit_degree(ad_spend, is_peak, y, degree=1)
    deg2 = _fit_degree(ad_spend, is_peak, y, degree=2)

    if deg2["loocv_mae"] < deg1["loocv_mae"] * DEGREE2_IMPROVEMENT_THRESHOLD:
        chosen, alt = deg2, deg1
    else:
        chosen, alt = deg1, deg2

    chosen = dict(chosen)
    chosen["campaign"] = camp_df["캠페인구분"].iloc[0]
    chosen["n_obs"] = len(camp_df)
    chosen["peak_months"] = peak_months
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


def get_recent_avg_budget(camp_df: pd.DataFrame, n: int = 3) -> float:
    """최근 n개월 평균 광고비 (보조 참고치 — 최신 흐름/모멘텀 파악용)."""
    return float(camp_df.sort_values("월")["광고비"].tail(n).mean())


def get_prior_year_budget(camp_df: pd.DataFrame, target_month: str) -> float | None:
    """전년 동월 실제 광고비. 해당 월 데이터가 없으면 None."""
    year, mon = int(target_month[:4]), int(target_month[5:7])
    prior_month = f"{year - 1:04d}-{mon:02d}"
    match = camp_df[camp_df["월"] == prior_month]
    if match.empty:
        return None
    return float(match["광고비"].iloc[0])


def get_reference_budget(camp_df: pd.DataFrame, target_month: str | None) -> dict:
    """예산 시뮬레이션 비교 기준(참고예산) 산출.

    메인 기준은 "전년 동월" 실제 집행액 — 교육업계는 계절성이 뚜렷해(겨울방학·신학기 등)
    최근 3개월보다 작년 같은 달과 비교하는 것이 왜곡이 적다. 전년 동월 데이터가 없으면
    최근 3개월 평균으로 대체한다. 최근 3개월 평균은 "최신 흐름"을 보여주는 보조 참고치로
    항상 함께 반환한다.
    """
    recent_avg = get_recent_avg_budget(camp_df)
    prior_year = get_prior_year_budget(camp_df, target_month) if target_month else None

    if prior_year is not None:
        return {"참고예산": prior_year, "참고예산기준": "전년동월", "최근3개월평균": recent_avg}
    return {
        "참고예산": recent_avg,
        "참고예산기준": "최근3개월평균(전년동월 데이터 없음)",
        "최근3개월평균": recent_avg,
    }


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
    target_month: str | None = None,
    reference_df: pd.DataFrame | None = None,
    media_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """캠페인별 회귀모델 학습 + 예산 추천 결과.

    method: "target_price"(목표 DB단가를 만족하는 최대 예산) 또는 "inflection"(DB단가 급등 변곡점)
    target_prices: {캠페인명: 목표DB단가}. 미지정 캠페인은 최근 3개월 실제 DB단가를 목표로 사용.
    target_month: 예측 대상월("YYYY-MM"). 캠페인별로 자동 감지된 성수기(집행 기준) 여부 판단에 사용.
    성수기는 캠페인마다 실제 광고비 패턴에서 자동 감지하며(detect_peak_months), 캠페인마다 다를 수 있다.
    reference_df: "참고예산"(화면 표시용 전년동월 비교치) 계산에 쓸 데이터. 미지정 시 df를 그대로 사용.
    회귀는 유료매체 전용 확장 데이터(df)로 하되, 참고예산은 실제 총광고비 공식 데이터(reference_df)로
    보여주고 싶을 때 서로 다른 데이터를 넘길 수 있다.
    media_df: "효율좋은월" 판단에 쓸 매체별 원본 데이터. 주어지면 캠페인별 핵심 채널
    (EFFICIENCY_KEY_CHANNELS)의 실적만으로 효율 우수월을 판단하고, 없으면 df 전체 평균으로 판단한다.
    """
    target_prices = target_prices or {}
    reference_source = reference_df if reference_df is not None else df

    rows = []
    for campaign in sorted(df["캠페인구분"].unique()):
        camp_df = df[df["캠페인구분"] == campaign]
        model_info = fit_campaign_model(camp_df)
        peak_months = model_info["peak_months"]
        is_peak_target = 1.0 if (target_month and int(target_month.split("-")[1]) in peak_months) else 0.0

        ref_camp_df = reference_source[reference_source["캠페인구분"] == campaign]
        reference = get_reference_budget(ref_camp_df if not ref_camp_df.empty else camp_df, target_month)

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
                recommended_budget = reference["참고예산"]
                notes.append("목표 DB단가를 만족하는 예산 구간을 찾지 못해 참고예산 유지")
        note = "; ".join(notes)

        expected_db = float(predict_db_count(model_info, recommended_budget, is_peak_target)[0])
        expected_price = float(predict_db_price(model_info, recommended_budget, is_peak_target)[0])

        rows.append({
            "캠페인구분": campaign,
            "참고예산": reference["참고예산"],
            "참고예산기준": reference["참고예산기준"],
            "최근3개월평균": reference["최근3개월평균"],
            "추천예산": recommended_budget,
            "예상DB수": expected_db,
            "예상DB단가": expected_price,
            "모델신뢰도(R2)": model_info["loocv_r2"],
            "모델차수": model_info["degree"],
            "성수기월": sorted(peak_months),
            "효율좋은월": sorted(_campaign_efficiency_months(camp_df, campaign, media_df)),
            "비고": note,
        })

    return pd.DataFrame(rows)


def _month_to_index(month: str) -> int:
    """'YYYY-MM' 문자열을 연속된 정수로 변환(추세 회귀의 시간축)."""
    year, mon = int(month[:4]), int(month[5:7])
    return year * 12 + mon


def fit_organic_trend(organic_monthly: pd.DataFrame, campaign: str) -> dict | None:
    """자연유입/브랜드 채널 DB수를 월별 추세(로그선형회귀)로 학습.

    이 채널들은 광고비를 늘린다고 DB수가 늘지 않고 연도별 수요·브랜드 쿼리 추세를 따라가므로,
    광고비→DB수 회귀와는 별도로 시간축(월 인덱스 + 성수기 더미)만으로 예측한다.
    데이터가 3개월 미만이면 추세를 학습할 수 없어 None을 반환한다.
    """
    camp_df = organic_monthly[organic_monthly["캠페인구분"] == campaign].sort_values("월")
    if len(camp_df) < 3:
        return None

    peak_months = detect_peak_months(camp_df, metric="DB수")
    month_index = camp_df["월"].apply(_month_to_index).to_numpy(dtype=float)
    is_peak = _is_peak(camp_df["월"], peak_months)
    log_db = np.log1p(camp_df["DB수"].to_numpy(dtype=float))

    X = np.column_stack([month_index, is_peak])
    model = LinearRegression()
    model.fit(X, log_db)

    return {"model": model, "r2": model.score(X, log_db), "n_obs": len(camp_df), "peak_months": peak_months}


def predict_organic_db(trend_info: dict | None, target_month: str) -> float:
    """자연유입 채널의 target_month DB수 예측치. 추세 학습 실패/데이터 부족 시 0."""
    if trend_info is None:
        return 0.0
    month_index = _month_to_index(target_month)
    peak_months = trend_info.get("peak_months", PEAK_MONTHS)
    is_peak = 1.0 if int(target_month.split("-")[1]) in peak_months else 0.0
    X = np.array([[month_index, is_peak]], dtype=float)
    log_pred = trend_info["model"].predict(X)[0]
    return max(0.0, float(np.expm1(log_pred)))


@st.cache_data(show_spinner="회귀 모델 학습 및 예산 추천 계산 중...")
def cached_budget_recommendations(
    df: pd.DataFrame,
    method: str = "target_price",
    target_prices: dict | None = None,
    target_month: str | None = None,
) -> pd.DataFrame:
    return build_budget_recommendations(df, method, target_prices, target_month)
