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
            "<div style='font-size:1.6rem; font-weight:800;'>AI Decision Partner for Digital Marketing</div>",
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
