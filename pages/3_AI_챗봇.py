"""AI 챗봇 페이지 (1단계 규칙기반)."""

import os
import sys

import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.chatbot import answer  # noqa: E402
from core.kpi_aggregation import build_kpi_summary  # noqa: E402

st.set_page_config(page_title="AI 챗봇", layout="wide")
st.title("🤖 AI 챗봇")

if "processed_df" not in st.session_state:
    st.warning("⚠️ '데이터 확인'에서 데이터를 먼저 로드/정제해주세요.")
    st.stop()

df = st.session_state["processed_df"]

kpi_summary = st.session_state.get("kpi_summary")
if kpi_summary is None:
    kpi_summary = build_kpi_summary(df, targets=st.session_state.get("targets"))

budget_simulation = st.session_state.get("budget_simulation")

st.info(
    "**이 챗봇은 자유 대화형 AI가 아니라, 문장에서 정해진 키워드(캠페인명·기간·지표)를 "
    "찾아 답하는 규칙기반 챗봇입니다.** 아래 범위 안에서 질문하면 정확하게 답합니다.\n\n"
    "**✅ 할 수 있는 질문**\n"
    "- **실적 조회**: [캠페인] + [기간] + [지표]를 조합한 질문\n"
    "  - 캠페인: 키즈 / 초등 / 중학\n"
    "  - 기간: \"2026년 3월\", \"지난달\", \"이번달\", \"3월\", \"작년 5월\" 등\n"
    "  - 지표: 광고비 / DB수 / DB단가 / 입회수 / 입회단가 / 입회율\n"
    "  - 예: \"중학 캠페인 지난달 DB단가 알려줘\"\n"
    "- **예산 추천 조회**: '예산 추천' 페이지에서 시뮬레이션을 실행한 뒤, 캠페인별 추천예산이나 "
    "보수/중립/적극 시나리오별 예산·DB수·DB단가를 물어볼 수 있습니다.\n"
    "  - 예: \"초등 캠페인 추천예산 알려줘\", \"적극 시나리오 키즈 캠페인 예산은?\"\n\n"
    "**❌ 할 수 없는 것(한계)**\n"
    "- 캠페인명/지표명 키워드가 문장에 없으면 인식하지 못합니다 (오타·미등록 동의어 포함).\n"
    "- \"A와 B 중 어디가 더 나아요?\" 같은 비교·추론성 질문은 처리하지 못합니다.\n"
    "- 여러 조건을 동시에 묻는 복잡한 질문(예: 두 캠페인을 한 문장에서 동시에 비교)은 지원하지 않습니다.\n"
    "- 예산 추천 질문은 '예산 추천' 페이지에서 시뮬레이션을 먼저 실행해야 답할 수 있습니다."
)

with st.expander("💡 질문 예시 더보기"):
    st.markdown(
        "- 중학 캠페인의 지난달 DB단가 알려줘\n"
        "- 키즈 캠페인 2026년 3월 입회율은?\n"
        "- 초등 캠페인 작년 5월 DB수는?\n"
        "- 초등 캠페인 추천예산 알려줘\n"
        "- 적극 시나리오 키즈 캠페인 예산은?\n"
        "- 보수 시나리오 결과 알려줘"
    )

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

for msg in st.session_state["chat_history"]:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

prompt = st.chat_input("질문을 입력하세요 (예: 중학 캠페인 지난달 DB단가 알려줘)")

if prompt:
    st.session_state["chat_history"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    response = answer(prompt, kpi_summary, budget_simulation)

    st.session_state["chat_history"].append({"role": "assistant", "content": response})
    with st.chat_message("assistant"):
        st.write(response)

if st.session_state["chat_history"]:
    if st.button("🗑️ 대화 초기화"):
        st.session_state["chat_history"] = []
        st.rerun()
