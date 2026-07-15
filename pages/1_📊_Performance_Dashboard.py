"""성과 대시보드 페이지."""

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.budget_model import reference_db_price  # noqa: E402
from core.daily_media_data import load_daily_data, load_media_data  # noqa: E402
from core.kpi_aggregation import aggregate_by_campaign_month, build_kpi_summary, METRICS  # noqa: E402
from core.ui import CAMPAIGN_COLORS, setup_page, style_campaign_rows  # noqa: E402

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


tab_summary, tab_daily, tab_media = st.tabs(["📊 캠페인 실적 요약", "📈 일자별 성과 추이", "📡 주요 매체별 성과"])

with tab_summary:
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


    def _render_compare_chart(metric: str) -> None:
        plot_df = cmp_df.copy()
        y_col = metric
        if metric == "입회율":
            y_col = "입회율(%)"
            plot_df[y_col] = plot_df["입회율"] * 100

        fig = px.bar(
            plot_df, x="캠페인구분", y=y_col, color="캠페인구분", pattern_shape="월",
            color_discrete_map=CAMPAIGN_COLORS, barmode="group",
            text_auto=".1f" if metric == "입회율" else ".0f",
            title=f"{metric} 비교 ({month_a} vs {month_b})",
        )

        if metric == "DB단가":
            targets_dict = st.session_state.get("targets", {})
            campaign_order = sorted(plot_df["캠페인구분"].unique())
            for i, campaign in enumerate(campaign_order):
                camp_hist_df = df[df["캠페인구분"] == campaign]
                target_price = (targets_dict.get(campaign) or {}).get("목표DB단가")
                ref_price = reference_db_price(camp_hist_df, target_price)
                fig.add_shape(
                    type="line", xref="x", yref="y",
                    x0=i - 0.4, x1=i + 0.4, y0=ref_price, y1=ref_price,
                    line=dict(color="red", dash="dash", width=2),
                )
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="lines",
                line=dict(color="red", dash="dash"),
                name="기준 DB단가(목표 또는 과거12개월 평균)",
            ))

        st.plotly_chart(fig, width='stretch')
        if metric == "DB단가":
            st.caption("점선 = 캠페인별 목표 DB단가(미입력 시 최근 12개월 가중평균 DB단가)")


    col_a, col_b = st.columns(2)
    with col_a:
        metric_left = st.selectbox("좌측 비교 지표", METRICS, index=METRICS.index("DB단가"), key="cmp_metric_left")
        _render_compare_chart(metric_left)
    with col_b:
        metric_right = st.selectbox("우측 비교 지표", METRICS, index=METRICS.index("입회율"), key="cmp_metric_right")
        _render_compare_chart(metric_right)

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
        achievement_cols = ["캠페인구분", "월", "광고비", "DB수", "DB단가", "DB수_달성률", "DB단가_달성률", "예산_달성률"]
        if set(achievement_cols).issubset(campaign_monthly.columns):
            ach_months = sorted(campaign_monthly["월"].unique())
            ach_month = st.selectbox("조회월", ach_months, index=len(ach_months) - 1, key="ach_month")

            ach_raw = campaign_monthly[campaign_monthly["월"] == ach_month][achievement_cols].copy()

            targets_dict = st.session_state.get("targets", {})

            def _row_of(campaign: str) -> pd.Series:
                return ach_raw[ach_raw["캠페인구분"] == campaign].iloc[0]

            # 지표별로 "해당 목표가 입력된 캠페인"만 일관되게 묶어서 합계를 낸다.
            # (목표가 없는 캠페인의 실제값이 분자에 섞여 달성률이 왜곡되는 것을 방지)
            db_scope = [c for c in selected_campaigns if (targets_dict.get(c) or {}).get("목표DB수")]
            budget_scope = [c for c in selected_campaigns if (targets_dict.get(c) or {}).get("월배정예산")]
            price_scope = [c for c in selected_campaigns if (targets_dict.get(c) or {}).get("목표DB단가")]

            total_budget = sum(_row_of(c)["광고비"] for c in selected_campaigns)
            total_db = sum(_row_of(c)["DB수"] for c in selected_campaigns)
            total_db_price = total_budget / total_db if total_db else float("nan")

            db_actual = sum(_row_of(c)["DB수"] for c in db_scope)
            db_target = sum((targets_dict.get(c) or {}).get("목표DB수") or 0 for c in db_scope)

            budget_actual = sum(_row_of(c)["광고비"] for c in budget_scope)
            budget_target = sum((targets_dict.get(c) or {}).get("월배정예산") or 0 for c in budget_scope)

            price_actual_budget = sum(_row_of(c)["광고비"] for c in price_scope)
            price_actual_db = sum(_row_of(c)["DB수"] for c in price_scope)
            price_actual = (price_actual_budget / price_actual_db) if price_actual_db else None
            price_target_avg = (
                sum((targets_dict.get(c) or {}).get("목표DB단가") or 0 for c in price_scope) / len(price_scope)
                if price_scope else None
            )

            total_row = pd.DataFrame([{
                "캠페인구분": "합계",
                "월": ach_month,
                "광고비": total_budget,
                "DB수": total_db,
                "DB단가": total_db_price,
                "DB수_달성률": (db_actual / db_target) if db_target else None,
                "DB단가_달성률": (price_target_avg / price_actual) if price_target_avg and price_actual else None,
                "예산_달성률": (budget_actual / budget_target) if budget_target else None,
            }])

            ach_df = pd.concat([ach_raw, total_row], ignore_index=True)
            display_cols = ["캠페인구분", "월", "DB수_달성률", "DB단가_달성률", "예산_달성률"]
            ach_df = ach_df[display_cols]
            for c in ["DB수_달성률", "DB단가_달성률", "예산_달성률"]:
                ach_df[c] = ach_df[c].apply(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "목표 미입력")
            st.dataframe(ach_df, width='stretch')
            st.caption("'합계' 행은 위 조회조건에서 선택한 캠페인들의 합산 기준입니다.")
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

DAILY_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "smartall_daily_data.xlsx")
MEDIA_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "smartall_media_data.xlsx")

with tab_daily:
    st.caption(
        "⚠️ 이 데이터는 인보이스 마감 기준이 아니라서 광고비 합계가 월별 데이터와 다를 수 있습니다. "
        "월별 데이터와 별도로 관리됩니다."
    )

    if not os.path.exists(DAILY_DATA_PATH):
        st.warning(f"⚠️ 일자별 데이터 파일이 없습니다: {os.path.basename(DAILY_DATA_PATH)}")
        st.stop()

    try:
        daily_df = load_daily_data(DAILY_DATA_PATH)
    except ValueError as e:
        st.error(f"❌ 일자별 데이터 형식이 맞지 않습니다: {e}")
        st.stop()

    daily_campaigns = sorted(daily_df["캠페인구분"].unique())
    d_col1, d_col2 = st.columns([1.4, 2])
    with d_col1:
        daily_selected = st.multiselect("캠페인구분", daily_campaigns, default=daily_campaigns, key="daily_campaigns")
    with d_col2:
        min_date, max_date = daily_df["일자"].min(), daily_df["일자"].max()
        daily_range = st.date_input(
            "기간", value=(min_date, max_date), min_value=min_date, max_value=max_date, key="daily_date_range"
        )

    if isinstance(daily_range, tuple) and len(daily_range) == 2:
        daily_start, daily_end = daily_range
    else:
        daily_start, daily_end = min_date, max_date

    daily_filtered = daily_df[
        daily_df["캠페인구분"].isin(daily_selected) & daily_df["일자"].between(daily_start, daily_end)
    ]

    if not daily_selected or daily_filtered.empty:
        st.info("선택한 조건에 해당하는 데이터가 없습니다.")
    else:
        d_total_spend = daily_filtered["광고비"].sum()
        d_total_db = daily_filtered["DB수"].sum()
        d_avg_price = d_total_spend / d_total_db if d_total_db else float("nan")

        m1, m2, m3 = st.columns(3)
        m1.metric("기간 합계 광고비", f"{d_total_spend:,.0f}원")
        m2.metric("기간 합계 DB수", f"{d_total_db:,.0f}건")
        m3.metric("기간 평균 DB단가", f"{d_avg_price:,.0f}원")

        opt_col1, opt_col2 = st.columns([1, 1])
        with opt_col1:
            daily_metric = st.selectbox("지표 선택", ["광고비", "DB수", "DB단가"], key="daily_metric")
        with opt_col2:
            daily_smooth = st.checkbox("7일 이동평균으로 보기", value=True, key="daily_smooth")

        daily_plot_df = daily_filtered.sort_values(["캠페인구분", "일자"]).copy()
        if daily_smooth:
            daily_plot_df[daily_metric] = daily_plot_df.groupby("캠페인구분")[daily_metric].transform(
                lambda s: s.rolling(7, min_periods=1).mean()
            )

        fig_daily = px.line(
            daily_plot_df, x="일자", y=daily_metric, color="캠페인구분",
            color_discrete_map=CAMPAIGN_COLORS,
            title=f"일자별 {daily_metric} 추이" + ("(7일 이동평균)" if daily_smooth else ""),
        )
        st.plotly_chart(fig_daily, width="stretch")

        with st.expander("일자별 원본 데이터 보기"):
            daily_display = daily_filtered.copy()
            daily_display["일자"] = daily_display["일자"].astype(str)
            styled_daily = (
                style_campaign_rows(daily_display)
                .format({"광고비": "{:,.0f}", "DB수": "{:,.0f}", "DB단가": "{:,.0f}"})
                .hide(axis="index")
            )
            st.dataframe(styled_daily, width="stretch", height=400)

with tab_media:
    st.caption(
        "⚠️ 이 데이터의 광고비는 매체 집행비 기준이라, 부대비용이 포함된 월별 데이터의 총 광고비와 합계가 다를 수 있습니다. "
        "월별 데이터와 별도로 관리됩니다."
    )

    if not os.path.exists(MEDIA_DATA_PATH):
        st.warning(f"⚠️ 매체별 데이터 파일이 없습니다: {os.path.basename(MEDIA_DATA_PATH)}")
        st.stop()

    try:
        media_df = load_media_data(MEDIA_DATA_PATH)
    except ValueError as e:
        st.error(f"❌ 매체별 데이터 형식이 맞지 않습니다: {e}")
        st.stop()

    media_campaigns = sorted(media_df["캠페인구분"].unique())
    media_months = sorted(media_df["월"].unique())

    mf_col1, mf_col2 = st.columns([1.4, 2])
    with mf_col1:
        media_selected_campaigns = st.multiselect(
            "캠페인구분", media_campaigns, default=media_campaigns, key="media_campaigns"
        )
    with mf_col2:
        default_start = media_months[max(0, len(media_months) - 6)]
        media_month_range = st.select_slider(
            "기간(월)", options=media_months, value=(default_start, media_months[-1]), key="media_month_range"
        )
    media_start, media_end = media_month_range

    media_filtered = media_df[
        media_df["캠페인구분"].isin(media_selected_campaigns)
        & media_df["월"].between(media_start, media_end)
    ].dropna(subset=["광고비"])

    if not media_selected_campaigns or media_filtered.empty:
        st.info("선택한 조건에 해당하는 데이터가 없습니다.")
    else:
        media_agg = media_filtered.groupby("매체", as_index=False).agg(
            광고비=("광고비", "sum"), DB수=("DB수", "sum"), 입회수=("입회수", "sum")
        )
        media_agg["DB단가"] = media_agg["광고비"] / media_agg["DB수"].replace(0, pd.NA)
        media_agg["입회율"] = media_agg["입회수"] / media_agg["DB수"].replace(0, pd.NA)
        media_agg = media_agg.sort_values("광고비", ascending=False).reset_index(drop=True)

        top_n = st.slider(
            "표시할 매체 수 (광고비 기준 상위)", min_value=3, max_value=len(media_agg),
            value=min(8, len(media_agg)), key="media_top_n",
        )
        top_media = media_agg.head(top_n)

        bar_col1, bar_col2 = st.columns(2)
        with bar_col1:
            fig_spend = px.bar(
                top_media, x="매체", y="광고비", title=f"매체별 광고비 (상위 {top_n})", text_auto=".2s"
            )
            st.plotly_chart(fig_spend, width="stretch")
        with bar_col2:
            fig_price = px.bar(
                top_media.sort_values("DB단가"), x="매체", y="DB단가",
                title="매체별 DB단가 (낮을수록 효율적)", text_auto=".0f",
            )
            st.plotly_chart(fig_price, width="stretch")

        st.markdown("**매체별 월별 광고비 추이 (상위 매체)**")
        trend_source = media_filtered[media_filtered["매체"].isin(top_media["매체"])]
        trend_agg = trend_source.groupby(["월", "매체"], as_index=False)["광고비"].sum()
        fig_trend_media = px.line(
            trend_agg, x="월", y="광고비", color="매체", markers=True, title="상위 매체 월별 광고비 추이"
        )
        st.plotly_chart(fig_trend_media, width="stretch")

        st.markdown("**매체별 집계 표**")
        styled_media = (
            top_media.style
            .format(
                {"광고비": "{:,.0f}", "DB수": "{:,.0f}", "입회수": "{:,.0f}", "DB단가": "{:,.0f}", "입회율": "{:.1%}"},
                na_rep="-",
            )
            .hide(axis="index")
        )
        st.dataframe(styled_media, width="stretch")
