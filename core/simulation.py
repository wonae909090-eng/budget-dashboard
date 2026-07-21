"""예산 시나리오 시뮬레이션: 보수 / 중립 / 적극."""

from __future__ import annotations

import pandas as pd

from core.budget_model import (
    build_budget_recommendations,
    fit_campaign_model,
    fit_organic_trend,
    get_reference_budget,
    max_grid_budget,
    min_budget_for_db_count,
    predict_db_count,
    predict_db_price,
    predict_organic_db,
    reference_db_price,
)
from core.daily_media_data import build_organic_monthly, build_paid_monthly, estimate_fixed_cost

CONSERVATIVE_BAND = 0.10
AGGRESSIVE_CONCENTRATION = 2.0
LOW_CONFIDENCE_R2_THRESHOLD = 0.5

# 최소 DB목표(floor)를 강제 적용할 시나리오. 적극 시나리오는 효율 극대화가 목적이므로
# 최소 집행비용만 강제하고, 최소 DB목표는 미달 시 경고만 표시한다 (강제하면 취지가 훼손됨).
SCENARIO_ENFORCE_DB_FLOOR = {"보수": True, "중립": True, "적극": False}


def conservative_allocation(base_rec: pd.DataFrame, reference_map: dict, band: float = CONSERVATIVE_BAND) -> dict:
    """참고예산(유료매체 기준) 대비 ±band 이내에서, 회귀 추천예산 방향으로 소폭 조정.

    reference_map은 "추천예산"과 동일한 기준(유료매체 전용)으로 계산된 값이어야 한다.
    화면 표시용 base_rec["참고예산"]은 총광고비(전체) 기준이라 여기 쓰면 기준이 어긋난다.
    """
    budgets = {}
    for _, row in base_rec.iterrows():
        campaign = row["캠페인구분"]
        current = reference_map[campaign]
        recommended = row["추천예산"]
        delta = recommended - current
        capped_delta = max(-current * band, min(current * band, delta))
        budgets[campaign] = current + capped_delta
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

    df는 base_rec["예상DB단가"]와 동일한 기준(회귀 학습에 쓴 데이터)이어야 한다.
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


def apply_fixed_budgets(
    desired: dict, fixed_budgets: dict, total_target: float
) -> tuple[dict, dict, float, list[str]]:
    """캠페인별 고정 총예산(fixed_budgets)을 먼저 배정하고, 나머지 캠페인·예산을 반환.

    고정값 합계가 total_target을 넘으면 총예산을 절대 넘지 않도록 고정값 전체를 비례 축소한다
    (이 경우 미고정 캠페인에게 남는 예산은 0이 됨).
    """
    warnings: list[str] = []
    fixed = {c: v for c, v in fixed_budgets.items() if c in desired and v}
    fixed_sum = sum(fixed.values())

    unfixed_desired = {c: v for c, v in desired.items() if c not in fixed}

    if fixed_sum > total_target:
        scale = (total_target / fixed_sum) if fixed_sum > 0 else 0.0
        warnings.append(
            f"캠페인별 고정 총예산 합계({fixed_sum:,.0f}원)가 총예산({total_target:,.0f}원)을 초과해, "
            f"총예산을 넘지 않도록 고정 총예산을 비례 축소했습니다(축소율 {scale * 100:.0f}%). "
            "미고정 캠페인에는 남는 예산이 없어 0원이 배정됩니다."
        )
        return {c: v * scale for c, v in fixed.items()}, unfixed_desired, 0.0, warnings

    remaining_total = total_target - fixed_sum
    return dict(fixed), unfixed_desired, remaining_total, warnings


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
    fixed_budgets: dict | None = None,
    media_df: pd.DataFrame | None = None,
    fixed_cost_df: pd.DataFrame | None = None,
    organic_db_overrides: dict | None = None,
    fixed_cost_overrides: dict | None = None,
) -> dict:
    """보수/중립/적극 3개 시나리오를 계산해 결과 dict로 반환.

    - media_df가 주어지면 자연유입/브랜드 채널(네이버BS 등)을 제외한 유료 확장형 매체만 모아
      회귀 학습 데이터로 쓴다 (30개월치, 월별 데이터 17개월보다 표본이 많아 더 정확함).
      미지정 시 기존처럼 월별 데이터(df)로 회귀한다 (하위 호환).
    - 자연유입 채널은 광고비와 무관하게 연도별 추세를 따라가므로 별도 추세 모델로 예측해서
      "예상DB수"에 더한다. organic_db_overrides로 캠페인별 예측치를 직접 지정할 수도 있다
      (담당자가 아는 정보로 트렌드 예측을 보정하고 싶을 때).
    - fixed_cost_df가 주어지면 제작비 등 고정비용을 캠페인별로 추정해 "시나리오예산"(화면 표시용
      총예산)에 더한다. 유료매체 예산 배분 로직 자체는 고정비용과 무관하게 유료매체 풀만 갖고 계산한다.
      fixed_cost_overrides로 캠페인별 값을 직접 지정할 수도 있다.
    - overall_total_budget/fixed_budgets/min_budgets는 모두 "유료매체 예산" 기준이다(고정비용 제외).
    - overall_total_budget이 주어지면 각 시나리오의 배분 '비율'은 유지한 채 총액을 이 값에 맞춘다.
    - fixed_budgets는 캠페인별로 "정확히 이 금액을 배정"하는 고정값이다. 고정된 캠페인은 시나리오
      배분 로직을 거치지 않고 그 값을 그대로 쓰며, 남은 예산만 미고정 캠페인들에게 기존 로직으로 나눈다.
    - min_budgets/min_db_counts는 캠페인별 최소 보장값(floor, 미고정 캠페인에만 적용). 보수·중립
      시나리오는 최소 집행비용과 최소 DB목표를 모두 강제하고, 적극 시나리오는 최소 집행비용만
      강제하고 최소 DB목표는 미달 시 경고만 표시한다(효율 극대화 취지 유지).
    """
    model_df = build_paid_monthly(media_df) if media_df is not None else df
    organic_monthly = build_organic_monthly(media_df) if media_df is not None else None

    base_rec = build_budget_recommendations(
        model_df, method="target_price", target_prices=target_prices, target_month=target_month,
        reference_df=df, media_df=media_df,
    )
    reference_map = base_rec.set_index("캠페인구분")["참고예산"]  # 화면 표시용(전체 총광고비 기준)
    recent_avg_map = base_rec.set_index("캠페인구분")["최근3개월평균"]  # 화면 표시용 보조 참고치

    min_budgets = min_budgets or {}
    min_db_counts = min_db_counts or {}
    fixed_budgets = fixed_budgets or {}
    organic_db_overrides = organic_db_overrides or {}
    fixed_cost_overrides = fixed_cost_overrides or {}

    campaigns = base_rec["캠페인구분"].tolist()
    models = {c: fit_campaign_model(model_df[model_df["캠페인구분"] == c]) for c in campaigns}

    is_peak_map = {
        c: (1.0 if target_month and int(target_month.split("-")[1]) in models[c]["peak_months"] else 0.0)
        for c in campaigns
    }

    # 보수 시나리오의 ±10% 앵커는 "추천예산"과 같은 기준(유료매체)이어야 함 — 참고예산(전체)과 다름
    paid_reference_map = {
        c: get_reference_budget(model_df[model_df["캠페인구분"] == c], target_month)["참고예산"]
        for c in campaigns
    }

    organic_db_map = {}
    for c in campaigns:
        if organic_db_overrides.get(c) is not None:
            organic_db_map[c] = float(organic_db_overrides[c])
        elif organic_monthly is not None and target_month:
            trend = fit_organic_trend(organic_monthly, c)
            organic_db_map[c] = predict_organic_db(trend, target_month)
        else:
            organic_db_map[c] = 0.0

    fixed_cost_map = {}
    for c in campaigns:
        if fixed_cost_overrides.get(c) is not None:
            fixed_cost_map[c] = float(fixed_cost_overrides[c])
        elif fixed_cost_df is not None:
            fixed_cost_map[c] = estimate_fixed_cost(fixed_cost_df, c)
        else:
            fixed_cost_map[c] = 0.0

    scenario_desired = {
        "보수": conservative_allocation(base_rec, paid_reference_map),
        "중립": neutral_allocation(base_rec, target_db_counts),
        "적극": aggressive_allocation(base_rec, model_df, target_prices),
    }

    scenarios = {}
    for name, desired in scenario_desired.items():
        enforce_db_floor = SCENARIO_ENFORCE_DB_FLOOR[name]
        natural_total = sum(desired.values())
        total_target = overall_total_budget or natural_total

        warnings: list[str] = []

        fixed_final, unfixed_desired, remaining_total, fixed_warnings = apply_fixed_budgets(
            desired, fixed_budgets, total_target
        )
        warnings.extend(fixed_warnings)

        floors = {}
        for campaign in unfixed_desired:
            camp_df = model_df[model_df["캠페인구분"] == campaign]
            floor = float(min_budgets.get(campaign) or 0)
            if enforce_db_floor and min_db_counts.get(campaign):
                needed = min_budget_for_db_count(
                    models[campaign], camp_df, min_db_counts[campaign], is_peak_map[campaign]
                )
                if needed is None:
                    needed = max_grid_budget(camp_df)
                    warnings.append(
                        f"{campaign}: 회귀모델 추정 범위 내에서 최소 DB목표"
                        f"({min_db_counts[campaign]:,.0f}건)를 만족하는 예산을 찾지 못해 "
                        "추정 가능한 최대 예산을 기준으로 사용했습니다."
                    )
                floor = max(floor, needed)
            floors[campaign] = floor

        floor_final, floor_warnings = apply_floor_constraints(unfixed_desired, floors, remaining_total)
        warnings.extend(floor_warnings)
        final_budgets_paid = {**fixed_final, **floor_final}

        if not enforce_db_floor:
            for campaign in desired:
                target_db = min_db_counts.get(campaign)
                if target_db:
                    predicted = float(
                        predict_db_count(models[campaign], final_budgets_paid[campaign], is_peak_map[campaign])[0]
                    )
                    if predicted < target_db:
                        warnings.append(
                            f"{campaign}: 최소 DB목표({target_db:,.0f}건) 미달 예상"
                            f"({predicted:,.0f}건) — 적극 시나리오는 효율을 우선하므로 강제 적용하지 않았습니다."
                        )

        rows = []
        for campaign, paid_budget in final_budgets_paid.items():
            model_info = models[campaign]
            paid_db = float(predict_db_count(model_info, paid_budget, is_peak_map[campaign])[0])
            organic_db = organic_db_map[campaign]
            fixed_cost = fixed_cost_map[campaign]
            total_db = paid_db + organic_db
            total_budget = paid_budget + fixed_cost
            avg_price = total_budget / total_db if total_db else float("nan")

            rows.append({
                "캠페인구분": campaign,
                "참고예산": reference_map[campaign],
                "최근3개월평균": recent_avg_map[campaign],
                "시나리오예산": total_budget,
                "유료매체예산": paid_budget,
                "고정비용": fixed_cost,
                "예상DB수": total_db,
                "유료매체예상DB수": paid_db,
                "자연유입예상DB수": organic_db,
                "예상DB단가": avg_price,
                "모델신뢰도(R2)": model_info["loocv_r2"],
            })
        table = pd.DataFrame(rows)

        total_budget_sum = table["시나리오예산"].sum()
        total_db_sum = table["예상DB수"].sum()
        avg_price_sum = total_budget_sum / total_db_sum if total_db_sum else float("nan")

        summary = {
            "총예산": total_budget_sum,
            "예상총DB수": total_db_sum,
            "예상평균DB단가": avg_price_sum,
        }
        if overall_target_db_count:
            summary["목표DB수달성률"] = total_db_sum / overall_target_db_count
        if overall_target_db_price:
            summary["목표DB단가달성률"] = overall_target_db_price / avg_price_sum

        scenarios[name] = {"table": table, "summary": summary, "warnings": warnings}

    low_confidence = base_rec.loc[
        base_rec["모델신뢰도(R2)"] < LOW_CONFIDENCE_R2_THRESHOLD, "캠페인구분"
    ].tolist()

    return {
        "base_recommendation": base_rec,
        "scenarios": scenarios,
        "low_confidence_campaigns": low_confidence,
    }
