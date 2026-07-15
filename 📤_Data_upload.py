"""데이터 업로드 + 정제 실행 페이지."""

import os
import sys

import streamlit as st

sys.path.append(os.path.dirname(__file__))

from core.data_cleaning import clean_pipeline  # noqa: E402
from core.daily_media_data import load_daily_data, load_media_data  # noqa: E402
from core.ui import setup_page  # noqa: E402

st.set_page_config(page_title="Data upload", page_icon="📤", layout="wide")
setup_page()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DEFAULT_MONTHLY_PATH = os.path.join(DATA_DIR, "smartall_raw_data.xlsx")
DEFAULT_DAILY_PATH = os.path.join(DATA_DIR, "smartall_daily_data.xlsx")
DEFAULT_MEDIA_PATH = os.path.join(DATA_DIR, "smartall_media_data.xlsx")

MONTHLY_COLUMNS = ["캠페인구분", "월", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]
DAILY_COLUMNS = ["캠페인구분", "일자", "광고비", "DB수", "DB단가"]
MEDIA_COLUMNS = ["캠페인구분", "월", "매체", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율"]

st.title("📤 데이터 업로드")
st.caption(
    "키즈 / 초등 / 중학 캠페인 데이터를 업로드하면 자동으로 정제되어 다른 페이지에서 바로 사용됩니다. "
    "월별 · 일자별 · 매체별 데이터는 서로 합계를 맞추지 않는 완전히 별도의 데이터입니다."
)

tab_monthly, tab_daily, tab_media = st.tabs(["📅 월별 데이터", "🗓️ 일자별 데이터", "📡 매체별 데이터"])

with tab_monthly:
    st.caption(f"필수 컬럼: {', '.join(MONTHLY_COLUMNS)}")
    monthly_default_exists = os.path.exists(DEFAULT_MONTHLY_PATH)
    monthly_uploaded = st.file_uploader(
        "월별 원본 데이터 파일 업로드 (xlsx 또는 csv)" if not monthly_default_exists else
        "월별 원본 데이터 파일 업로드 (xlsx 또는 csv, 미업로드 시 기본 데이터 사용)",
        type=["xlsx", "xls", "csv"],
        key="upload_monthly",
    )

    monthly_data_path = None
    if monthly_uploaded is not None:
        tmp_path = os.path.join(DATA_DIR, f"_uploaded_{monthly_uploaded.name}")
        with open(tmp_path, "wb") as f:
            f.write(monthly_uploaded.getbuffer())
        monthly_data_path = tmp_path
    elif monthly_default_exists:
        monthly_data_path = DEFAULT_MONTHLY_PATH
        st.info(f"기본 데이터 파일을 사용합니다: {os.path.basename(DEFAULT_MONTHLY_PATH)}")
    else:
        st.info("이 배포 환경에는 샘플 데이터가 포함되어 있지 않습니다. 위에서 데이터 파일을 업로드해주세요.")

    if monthly_data_path:
        try:
            monthly_result = clean_pipeline(monthly_data_path)
        except ValueError as e:
            st.error(f"❌ 데이터 형식이 맞지 않습니다: {e}")
            monthly_result = None
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ 데이터 로드/정제 중 오류가 발생했습니다: {e}")
            monthly_result = None

        if monthly_result:
            df = monthly_result["df"]
            duplicates = monthly_result["duplicates"]
            n_inconsistent = monthly_result["n_inconsistent"]
            n_outlier = monthly_result["n_outlier"]

            st.session_state["processed_df"] = df

            if monthly_uploaded is not None:
                st.success("✅ 업로드 성공! 데이터가 정제되어 바로 반영되었습니다.")
            else:
                st.success("✅ 데이터가 정제되어 반영되었습니다.")

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
                        df.loc[
                            df["flag_inconsistent"],
                            ["캠페인구분", "월", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율", "reason"],
                        ],
                        width='stretch',
                    )

            if n_outlier > 0:
                with st.expander(f"⚠️ 이상치 상세 ({n_outlier}건)"):
                    st.dataframe(
                        df.loc[
                            df["flag_outlier"],
                            ["캠페인구분", "월", "광고비", "DB수", "DB단가", "입회수", "입회단가", "입회율", "outlier_reason"],
                        ],
                        width='stretch',
                    )

            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "정제된 데이터 CSV 다운로드",
                data=csv_bytes,
                file_name="smartall_cleaned_data.csv",
                mime="text/csv",
                key="download_monthly",
            )

with tab_daily:
    st.caption(
        f"필수 컬럼: {', '.join(DAILY_COLUMNS)} — ⚠️ 인보이스 마감 기준이 아니라서 월별 데이터와 광고비 합계가 다를 수 있습니다."
    )
    daily_default_exists = os.path.exists(DEFAULT_DAILY_PATH)
    daily_uploaded = st.file_uploader(
        "일자별 데이터 파일 업로드 (xlsx 또는 csv)" if not daily_default_exists else
        "일자별 데이터 파일 업로드 (xlsx 또는 csv, 미업로드 시 기본 데이터 사용)",
        type=["xlsx", "xls", "csv"],
        key="upload_daily",
    )

    daily_data_path = None
    if daily_uploaded is not None:
        tmp_path = os.path.join(DATA_DIR, f"_uploaded_daily_{daily_uploaded.name}")
        with open(tmp_path, "wb") as f:
            f.write(daily_uploaded.getbuffer())
        daily_data_path = tmp_path
    elif daily_default_exists:
        daily_data_path = DEFAULT_DAILY_PATH
        st.info(f"기본 데이터 파일을 사용합니다: {os.path.basename(DEFAULT_DAILY_PATH)}")
    else:
        st.info(
            "일자별 데이터는 선택 사항입니다. 업로드하지 않으면 '성과 대시보드 > 일자별 성과 추이' 탭이 비활성화됩니다."
        )

    if daily_data_path:
        try:
            daily_df = load_daily_data(daily_data_path)
        except ValueError as e:
            st.error(f"❌ 일자별 데이터 형식이 맞지 않습니다: {e}")
            daily_df = None
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ 일자별 데이터 로드 중 오류가 발생했습니다: {e}")
            daily_df = None

        if daily_df is not None:
            st.session_state["daily_df"] = daily_df
            st.success(f"✅ 일자별 데이터 반영 완료 ({len(daily_df):,}행)")
            with st.expander("일자별 데이터 미리보기"):
                daily_preview = daily_df.copy()
                daily_preview["일자"] = daily_preview["일자"].astype(str)
                st.dataframe(daily_preview, width='stretch', height=400)

with tab_media:
    st.caption(
        f"필수 컬럼: {', '.join(MEDIA_COLUMNS)} — ⚠️ 부대비용이 포함된 월별 데이터의 총 광고비와 합계가 다를 수 있습니다."
    )
    media_default_exists = os.path.exists(DEFAULT_MEDIA_PATH)
    media_uploaded = st.file_uploader(
        "매체별 데이터 파일 업로드 (xlsx 또는 csv)" if not media_default_exists else
        "매체별 데이터 파일 업로드 (xlsx 또는 csv, 미업로드 시 기본 데이터 사용)",
        type=["xlsx", "xls", "csv"],
        key="upload_media",
    )

    media_data_path = None
    if media_uploaded is not None:
        tmp_path = os.path.join(DATA_DIR, f"_uploaded_media_{media_uploaded.name}")
        with open(tmp_path, "wb") as f:
            f.write(media_uploaded.getbuffer())
        media_data_path = tmp_path
    elif media_default_exists:
        media_data_path = DEFAULT_MEDIA_PATH
        st.info(f"기본 데이터 파일을 사용합니다: {os.path.basename(DEFAULT_MEDIA_PATH)}")
    else:
        st.info(
            "매체별 데이터는 선택 사항입니다. 업로드하지 않으면 '성과 대시보드 > 주요 매체별 성과' 탭이 비활성화됩니다."
        )

    if media_data_path:
        try:
            media_df = load_media_data(media_data_path)
        except ValueError as e:
            st.error(f"❌ 매체별 데이터 형식이 맞지 않습니다: {e}")
            media_df = None
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ 매체별 데이터 로드 중 오류가 발생했습니다: {e}")
            media_df = None

        if media_df is not None:
            st.session_state["media_df"] = media_df
            st.success(f"✅ 매체별 데이터 반영 완료 ({len(media_df):,}행)")
            with st.expander("매체별 데이터 미리보기"):
                st.dataframe(media_df, width='stretch', height=400)
