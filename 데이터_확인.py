"""데이터 로드 + 정제 실행 페이지."""

import os
import sys

import pandas as pd
import streamlit as st

sys.path.append(os.path.dirname(__file__))

from core.data_cleaning import clean_pipeline  # noqa: E402

st.set_page_config(page_title="데이터 확인", page_icon="🔍", layout="wide")

DEFAULT_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "smartall_raw_data.xlsx")

st.title("🔍 데이터 확인")
st.caption("키즈 / 초등 / 중학 캠페인 퍼포먼스 마케팅 데이터 로드 및 정제")

st.header("1. 데이터 로드")

default_exists = os.path.exists(DEFAULT_DATA_PATH)

uploaded_file = st.file_uploader(
    "원본 데이터 파일 업로드 (xlsx 또는 csv)" if not default_exists else
    "원본 데이터 파일 업로드 (xlsx 또는 csv, 미업로드 시 기본 데이터 사용)",
    type=["xlsx", "xls", "csv"],
)

if uploaded_file is not None:
    tmp_path = os.path.join(os.path.dirname(__file__), "data", f"_uploaded_{uploaded_file.name}")
    with open(tmp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    data_path = tmp_path
    st.info(f"업로드된 파일을 사용합니다: {uploaded_file.name}")
elif default_exists:
    data_path = DEFAULT_DATA_PATH
    st.info(f"기본 데이터 파일을 사용합니다: {os.path.basename(DEFAULT_DATA_PATH)}")
else:
    st.info("이 배포 환경에는 샘플 데이터가 포함되어 있지 않습니다. 위에서 데이터 파일을 업로드해주세요.")
    st.stop()

try:
    result = clean_pipeline(data_path)
except Exception as e:  # noqa: BLE001
    st.error(f"데이터 로드/정제 중 오류가 발생했습니다: {e}")
    st.stop()

df = result["df"]
duplicates = result["duplicates"]
n_rows = result["n_rows"]
n_inconsistent = result["n_inconsistent"]
n_outlier = result["n_outlier"]

st.header("2. 정제 결과 요약")

col1, col2, col3, col4 = st.columns(4)
col1.metric("총 행 수", f"{n_rows}행")
col2.metric("정합성 불일치", f"{n_inconsistent}건")
col3.metric("이상치 플래그", f"{n_outlier}건")
col4.metric("중복 캠페인×월", f"{len(duplicates)}건")

st.success(
    f"총 {n_rows}행 중 이상치 {n_outlier}건, 정합성 불일치 {n_inconsistent}건 발견되었습니다."
)

if len(duplicates) > 0:
    st.warning("⚠️ 캠페인×월 중복 행이 발견되었습니다.")
    st.dataframe(duplicates, width='stretch')

st.subheader("정제된 데이터 미리보기")
display_df = df.copy()
display_df["입회율"] = (display_df["입회율"] * 100).round(2).astype(str) + "%"
st.dataframe(display_df, width='stretch', height=400)

if n_inconsistent > 0:
    with st.expander(f"⚠️ 정합성 불일치 상세 ({n_inconsistent}건)"):
        st.dataframe(
            df.loc[df["flag_inconsistent"], ["캠페인구분", "월", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율", "reason"]],
            width='stretch',
        )

if n_outlier > 0:
    with st.expander(f"⚠️ 이상치 상세 ({n_outlier}건)"):
        st.dataframe(
            df.loc[df["flag_outlier"], ["캠페인구분", "월", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율", "outlier_reason"]],
            width='stretch',
        )

st.header("3. 확정")
st.write("아래 버튼을 클릭하면 정제된 데이터가 세션에 저장되어 다른 페이지에서 사용할 수 있습니다.")

if st.button("✅ 확정", type="primary"):
    st.session_state["processed_df"] = df
    st.success("정제된 데이터가 세션에 저장되었습니다. 좌측 메뉴에서 다른 페이지로 이동해주세요.")

if "processed_df" in st.session_state:
    st.caption(f"현재 세션에 저장된 데이터: {len(st.session_state['processed_df'])}행")

    csv_bytes = st.session_state["processed_df"].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "정제된 데이터 CSV 다운로드",
        data=csv_bytes,
        file_name="smartall_cleaned_data.csv",
        mime="text/csv",
    )
