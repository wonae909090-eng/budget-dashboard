"""예산 시뮬레이션 페이지."""

import io
import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.ai_insights import explain_simulation  # noqa: E402
from core.budget_model import build_model_report  # noqa: E402
from core.simulation import run_simulation  # noqa: E402
from core.ui import CAMPAIGN_COLORS, campaign_badge, setup_page, style_campaign_rows  # noqa: E402

st.set_page_config(page_title="Budget Simulation", page_icon="💰", layout="wide")
setup_page()
st.title("💰 예산 시뮬레이션")

if "processed_df" not in st.session_state:
    st.warning("⚠️ 'Data upload'에서 데이터를 먼저 업로드해주세요.")
    st.stop()

df = st.session_state["processed_df"]
all_campaigns = sorted(df["캠페인구분"].unique())

st.info(
    "회귀 모델은 17개월치 데이터로 학습되어 **참고용**입니다. "
    "모델 신뢰도(R²)가 낮은 캠페인은 결과 하단에 별도 표시됩니다."
)


def _future_months(last_month: str, n: int = 12) -> list[str]:
    last_year, last_mon = int(last_month[:4]), int(last_month[5:7])
    months = []
    for i in range(1, n + 1):
        total = last_year * 12 + (last_mon - 1) + i
        y, m = divmod(total, 12)
        months.append(f"{y:04d}-{m + 1:02d}")
    return months


# ── 목표 입력 폼 ───────────────────────────────────────
st.subheader("목표 입력")

last_data_month = max(df["월"])
future_month_options = _future_months(last_data_month)
target_month = st.selectbox(
    f"예측 대상월 (업로드된 데이터의 마지막 월: {last_data_month} 이후, 계절성 반영: 1·2·7·8월=성수기)",
    future_month_options,
    index=0,
)

allocation_mode = st.radio("목표 입력 방식", ["캠페인별 개별 입력", "전체 목표 자동 분배"], horizontal=True)

target_db_counts: dict = {}
target_prices: dict = {}
overall_target_db_count = None
overall_target_db_price = None

if allocation_mode == "캠페인별 개별 입력":
    cols = st.columns(len(all_campaigns))
    for col, campaign in zip(cols, all_campaigns):
        with col:
            campaign_badge(campaign)
            db_count = st.number_input(f"{campaign} 목표 DB수", min_value=0, value=0, key=f"sim_db_{campaign}")
            db_price = st.number_input(f"{campaign} 목표 DB단가(원)", min_value=0, value=0, key=f"sim_price_{campaign}")
            if db_count:
                target_db_counts[campaign] = db_count
            if db_price:
                target_prices[campaign] = db_price
else:
    c1, c2 = st.columns(2)
    with c1:
        overall_target_db_count = st.number_input("전체 목표 DB수", min_value=0, value=0)
    with c2:
        overall_target_db_price = st.number_input("전체 목표 DB단가(원)", min_value=0, value=0)

    if overall_target_db_count:
        recent_db_share = df.groupby("캠페인구분").apply(
            lambda g: g.sort_values("월")["DB수"].tail(3).sum(), include_groups=False
        )
        recent_db_share = recent_db_share / recent_db_share.sum()
        target_db_counts = {c: overall_target_db_count * recent_db_share[c] for c in all_campaigns}
    if overall_target_db_price:
        target_prices = {c: overall_target_db_price for c in all_campaigns}

st.subheader("총예산 설정 (선택)")
st.caption("0이면 시나리오별로 회귀모델이 추천하는 자연스러운 총액을 그대로 사용합니다. 값을 입력하면 각 시나리오의 배분 비율은 유지한 채 총액을 이 값에 맞춥니다.")
overall_total_budget = st.number_input("전체 목표 총예산(원)", min_value=0, value=0, step=10_000_000)

st.caption("캠페인별로 '이 금액을 정확히 배정'하고 싶다면 아래에 입력하세요. 입력한 캠페인은 모든 시나리오에서 그 금액 그대로 고정되고, 나머지 예산만 다른 캠페인들에게 배분됩니다.")
fixed_budgets: dict = {}
fixed_cols = st.columns(len(all_campaigns))
for col, campaign in zip(fixed_cols, all_campaigns):
    with col:
        campaign_badge(campaign)
        fb = st.number_input(f"{campaign} 총예산(원)", min_value=0, value=0, step=10_000_000, key=f"fixed_budget_{campaign}")
        if fb:
            fixed_budgets[campaign] = fb

st.subheader("캠페인별 최소 보장 조건 (선택)")
st.caption(
    "각 캠페인에 최소한 배정해야 하는 집행비용과, 최소한 확보해야 하는 DB수입니다(위에서 총예산을 고정한 캠페인에는 적용되지 않습니다). "
    "보수·중립 시나리오는 두 조건을 모두 반영하고, 적극 시나리오는 효율 극대화 취지를 지키기 위해 "
    "최소 집행비용만 반영하며 최소 DB목표는 미달 시 경고로만 표시합니다. "
    "최소값 합계가 남은 예산을 넘으면 그 예산을 넘지 않도록 최소값을 비례 축소합니다."
)
min_budgets: dict = {}
min_db_counts: dict = {}
min_cols = st.columns(len(all_campaigns))
for col, campaign in zip(min_cols, all_campaigns):
    with col:
        campaign_badge(campaign)
        mb = st.number_input(f"{campaign} 최소 집행비용(원)", min_value=0, value=0, key=f"min_budget_{campaign}")
        mdb = st.number_input(f"{campaign} 최소 DB목표(건)", min_value=0, value=0, key=f"min_db_{campaign}")
        if mb:
            min_budgets[campaign] = mb
        if mdb:
            min_db_counts[campaign] = mdb

run_clicked = st.button("🚀 예산 시뮬레이션 실행", type="primary")

if run_clicked:
    st.session_state["budget_simulation"] = run_simulation(
        df,
        target_month=target_month,
        target_prices=target_prices or None,
        target_db_counts=target_db_counts or None,
        overall_target_db_count=overall_target_db_count or None,
        overall_target_db_price=overall_target_db_price or None,
        overall_total_budget=overall_total_budget or None,
        min_budgets=min_budgets or None,
        min_db_counts=min_db_counts or None,
        fixed_budgets=fixed_budgets or None,
    )

if "budget_simulation" not in st.session_state:
    st.info("목표를 입력하고 '예산 시뮬레이션 실행'을 클릭해주세요. (목표 미입력 시에도 기본값으로 실행 가능)")
    st.stop()

sim = st.session_state["budget_simulation"]

st.subheader("예산 시뮬레이션 결과")

SCENARIO_DESC = {
    "보수": "현재 예산(최근 3개월 평균) 대비 ±10% 이내에서 회귀 추천예산 방향으로 소폭 조정",
    "중립": "회귀모델 추천 예산 총합을 목표 DB수 비중으로 재배분",
    "적극": "회귀모델 추천 예산 총합을 DB단가 효율이 좋은 캠페인에 집중 배분",
}

tabs = st.tabs(["보수", "중립", "적극"])
for tab, name in zip(tabs, ["보수", "중립", "적극"]):
    with tab:
        st.caption(SCENARIO_DESC[name])
        scenario = sim["scenarios"][name]
        table = scenario["table"]
        summary = scenario["summary"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 예산", f"{summary['총예산']:,.0f}원")
        m2.metric("예상 총 DB수", f"{summary['예상총DB수']:,.0f}건")
        m3.metric("예상 평균 DB단가", f"{summary['예상평균DB단가']:,.0f}원")
        if "목표DB수달성률" in summary:
            m4.metric("목표 DB수 달성률", f"{summary['목표DB수달성률']*100:.1f}%")
        elif "목표DB단가달성률" in summary:
            m4.metric("목표 DB단가 달성률", f"{summary['목표DB단가달성률']*100:.1f}%")
        else:
            m4.metric("목표 달성률", "목표 미입력")

        st.markdown("**캠페인별 현재예산 vs 시나리오예산**")
        display_table = table.copy()
        display_table["예상DB단가"] = display_table["예상DB단가"].round(0)
        display_table["모델신뢰도(R2)"] = display_table["모델신뢰도(R2)"].round(3)
        st.dataframe(style_campaign_rows(display_table), width="stretch")

        chart_df = table.melt(
            id_vars="캠페인구분", value_vars=["현재예산", "시나리오예산"], var_name="구분", value_name="예산"
        )
        fig = px.bar(
            chart_df, x="캠페인구분", y="예산", color="캠페인구분", pattern_shape="구분",
            color_discrete_map=CAMPAIGN_COLORS, barmode="group",
            title=f"[{name}] 캠페인별 현재예산 vs 시나리오예산",
        )
        st.plotly_chart(fig, width="stretch")

        for w in scenario["warnings"]:
            st.warning(f"⚠️ {w}")

        if sim["low_confidence_campaigns"]:
            st.warning(
                f"⚠️ 모델 신뢰도(R²)가 낮은 캠페인: {', '.join(sim['low_confidence_campaigns'])} "
                "— 예산 추천값을 참고용으로만 활용하세요."
            )

# ── AI 해석 ────────────────────────────────────────────
st.subheader("🤖 AI 해석 (선택)")
st.caption(
    "회귀 계산 자체는 그대로 두고, 그 결과를 Claude가 문장으로 설명해주는 기능입니다. "
    "숫자는 항상 회귀 모델이 계산한 값 그대로이며, AI는 해석만 덧붙입니다."
)
if st.button("🤖 예산 시뮬레이션 결과 AI로 해석하기"):
    with st.spinner("Claude가 결과를 해석하는 중..."):
        model_report = build_model_report(df)
        explanation = explain_simulation(sim, model_report)
    st.markdown(explanation)

# ── 다운로드 ───────────────────────────────────────────
st.subheader("다운로드")
combined = pd.concat(
    [sim["scenarios"][name]["table"].assign(시나리오=name) for name in ["보수", "중립", "적극"]],
    ignore_index=True,
)

csv_bytes = combined.to_csv(index=False).encode("utf-8-sig")
st.download_button("예산 시뮬레이션 결과 CSV 다운로드", data=csv_bytes, file_name="budget_simulation.csv", mime="text/csv")

excel_buffer = io.BytesIO()
with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
    for name in ["보수", "중립", "적극"]:
        sim["scenarios"][name]["table"].to_excel(writer, sheet_name=name, index=False)
st.download_button(
    "예산 시뮬레이션 결과 엑셀 다운로드",
    data=excel_buffer.getvalue(),
    file_name="budget_simulation.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
