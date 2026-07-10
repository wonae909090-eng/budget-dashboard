"""성과 대시보드 페이지."""

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.budget_model import reference_db_price  # noqa: E402
from core.kpi_aggregation import aggregate_by_campaign_month, build_kpi_summary, METRICS  # noqa: E402
from core.ui import CAMPAIGN_COLORS, setup_page  # noqa: E402

st.set_page_config(page_title="Performance Dashboard", page_icon="📊", layout="wide")
setup_page()
st.title("📊 성과 대시보드")

if "processed_df" not in st.session_state:
    st.warning("⚠️ 'Data upload'에서 데이터를 먼저 업로드해주세요.")
    st.stop()

df = st.session_state["processed_df"]
all_campaigns = sorted(df["캠페인구분"].unique())
all_months = sorted(df["월"].unique())
available_years = sorted({int(m[:4]) for m in all_months})


def _months_in_year(year: int) -> list[int]:
    return sorted(int(m[5:7]) for m in all_months if int(m[:4]) == year)


def _shift_month(month: str, offset: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    total = year * 12 + (mon - 1) + offset
    new_year, new_mon = divmod(total, 12)
    return f"{new_year:04d}-{new_mon + 1:02d}"


# ── 필터 (요약 위에 배치) ─────────────────────────────────
st.subheader("🔎 조회 조건")
filter_col1, filter_col2, filter_col3 = st.columns([1.4, 1, 1])

with filter_col1:
    selected_campaigns = st.multiselect("캠페인구분", all_campaigns, default=all_campaigns)

with filter_col2:
    st.caption("시작월")
    sy_col, sm_col = st.columns(2)
    start_year = sy_col.selectbox("연도", available_years, index=0, key="start_year", label_visibility="collapsed")
    start_month = sm_col.selectbox(
        "월", _months_in_year(start_year), index=0, key="start_month",
        format_func=lambda m: f"{m}월", label_visibility="collapsed",
    )

with filter_col3:
    st.caption("종료월")
    ey_col, em_col = st.columns(2)
    end_year = ey_col.selectbox(
        "연도", available_years, index=len(available_years) - 1, key="end_year", label_visibility="collapsed"
    )
    end_months = _months_in_year(end_year)
    end_month = em_col.selectbox(
        "월", end_months, index=len(end_months) - 1, key="end_month",
        format_func=lambda m: f"{m}월", label_visibility="collapsed",
    )

start_month_str = f"{start_year:04d}-{start_month:02d}"
end_month_str = f"{end_year:04d}-{end_month:02d}"

if not selected_campaigns:
    st.info("캠페인을 하나 이상 선택해주세요.")
    st.stop()

if start_month_str > end_month_str:
    st.error("시작월이 종료월보다 늦을 수 없습니다. 기간을 다시 선택해주세요.")
    st.stop()

st.divider()

filtered_df = df[
    df["캠페인구분"].isin(selected_campaigns) & df["월"].between(start_month_str, end_month_str)
].copy()

kpi = build_kpi_summary(filtered_df, targets=st.session_state.get("targets"))
campaign_monthly = kpi["campaign_monthly"]
overall_monthly = kpi["overall_monthly"]
st.session_state["kpi_summary"] = kpi

# ── 상단 카드 ──────────────────────────────────────────
if set(selected_campaigns) == set(all_campaigns):
    summary_label = "캠페인 전체 요약"
elif len(selected_campaigns) == 1:
    summary_label = f"{selected_campaigns[0]} 캠페인 요약"
else:
    summary_label = ", ".join(selected_campaigns) + " 캠페인 요약"

st.header(summary_label)
if len(overall_monthly) == 0:
    st.info("선택한 조건에 해당하는 데이터가 없습니다.")
    st.stop()

latest = overall_monthly.iloc[-1]

c1, c2, c3, c4 = st.columns(4)
c1.metric("총 광고비", f"{latest['광고비']:,.0f}원", delta=(f"{latest['광고비_MoM']:.1f}%" if pd.notna(latest["광고비_MoM"]) else None))
c2.metric("총 DB수", f"{latest['DB수']:,.0f}건", delta=(f"{latest['DB수_MoM']:.1f}%" if pd.notna(latest["DB수_MoM"]) else None))
c3.metric("평균 DB단가", f"{latest['DB단가']:,.0f}원", delta=(f"{latest['DB단가_MoM']:.1f}%" if pd.notna(latest["DB단가_MoM"]) else None), delta_color="inverse")
c4.metric("평균 입회율", f"{latest['입회율']*100:.1f}%", delta=(f"{latest['입회율_MoM']:.1f}%" if pd.notna(latest["입회율_MoM"]) else None))
st.caption(f"기준월: {latest['월']} (전월 대비 변화율)")

# ── 트렌드 라인 차트 ────────────────────────────────────
st.header("캠페인별 월별 트렌드")
metric_choice = st.selectbox("지표 선택", METRICS, index=2)

plot_df = campaign_monthly.copy()
y_col = metric_choice
if metric_choice == "입회율":
    plot_df[y_col] = plot_df[y_col] * 100

fig_trend = px.line(
    plot_df, x="월", y=y_col, color="캠페인구분", markers=True,
    color_discrete_map=CAMPAIGN_COLORS,
    labels={y_col: metric_choice, "월": "월"},
    title=f"캠페인별 {metric_choice} 트렌드",
)
st.plotly_chart(fig_trend, width='stretch')

# ── 캠페인 간 비교 (월별 비교) ────────────────────────────
st.header("캠페인 간 비교 (월별 비교)")
st.caption("비교할 두 개의 월을 직접 선택할 수 있습니다. 기본값은 최근월과 전년도 동월입니다.")

compare_source_df = df[df["캠페인구분"].isin(selected_campaigns)]
compare_agg = aggregate_by_campaign_month(compare_source_df)
compare_months = sorted(compare_agg["월"].unique())

latest_compare_month = compare_months[-1]
default_prev_month = _shift_month(latest_compare_month, -12)
if default_prev_month not in compare_months:
    default_prev_month = compare_months[0]

cmp_col1, cmp_col2 = st.columns(2)
month_a = cmp_col1.selectbox(
    "비교월 A", compare_months, index=compare_months.index(latest_compare_month), key="cmp_month_a"
)
month_b = cmp_col2.selectbox(
    "비교월 B (기본: 전년 동월)", compare_months, index=compare_months.index(default_prev_month), key="cmp_month_b"
)

cmp_df = compare_agg[compare_agg["월"].isin([month_a, month_b])].copy()
cmp_df["입회율(%)"] = cmp_df["입회율"] * 100

col_a, col_b = st.columns(2)
with col_a:
    fig_price = px.bar(
        cmp_df, x="캠페인구분", y="DB단가", color="캠페인구분", pattern_shape="월",
        color_discrete_map=CAMPAIGN_COLORS, barmode="group", text_auto=".0f",
        title=f"DB단가 비교 ({month_a} vs {month_b})",
    )

    targets_dict = st.session_state.get("targets", {})
    campaign_order = sorted(cmp_df["캠페인구분"].unique())
    for i, campaign in enumerate(campaign_order):
        camp_hist_df = df[df["캠페인구분"] == campaign]
        target_price = (targets_dict.get(campaign) or {}).get("목표DB단가")
        ref_price = reference_db_price(camp_hist_df, target_price)
        fig_price.add_shape(
            type="line", xref="x", yref="y",
            x0=i - 0.4, x1=i + 0.4, y0=ref_price, y1=ref_price,
            line=dict(color="red", dash="dash", width=2),
        )
    fig_price.add_trace(go.Scatter(
        x=[None], y=[None], mode="lines",
        line=dict(color="red", dash="dash"),
        name="기준 DB단가(목표 또는 과거12개월 평균)",
    ))
    st.plotly_chart(fig_price, width='stretch')
    st.caption("점선 = 캠페인별 목표 DB단가(미입력 시 최근 12개월 가중평균 DB단가)")
with col_b:
    fig_rate = px.bar(
        cmp_df, x="캠페인구분", y="입회율(%)", color="캠페인구분", pattern_shape="월",
        color_discrete_map=CAMPAIGN_COLORS, barmode="group", text_auto=".1f",
        title=f"입회율 비교 ({month_a} vs {month_b})",
    )
    st.plotly_chart(fig_rate, width='stretch')

# ── MoM/YoY 증감 테이블 ──────────────────────────────────
st.header("MoM / YoY 증감률")
change_cols = ["캠페인구분", "월"] + [f"{m}_MoM" for m in METRICS] + [f"{m}_YoY" for m in METRICS]
change_df = campaign_monthly[change_cols].copy()


def _color_pos_neg(val):
    if pd.isna(val):
        return ""
    color = "#2e7d32" if val > 0 else ("#c62828" if val < 0 else "")
    return f"color: {color}"


numeric_change_cols = [c for c in change_df.columns if c not in ("캠페인구분", "월")]
styled = change_df.style.map(_color_pos_neg, subset=numeric_change_cols).format(
    {c: "{:.1f}%" for c in numeric_change_cols}, na_rep="-"
)
st.dataframe(styled, width='stretch', height=400)

# ── 목표 대비 달성률 ─────────────────────────────────────
st.header("🎯 목표 대비 달성률")

with st.expander("목표값 입력", expanded=not any(st.session_state.get("targets", {}).values())):
    st.caption("입력한 캠페인만 목표 대비 달성률이 계산됩니다.")
    targets = st.session_state.get("targets", {})
    target_cols = st.columns(len(all_campaigns))
    for col, campaign in zip(target_cols, all_campaigns):
        with col:
            st.markdown(f"**{campaign}**")
            existing = targets.get(campaign) or {}
            db_target = st.number_input(
                f"{campaign} 목표 DB수", min_value=0, value=int(existing.get("목표DB수") or 0), key=f"target_db_{campaign}"
            )
            price_target = st.number_input(
                f"{campaign} 목표 DB단가(원)", min_value=0, value=int(existing.get("목표DB단가") or 0), key=f"target_price_{campaign}"
            )
            budget_target = st.number_input(
                f"{campaign} 월배정예산(원)", min_value=0, value=int(existing.get("월배정예산") or 0), key=f"target_budget_{campaign}"
            )
            if db_target or price_target or budget_target:
                targets[campaign] = {
                    "목표DB수": db_target or None,
                    "목표DB단가": price_target or None,
                    "월배정예산": budget_target or None,
                }
    st.session_state["targets"] = targets

if any(st.session_state.get("targets", {}).values()):
    kpi = build_kpi_summary(filtered_df, targets=st.session_state.get("targets"))
    campaign_monthly = kpi["campaign_monthly"]
    achievement_cols = ["캠페인구분", "월", "DB수_달성률", "DB단가_달성률", "예산_달성률"]
    if set(achievement_cols).issubset(campaign_monthly.columns):
        ach_df = campaign_monthly[achievement_cols].copy()
        for c in ["DB수_달성률", "DB단가_달성률", "예산_달성률"]:
            ach_df[c] = ach_df[c].apply(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "목표 미입력")
        st.dataframe(ach_df, width='stretch')
else:
    st.info("목표값을 입력하면 목표 대비 달성률이 여기에 표시됩니다.")

# ── 데이터 품질 플래그 ───────────────────────────────────
quality_issues = filtered_df[filtered_df["flag_outlier"] | filtered_df["flag_inconsistent"]]
if len(quality_issues) > 0:
    with st.expander(f"⚠️ 데이터 품질 확인 필요 ({len(quality_issues)}건)"):
        st.dataframe(
            quality_issues[["캠페인구분", "월", "flag_outlier", "outlier_reason", "flag_inconsistent", "reason"]],
            width='stretch',
        )
