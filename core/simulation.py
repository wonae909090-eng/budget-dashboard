"""예산 시나리오 시뮬레이션: 보수 / 중립 / 적극."""

from __future__ import annotations

import pandas as pd

from core.budget_model import (
    PEAK_MONTHS,
    build_budget_recommendations,
    fit_campaign_model,
    max_grid_budget,
    min_budget_for_db_count,
    predict_db_count,
    predict_db_price,
    reference_db_price,
)

CONSERVATIVE_BAND = 0.10
AGGRESSIVE_CONCENTRATION = 2.0
LOW_CONFIDENCE_R2_THRESHOLD = 0.5

# 최소 DB목표(floor)를 강제 적용할 시나리오. 적극 시나리오는 효율 극대화가 목적이므로
# 최소 집행비용만 강제하고, 최소 DB목표는 미달 시 경고만 표시한다 (강제하면 취지가 훼손됨).
SCENARIO_ENFORCE_DB_FLOOR = {"보수": True, "중립": True, "적극": False}


def _target_is_peak(target_month: str | None) -> float:
    if not target_month:
        return 0.0
    month_num = int(target_month.split("-")[1])
    return 1.0 if month_num in PEAK_MONTHS else 0.0


def conservative_allocation(base_rec: pd.DataFrame, band: float = CONSERVATIVE_BAND) -> dict:
    """현재예산 대비 ±band 이내에서, 회귀 추천예산 방향으로 소폭 조정."""
    budgets = {}
    for _, row in base_rec.iterrows():
        current = row["현재예산"]
        recommended = row["추천예산"]
        delta = recommended - current
        capped_delta = max(-current * band, min(current * band, delta))
        budgets[row["캠페인구분"]] = current + capped_delta
    return budgets


def neutral_allocation(base_rec: pd.DataFrame, target_db_counts: dict | None = None) -> dict:
    """회귀 추천예산 총합을, 목표 DB수(없으면 모델 예상DB수) 비중으로 재배분."""
    total_pool = base_rec["추천예산"].sum()
    target_db_counts = target_db_counts or {}

    weights = {}
    for _, row in base_rec.iterrows():
        campaign = row["캠페인구분"]
        weights[campaign] = target_db_counts.get(campaign) or row["예상DB수"]

    weight_sum = sum(weights.values())
    return {c: total_pool * (w / weight_sum) for c, w in weights.items()}


def aggressive_allocation(
    base_rec: pd.DataFrame,
    df: pd.DataFrame,
    target_prices: dict | None = None,
    concentration: float = AGGRESSIVE_CONCENTRATION,
) -> dict:
    """회귀 추천예산 총합을, 캠페인별 '자기 기준' 효율(낮을수록 우수)의 거듭제곱 가중치로 집중 배분.

    키즈/초등/중학은 시장 특성상 DB단가 절대 수준 자체가 다르므로, 절대값으로 비교하면
    원래 단가가 높은 캠페인이 항상 "비효율적"으로 나오는 왜곡이 생긴다. 이를 방지하기 위해
    효율 = 캠페인 자신의 기준 DB단가(목표DB단가, 없으면 최근 12개월 가중평균) / 예상DB단가
    로 계산한다. 1.0보다 크면 자기 기준보다 잘하고 있다는 뜻.
    """
    target_prices = target_prices or {}
    total_pool = base_rec["추천예산"].sum()

    weights = {}
    for _, row in base_rec.iterrows():
        campaign = row["캠페인구분"]
        camp_df = df[df["캠페인구분"] == campaign]
        ref_price = reference_db_price(camp_df, target_prices.get(campaign))
        efficiency = ref_price / row["예상DB단가"]
        weights[campaign] = efficiency ** concentration

    weight_sum = sum(weights.values())
    return {c: total_pool * (w / weight_sum) for c, w in weights.items()}


def apply_floor_constraints(desired: dict, floors: dict, total_target: float) -> tuple[dict, list[str]]:
    """floors(캠페인별 최소 보장 예산)를 지키면서 desired 비중으로 나머지를 배분.

    floors 합계가 total_target을 넘으면 총예산을 절대 넘지 않도록 floors 전체를 비례 축소한다.
    """
    warnings: list[str] = []
    floor_sum = sum(floors.values())

    if floor_sum > total_target:
        scale = (total_target / floor_sum) if floor_sum > 0 else 0.0
        warnings.append(
            f"캠페인별 최소값 합계({floor_sum:,.0f}원)가 총예산({total_target:,.0f}원)을 초과해, "
            f"총예산을 넘지 않도록 최소값을 비례 축소했습니다(축소율 {scale * 100:.0f}%)."
        )
        return {c: floors[c] * scale for c in desired}, warnings

    remainder = total_target - floor_sum
    weight_sum = sum(desired.values())
    if weight_sum > 0:
        shares = {c: desired[c] / weight_sum for c in desired}
    else:
        shares = {c: 1.0 / len(desired) for c in desired}

    final = {c: floors[c] + remainder * shares[c] for c in desired}
    return final, warnings


def run_simulation(
    df: pd.DataFrame,
    target_month: str | None = None,
    target_prices: dict | None = None,
    target_db_counts: dict | None = None,
    overall_target_db_count: float | None = None,
    overall_target_db_price: float | None = None,
    overall_total_budget: float | None = None,
    min_budgets: dict | None = None,
    min_db_counts: dict | None = None,
) -> dict:
    """보수/중립/적극 3개 시나리오를 계산해 결과 dict로 반환.

    - overall_total_budget이 주어지면 각 시나리오의 배분 '비율'은 유지한 채 총액을 이 값에 맞춘다.
      (미지정 시 각 시나리오 고유의 자연스러운 총액을 그대로 사용)
    - min_budgets/min_db_counts는 캠페인별 최소 보장값(floor). 보수·중립 시나리오는 최소
      집행비용과 최소 DB목표를 모두 강제하고, 적극 시나리오는 최소 집행비용만 강제하고
      최소 DB목표는 미달 시 경고만 표시한다(효율 극대화 취지 유지).
    - floor 합계가 총예산을 넘으면, 총예산을 넘지 않도록 floor 전체를 비례 축소한다.
    """
    base_rec = build_budget_recommendations(
        df, method="target_price", target_prices=target_prices, target_month=target_month
    )
    current_map = base_rec.set_index("캠페인구분")["현재예산"]
    is_peak = _target_is_peak(target_month)
    min_budgets = min_budgets or {}
    min_db_counts = min_db_counts or {}

    models = {c: fit_campaign_model(df[df["캠페인구분"] == c]) for c in base_rec["캠페인구분"]}

    scenario_desired = {
        "보수": conservative_allocation(base_rec),
        "중립": neutral_allocation(base_rec, target_db_counts),
        "적극": aggressive_allocation(base_rec, df, target_prices),
    }

    scenarios = {}
    for name, desired in scenario_desired.items():
        enforce_db_floor = SCENARIO_ENFORCE_DB_FLOOR[name]
        natural_total = sum(desired.values())
        total_target = overall_total_budget or natural_total

        warnings: list[str] = []
        floors = {}
        for campaign in desired:
            camp_df = df[df["캠페인구분"] == campaign]
            floor = float(min_budgets.get(campaign) or 0)
            if enforce_db_floor and min_db_counts.get(campaign):
                needed = min_budget_for_db_count(models[campaign], camp_df, min_db_counts[campaign], is_peak)
                if needed is None:
                    needed = max_grid_budget(camp_df)
                    warnings.append(
                        f"{campaign}: 회귀모델 추정 범위 내에서 최소 DB목표"
                        f"({min_db_counts[campaign]:,.0f}건)를 만족하는 예산을 찾지 못해 "
                        "추정 가능한 최대 예산을 기준으로 사용했습니다."
                    )
                floor = max(floor, needed)
            floors[campaign] = floor

        final_budgets, floor_warnings = apply_floor_constraints(desired, floors, total_target)
        warnings.extend(floor_warnings)

        if not enforce_db_floor:
            for campaign in desired:
                target_db = min_db_counts.get(campaign)
                if target_db:
                    predicted = float(predict_db_count(models[campaign], final_budgets[campaign], is_peak)[0])
                    if predicted < target_db:
                        warnings.append(
                            f"{campaign}: 최소 DB목표({target_db:,.0f}건) 미달 예상"
                            f"({predicted:,.0f}건) — 적극 시나리오는 효율을 우선하므로 강제 적용하지 않았습니다."
                        )

        rows = []
        for campaign, budget in final_budgets.items():
            model_info = models[campaign]
            expected_db = float(predict_db_count(model_info, budget, is_peak)[0])
            expected_price = float(predict_db_price(model_info, budget, is_peak)[0])
            rows.append({
                "캠페인구분": campaign,
                "현재예산": current_map[campaign],
                "시나리오예산": budget,
                "예상DB수": expected_db,
                "예상DB단가": expected_price,
                "모델신뢰도(R2)": model_info["loocv_r2"],
            })
        table = pd.DataFrame(rows)

        total_budget = table["시나리오예산"].sum()
        total_db = table["예상DB수"].sum()
        avg_price = total_budget / total_db if total_db else float("nan")

        summary = {
            "총예산": total_budget,
            "예상총DB수": total_db,
            "예상평균DB단가": avg_price,
        }
        if overall_target_db_count:
            summary["목표DB수달성률"] = total_db / overall_target_db_count
        if overall_target_db_price:
            summary["목표DB단가달성률"] = overall_target_db_price / avg_price

        scenarios[name] = {"table": table, "summary": summary, "warnings": warnings}

    low_confidence = base_rec.loc[
        base_rec["모델신뢰도(R2)"] < LOW_CONFIDENCE_R2_THRESHOLD, "캠페인구분"
    ].tolist()

    return {
        "base_recommendation": base_rec,
        "scenarios": scenarios,
        "low_confidence_campaigns": low_confidence,
    }
