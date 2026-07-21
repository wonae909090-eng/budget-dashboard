"""공용 UI 컴포넌트: 헤더 배너, 캠페인 색상, 사이드바 스타일."""

import os

import streamlit as st

CAMPAIGN_COLORS = {
    "키즈": "#8BC34A",  # 연두색
    "초등": "#FF9800",  # 주황색
    "중학": "#9C27B0",  # 보라색
}

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "asset", "logo.png")


def render_header() -> None:
    """모든 페이지 상단에 표시되는 로고 + 타이틀 배너."""
    col_logo, col_title = st.columns([1, 5], vertical_alignment="center")
    with col_logo:
        if os.path.exists(_LOGO_PATH):
            st.image(_LOGO_PATH, width=160)
    with col_title:
        st.markdown(
            "<div style='font-size:2.72rem; font-weight:800; color:#0B2545;'>"
            "AI Decision Partner for Digital Marketing 😉</div>",
            unsafe_allow_html=True,
        )
    st.divider()


def apply_sidebar_style() -> None:
    """사이드바 네비게이션 라벨을 기존 대비 더 굵고 크게(약 30%↑) 표시."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNavLink"] {
            font-size: 1.3rem !important;
            font-weight: 700 !important;
        }
        [data-testid="stSidebarNavLink"] * {
            font-size: 1.3rem !important;
            font-weight: 700 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def setup_page() -> None:
    """페이지 진입 시 공통으로 호출: 사이드바 스타일 + 상단 헤더 배너."""
    apply_sidebar_style()
    render_header()


def campaign_badge_html(campaign: str) -> str:
    """캠페인명을 고유 색상의 둥근 배지(뱃지) HTML로 반환."""
    color = CAMPAIGN_COLORS.get(campaign, "#666666")
    return (
        f"<span style='background-color:{color}; color:#ffffff; font-weight:700; "
        f"padding:3px 12px; border-radius:12px; display:inline-block;'>{campaign}</span>"
    )


def campaign_badge(campaign: str) -> None:
    """campaign_badge_html()을 바로 렌더링."""
    st.markdown(campaign_badge_html(campaign), unsafe_allow_html=True)


def style_campaign_rows(df, col: str = "캠페인구분", neutral_cols: list[str] | None = None):
    """DataFrame의 캠페인 컬럼 값에 따라 행 배경색을 캠페인 고유 색상(옅은 톤)으로 칠한 Styler 반환.

    neutral_cols를 지정하면 그 컬럼들은 캠페인 색상 대신 중립 회색 음영으로 덮어써서,
    "참고용" 컬럼(계산 결과가 아닌 비교 기준치 등)임을 시각적으로 구분해 보여준다.
    """

    def _row_style(row):
        color = CAMPAIGN_COLORS.get(row[col])
        if not color:
            return [""] * len(row)
        return [f"background-color:{color}22"] * len(row)

    styler = df.style.apply(_row_style, axis=1)
    if neutral_cols:
        existing = [c for c in neutral_cols if c in df.columns]
        if existing:
            styler = styler.set_properties(
                subset=existing, **{"background-color": "#8888881a", "color": "#666666"}
            )
    return styler
