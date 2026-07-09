# 스마트올 캠페인 성과 분석 시스템

- 목적: 키즈/초등/중학 3개 캠페인의 퍼포먼스 마케팅 성과 분석 및 예산 추천
- 작성일: 2026-07-09
- 버전: v1 (1단계 — 데이터 정제)

## 실행 방법

```
cd tools/app
pip install -r requirements.txt
streamlit run 데이터_확인.py
```

## 데이터 안내

- 원본 데이터: `data/smartall_raw_data.xlsx` (canonical 원본은 `../../context/smartall_raw_data.xlsx`)
- 실제 원본 파일은 이미 숫자형으로 정제된 엑셀 파일이나, `core/data_cleaning.py`의 파서는
  콤마 포함 문자열/퍼센트 문자열/CSV(EUC-KR) 형태로 원본이 교체되어도 안전하게 처리하도록
  방어적으로 구현되어 있음.

## 진행 단계

- [x] 1단계: 프로젝트 구조 + `core/data_cleaning.py` + `데이터_확인.py` (구 `Home.py`)
- [x] 2단계: `core/kpi_aggregation.py` + `pages/1_스마트올_성과_대시보드.py` (구 KPI 대시보드)
- [x] 3단계: `core/budget_model.py`
- [x] 4단계: `core/simulation.py` + `pages/2_예산_추천.py`
- [x] 6단계: `core/chatbot.py` + `pages/3_AI_챗봇.py` (1단계 규칙기반)
- [x] 7단계(사용자 요청): Home→데이터 확인 개명, 대시보드 필터 UI 개선, 예산추천 총예산·최소값 제약 추가,
      권한설정 페이지 삭제, 챗봇 기능 설명 추가

> 5단계였던 `pages/4_권한_설정.py`(역할·조회범위 제한)는 사용자 요청으로 삭제되었습니다.
> 관련 로직(`role`/`scope` 필터링)도 `pages/1_스마트올_성과_대시보드.py`, `pages/2_예산_추천.py`,
> `pages/3_AI_챗봇.py`, `core/chatbot.py`에서 함께 제거했습니다.
