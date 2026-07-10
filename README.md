# AI Decision Partner for Digital Marketing

- 목적: 키즈/초등/중학 3개 캠페인의 퍼포먼스 마케팅 성과 분석 및 예산 시뮬레이션
- 작성일: 2026-07-10
- 버전: v2 (리브랜딩 — 헤더/사이드바 네이밍/캠페인 색상/UX 개선)

## 실행 방법

```
cd tools/app
pip install -r requirements.txt
streamlit run 📤_Data_upload.py
```

Streamlit Cloud에 배포할 경우 Main file path는 `📤_Data_upload.py` (저장소 루트 기준).

## 페이지 구성 (사이드바 순서)

| 사이드바 라벨 | 파일 | 설명 |
|---|---|---|
| 📤 Data upload | `📤_Data_upload.py` | 원본 데이터 업로드 → 자동 정제·검증 후 즉시 반영 |
| 📊 Performance Dashboard | `pages/1_📊_Performance_Dashboard.py` | 트렌드, 월별 캠페인 비교, MoM/YoY, 목표 대비 달성률 |
| 💰 Budget Simulation | `pages/2_💰_Budget_Simulation.py` | 회귀 기반 예산 추천 + 보수/중립/적극 시나리오 시뮬레이션 |
| 🔎 Quick Lookup | `pages/3_🔎_Quick_Lookup.py` | 규칙기반 자연어 질의(실적/예산 시뮬레이션 조회) |

## 캠페인 색상 규칙 (`core/ui.py::CAMPAIGN_COLORS`)

- 키즈: 연두색(`#8BC34A`) / 초등: 주황색(`#FF9800`) / 중학: 보라색(`#9C27B0`)
- 모든 Plotly 차트에서 `color_discrete_map=CAMPAIGN_COLORS`로 동일하게 적용

## 데이터 안내

- 원본 데이터: `data/smartall_raw_data.xlsx` (canonical 원본은 `../../context/smartall_raw_data.xlsx`)
  — 공개 저장소에는 실제 데이터 파일을 올리지 않고 `.gitignore`로 제외했으며, 배포 환경에서는
  "Data upload" 페이지에서 직접 업로드해야 사용 가능.
- `core/data_cleaning.py`의 파서는 콤마 포함 문자열/퍼센트 문자열/CSV(EUC-KR) 형태로 원본이
  교체되어도 안전하게 처리하도록 방어적으로 구현되어 있음.

## 진행 이력

- v1: 데이터 정제 → KPI 집계/대시보드 → 회귀 기반 예산 추천 모델 → 시나리오 시뮬레이션 →
  권한 설정(이후 삭제) → 규칙기반 챗봇 순으로 6단계 구축
- v2(현재): 전체 리브랜딩
  - 상단 헤더(로고 + "AI Decision Partner for Digital Marketing") 전 페이지 공통 적용 (`core/ui.py`)
  - 사이드바 라벨 영문화 + 이모지 + 폰트 확대(약 30%)/볼드 처리
  - 페이지명 변경: 데이터 확인→Data upload, 스마트올 성과 대시보드→Performance Dashboard,
    예산 추천→Budget Simulation, AI 챗봇→Quick Lookup
  - Performance Dashboard: 필터를 요약 위 본문으로 이동, 기간 필터를 연/월 직접 선택으로 변경,
    "캠페인 간 비교"를 최근월 고정 대신 사용자가 선택하는 두 개 월 비교(기본값: 최근월 vs 전년 동월)로 변경,
    목표값 입력을 사이드바에서 "목표 대비 달성률" 섹션 내부로 이동
  - Budget Simulation: 예측 대상월을 실제 연-월 옵션으로 변경, 총예산 설정 옵션 추가,
    캠페인별 최소 집행비용/최소 DB목표(floor) 제약 추가 (보수·중립은 강제 적용,
    적극은 최소 집행비용만 강제하고 최소 DB목표는 경고만 표시)
  - 권한 설정 페이지 삭제 (역할/조회범위 제한 기능 제거)
  - 캠페인별 고유 색상(키즈 연두/초등 주황/중학 보라) 전 차트 공통 적용
  - Streamlit Community Cloud 배포 준비 (실데이터 제외, `.gitignore`, 업로드 전제 fallback 처리)
