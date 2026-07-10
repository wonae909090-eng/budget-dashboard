"""자연어 질의 응답 — 1단계 규칙기반(정규식 + 키워드 매칭) 챗봇."""

from __future__ import annotations

import re

import pandas as pd

CAMPAIGN_ALIASES = {
    "키즈": ["키즈", "kids"],
    "초등": ["초등학생", "초등부", "초등"],
    "중학": ["중학생", "중등", "중학"],
}

# 값이 길수록(구체적일수록) 먼저 매칭되도록 아래 순서를 유지
METRIC_ALIASES = {
    "DB단가": ["db단가", "db 단가", "리드단가", "cpl"],
    "입회단가": ["입회단가", "전환단가", "가입단가", "cpa"],
    "입회율": ["입회율", "전환율", "가입율", "가입률"],
    "입회수": ["입회수", "전환수", "가입수", "전환", "가입"],
    "DB수": ["db수", "db 수", "리드수", "리드", "db건수", "db"],
    "광고비": ["광고비", "예산", "비용", "스펜드", "spend"],
}

SCENARIO_KEYWORDS = ["보수", "중립", "적극"]
BUDGET_KEYWORDS = ["추천예산", "추천 예산", "예산추천", "예산 추천", "시나리오"] + SCENARIO_KEYWORDS

RELATIVE_PERIOD_OFFSETS = {
    "이번달": 0, "이번 달": 0, "이달": 0, "최근": 0, "최신": 0, "현재": 0,
    "지난달": -1, "지난 달": -1, "전월": -1, "전 월": -1,
    "전전달": -2, "전전 달": -2, "두달전": -2, "두 달 전": -2, "두달 전": -2,
}


def _find_alias(query: str, alias_map: dict) -> str | None:
    q = query.lower()
    for key, aliases in alias_map.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if alias.lower() in q:
                return key
    return None


def extract_campaign(query: str) -> str | None:
    return _find_alias(query, CAMPAIGN_ALIASES)


def extract_metric(query: str) -> str | None:
    return _find_alias(query, METRIC_ALIASES)


def extract_scenario(query: str) -> str | None:
    for kw in SCENARIO_KEYWORDS:
        if kw in query:
            return kw
    return None


def is_budget_query(query: str) -> bool:
    return any(kw in query for kw in BUDGET_KEYWORDS)


def _shift_month(month: str, offset: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    total = year * 12 + (mon - 1) + offset
    new_year, new_mon = divmod(total, 12)
    return f"{new_year:04d}-{new_mon + 1:02d}"


def extract_period(query: str, latest_month: str) -> str | None:
    """explicit 'YYYY-MM'/'YYYY년 M월', 상대표현('지난달' 등), 'M월'(연도 미지정) 순으로 탐색."""
    m = re.search(r"(20\d{2})[-./년]\s?(\d{1,2})월?", query)
    if m:
        year, mon = int(m.group(1)), int(m.group(2))
        return f"{year:04d}-{mon:02d}"

    for phrase, offset in RELATIVE_PERIOD_OFFSETS.items():
        if phrase in query:
            return _shift_month(latest_month, offset)

    is_last_year = "작년" in query or "전년" in query
    m = re.search(r"(\d{1,2})\s?월", query)
    if m:
        mon = int(m.group(1))
        year = int(latest_month[:4]) - (1 if is_last_year else 0)
        return f"{year:04d}-{mon:02d}"

    if is_last_year:
        return _shift_month(latest_month, -12)

    return None


def _fmt_value(metric: str, value: float) -> str:
    if pd.isna(value):
        return "데이터 없음"
    if metric == "입회율":
        return f"{value * 100:.1f}%"
    if metric in ("DB수", "입회수"):
        return f"{value:,.0f}건"
    return f"{value:,.0f}원"


def _fmt_change(pct: float) -> str:
    if pd.isna(pct):
        return ""
    direction = "증가" if pct > 0 else ("감소" if pct < 0 else "변동 없음")
    return f"{abs(pct):.1f}% {direction}"


def _month_kr(month: str) -> str:
    return f"{month[:4]}년 {int(month[5:7])}월"


def answer_kpi_query(query: str, kpi_summary: dict) -> str | None:
    campaign_monthly = kpi_summary.get("campaign_monthly")
    if campaign_monthly is None or len(campaign_monthly) == 0:
        return None

    campaign = extract_campaign(query)
    metric = extract_metric(query)
    latest_month = campaign_monthly["월"].max()
    month = extract_period(query, latest_month)

    if campaign is None:
        return "어떤 캠페인이 궁금하신가요? (키즈 / 초등 / 중학 중 하나를 포함해서 질문해주세요.)"
    if metric is None:
        return "어떤 지표가 궁금하신가요? (광고비/DB수/DB단가/입회수/입회단가/입회율 중 하나를 포함해서 질문해주세요.)"

    target_month = month or latest_month
    row = campaign_monthly[(campaign_monthly["캠페인구분"] == campaign) & (campaign_monthly["월"] == target_month)]
    if len(row) == 0:
        return f"{campaign} 캠페인의 {_month_kr(target_month)} 데이터를 찾을 수 없습니다."

    row = row.iloc[0]
    value = row[metric]
    mom = row.get(f"{metric}_MoM")
    yoy = row.get(f"{metric}_YoY")

    formatted_value = _fmt_value(metric, value)
    particle = "로" if formatted_value.endswith("%") else "으로"
    sentence = f"{campaign} 캠페인의 {_month_kr(target_month)} {metric}는 {formatted_value}"
    mom_text = _fmt_change(mom)
    if mom_text:
        sentence += f"{particle} 전월 대비 {mom_text}했습니다."
    else:
        sentence += "입니다. (전월 대비 비교 데이터 없음)"

    yoy_text = _fmt_change(yoy)
    if yoy_text:
        sentence += f" 전년 동월 대비로는 {yoy_text}했습니다."

    return sentence


def answer_budget_query(query: str, budget_simulation: dict | None) -> str | None:
    if not budget_simulation:
        return "먼저 'Budget Simulation' 페이지에서 시뮬레이션을 실행해주세요."

    campaign = extract_campaign(query)
    scenario = extract_scenario(query)

    if scenario is None:
        base_rec = budget_simulation.get("base_recommendation")
        if campaign:
            row = base_rec[base_rec["캠페인구분"] == campaign]
            if len(row) == 0:
                return f"{campaign} 캠페인의 추천 예산 정보를 찾을 수 없습니다."
            row = row.iloc[0]
            return (
                f"{campaign} 캠페인의 현재예산은 {row['현재예산']:,.0f}원이며, "
                f"추천예산은 {row['추천예산']:,.0f}원입니다. "
                f"(예상DB수 {row['예상DB수']:,.0f}건, 예상DB단가 {row['예상DB단가']:,.0f}원, "
                f"모델신뢰도 R²={row['모델신뢰도(R2)']:.2f})"
            )
        rows = "; ".join(
            f"{r['캠페인구분']} 추천예산 {r['추천예산']:,.0f}원" for _, r in base_rec.iterrows()
        )
        return f"캠페인별 추천예산: {rows}"

    scenario_data = budget_simulation["scenarios"].get(scenario)
    if scenario_data is None:
        return f"'{scenario}' 시나리오 데이터를 찾을 수 없습니다."

    table = scenario_data["table"]
    summary = scenario_data["summary"]

    if campaign:
        row = table[table["캠페인구분"] == campaign]
        if len(row) == 0:
            return f"{campaign} 캠페인의 '{scenario}' 시나리오 데이터를 찾을 수 없습니다."
        row = row.iloc[0]
        return (
            f"'{scenario}' 시나리오 기준 {campaign} 캠페인의 예산은 {row['시나리오예산']:,.0f}원, "
            f"예상DB수 {row['예상DB수']:,.0f}건, 예상DB단가 {row['예상DB단가']:,.0f}원입니다."
        )

    return (
        f"'{scenario}' 시나리오 전체 결과 — 총예산 {summary['총예산']:,.0f}원, "
        f"예상총DB수 {summary['예상총DB수']:,.0f}건, 예상평균DB단가 {summary['예상평균DB단가']:,.0f}원입니다."
    )


FALLBACK_MESSAGE = (
    "질문을 이해하지 못했습니다. 예시: '중학 캠페인 지난달 DB단가 알려줘', "
    "'키즈 캠페인 추천예산 알려줘', '적극 시나리오 초등 캠페인 예산은?'"
)


def answer(
    query: str,
    kpi_summary: dict | None,
    budget_simulation: dict | None,
) -> str:
    """질의를 분류해 KPI 조회 또는 예산 시뮬레이션 조회로 라우팅."""
    if not query or not query.strip():
        return FALLBACK_MESSAGE

    if is_budget_query(query):
        result = answer_budget_query(query, budget_simulation)
    elif kpi_summary:
        result = answer_kpi_query(query, kpi_summary)
    else:
        result = None

    if result is None:
        if kpi_summary is None and not is_budget_query(query):
            return "먼저 'Performance Dashboard' 페이지를 방문해 데이터를 집계해주세요."
        return FALLBACK_MESSAGE

    return result
