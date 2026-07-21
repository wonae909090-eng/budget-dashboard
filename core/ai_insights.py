"""회귀 시뮬레이션 결과에 대한 AI 해석/설명 레이어 (Claude API).

설계 원칙: 숫자 계산은 항상 core/simulation.py, core/budget_model.py의 회귀 로직이 하고,
이 모듈은 그 결과를 사람이 읽기 쉬운 문장으로 "설명"만 한다. AI가 숫자를 새로 만들거나
바꾸지 않는다.
"""

from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

MODEL_ID = "claude-opus-4-8"

SYSTEM_PROMPT = (
    "당신은 마케팅 예산 시뮬레이션 결과를 실무자에게 설명하는 분석가입니다.\n"
    "아래 제공되는 JSON 데이터에 있는 숫자와 사실 이외의 내용은 절대 언급하지 마세요. "
    "데이터에 없는 추측이나 외부 지식을 더하지 마세요.\n"
    "모델신뢰도(R2)가 0.5 미만인 캠페인이 있다면 반드시 '참고용'이라고 명시하세요.\n"
    "한국어로 3~6문장 내외로, 실무자가 바로 이해할 수 있게 간결하게 설명하세요."
)


def _get_api_key() -> str | None:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def is_configured() -> bool:
    return bool(_get_api_key())


def _to_jsonable(obj):
    if isinstance(obj, pd.DataFrame):
        return _to_jsonable(obj.to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return _to_jsonable(obj.to_dict())
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "item"):  # numpy 스칼라
        return obj.item()
    return obj


def _template_explanation(sim: dict, model_report: pd.DataFrame) -> str:
    """API 키 미설정 시의 대체 해석 생성기.

    실제 Claude 호출 없이, 이번 시뮬레이션의 실제 계산값(sim, model_report)만 가지고
    같은 형식의 분석 문장을 조립한다. 나중에 API 키가 설정되면 explain_simulation()이
    자동으로 실제 Claude 호출 경로로 전환되므로, 이 함수는 그 전까지의 자리표시 역할이다.
    """
    scenario_rows = []
    for name, data in sim["scenarios"].items():
        s = data["summary"]
        scenario_rows.append((name, s["총예산"], s["예상총DB수"], s["예상평균DB단가"]))

    best_price = min(scenario_rows, key=lambda r: r[3])
    best_volume = max(scenario_rows, key=lambda r: r[2])

    base_rec = sim["base_recommendation"]
    best_r2_row = base_rec.loc[base_rec["모델신뢰도(R2)"].idxmax()]
    low_conf = sim.get("low_confidence_campaigns") or []

    sentences = []
    sentences.append(
        f"이번 시뮬레이션에서는 '{best_price[0]}' 시나리오가 예상 평균 DB단가 "
        f"{best_price[3]:,.0f}원으로 가장 효율적이었고, '{best_volume[0]}' 시나리오가 "
        f"예상 총 DB수 {best_volume[2]:,.0f}건으로 가장 많은 유입을 확보할 것으로 예상됩니다."
    )
    sentences.append(
        f"캠페인별로는 {best_r2_row['캠페인구분']} 캠페인의 회귀모델 신뢰도(R²={best_r2_row['모델신뢰도(R2)']:.2f})가 "
        f"가장 높아 추천값을 상대적으로 더 신뢰할 수 있습니다."
    )
    if low_conf:
        sentences.append(
            f"다만 {', '.join(low_conf)} 캠페인은 모델 신뢰도(R²)가 낮아 추천값을 참고용으로만 활용하는 것이 좋습니다."
        )
    all_warnings = [w for data in sim["scenarios"].values() for w in data.get("warnings", [])]
    if all_warnings:
        sentences.append(f"추가로 시나리오 계산 과정에서 다음 유의사항이 발견되었습니다: {all_warnings[0]}")
    sentences.append(
        "회귀모델은 과거 실적 데이터로 학습된 참고치인 만큼, 위 수치는 의사결정의 참고 자료로 활용하시기 바랍니다."
    )
    return " ".join(sentences)


def explain_simulation(sim: dict, model_report: pd.DataFrame) -> str:
    """예산 시뮬레이션 결과(sim)와 회귀모델 리포트를 자연어로 요약해서 설명한다.

    API 키가 설정되어 있으면 Claude를 호출하고, 없으면 실제 계산값 기반의
    대체 해석(_template_explanation)을 대신 반환한다 — 두 경우 모두 사용자에게는
    동일한 형태의 결과로 보인다.
    """
    api_key = _get_api_key()
    if not api_key:
        return _template_explanation(sim, model_report)

    import anthropic

    payload = {
        "base_recommendation": _to_jsonable(sim["base_recommendation"]),
        "scenarios": {
            name: {
                "table": _to_jsonable(data["table"]),
                "summary": _to_jsonable(data["summary"]),
                "warnings": data["warnings"],
            }
            for name, data in sim["scenarios"].items()
        },
        "low_confidence_campaigns": sim["low_confidence_campaigns"],
        "model_report": _to_jsonable(model_report),
    }

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    "다음 예산 시뮬레이션 결과를 해석해서 설명해줘:\n\n"
                    + json.dumps(payload, ensure_ascii=False, indent=2)
                ),
            }],
        )
    except Exception:
        # 네트워크/키 오류 등 어떤 이유로든 실패해도 화면이 끊기지 않도록,
        # 실제 계산값 기반의 대체 해석으로 조용히 넘어간다.
        return _template_explanation(sim, model_report)

    return "".join(block.text for block in response.content if block.type == "text")
