"""데이터 업로드 + 정제 실행 페이지."""

import os
import sys

import streamlit as st

sys.path.append(os.path.dirname(__file__))

from core.data_cleaning import clean_pipeline  # noqa: E402
from core.ui import setup_page  # noqa: E402

st.set_page_config(page_title="Data upload", page_icon="📤", layout="wide")
setup_page()

DEFAULT_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "smartall_raw_data.xlsx")
REQUIRED_COLUMNS = ["캠페인구분", "월", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]

st.title("📤 데이터 업로드")
st.caption(
    "키즈 / 초등 / 중학 캠페인 원본 데이터를 업로드하면 자동으로 정제되어 다른 페이지에서 바로 사용됩니다. "
    f"필수 컬럼: {', '.join(REQUIRED_COLUMNS)}"
)

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
elif default_exists:
    data_path = DEFAULT_DATA_PATH
    st.info(f"기본 데이터 파일을 사용합니다: {os.path.basename(DEFAULT_DATA_PATH)}")
else:
    st.info("이 배포 환경에는 샘플 데이터가 포함되어 있지 않습니다. 위에서 데이터 파일을 업로드해주세요.")
    st.stop()

try:
    result = clean_pipeline(data_path)
except ValueError as e:
    st.error(f"❌ 데이터 형식이 맞지 않습니다: {e}")
    st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"❌ 데이터 로드/정제 중 오류가 발생했습니다: {e}")
    st.stop()

df = result["df"]
duplicates = result["duplicates"]
n_inconsistent = result["n_inconsistent"]
n_outlier = result["n_outlier"]

st.session_state["processed_df"] = df

if uploaded_file is not None:
    st.success("✅ 업로드 성공! 데이터가 정제되어 바로 반영되었습니다. 좌측 메뉴에서 다른 페이지로 이동해주세요.")
else:
    st.success("✅ 데이터가 정제되어 반영되었습니다. 좌측 메뉴에서 다른 페이지로 이동해주세요.")

if len(duplicates) > 0:
    st.warning("⚠️ 캠페인×월 중복 행이 발견되었습니다.")
    st.dataframe(duplicates, width='stretch')

with st.expander("정제된 데이터 미리보기"):
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

csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "정제된 데이터 CSV 다운로드",
    data=csv_bytes,
    file_name="smartall_cleaned_data.csv",
    mime="text/csv",
)
