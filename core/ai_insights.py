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


def explain_simulation(sim: dict, model_report: pd.DataFrame) -> str:
    """예산 시뮬레이션 결과(sim)와 회귀모델 리포트를 자연어로 요약해서 설명한다.

    API 키가 설정되어 있지 않으면 안내 문구를 반환한다(예외를 던지지 않음).
    """
    api_key = _get_api_key()
    if not api_key:
        return (
            "⚠️ 이 기능을 쓰려면 Anthropic API 키가 필요합니다. "
            "`tools/app/.streamlit/secrets.toml`에 `ANTHROPIC_API_KEY = \"sk-ant-...\"` "
            "형태로 추가하거나, 환경변수 `ANTHROPIC_API_KEY`를 설정해주세요."
        )

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
    except anthropic.AuthenticationError:
        return "⚠️ API 키가 유효하지 않습니다. `ANTHROPIC_API_KEY` 설정을 확인해주세요."
    except anthropic.APIError as e:
        return f"⚠️ AI 해석 요청 중 오류가 발생했습니다: {e}"

    return "".join(block.text for block in response.content if block.type == "text")
