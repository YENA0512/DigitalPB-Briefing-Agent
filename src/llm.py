"""
LLM 호출 래퍼 — 교육과정 방식(`init_chat_model` + `with_structured_output`).

## 규칙

- **예외를 밖으로 던지지 않는다.** 호출이 실패하면 `None` 과 사유를 돌려주고,
  호출부가 Rule 경로로 내려간다. 발표장에서 네트워크가 막혀도 데모가 돌아야 한다
- `USE_LLM=False` 면 애초에 호출하지 않는다
- 호출 횟수를 센다. "비용은?" 질문에 숫자로 답하기 위해서다
"""

from typing import Any

from pydantic import BaseModel, Field

import config

_llm = None
stats = {"calls": 0, "failures": 0, "by_purpose": {}}


# ---------------------------------------------------------------- 스키마

class AdviceOut(BaseModel):
    """문구 생성 결과."""
    advice: str = Field(description="상세조언 본문. 문장마다 출처 태그를 붙인다")
    tags: list[str] = Field(default_factory=list,
                            description="본문에서 사용한 출처 태그 (대괄호 없이)")
    reasoning: str = Field(default="", description="어떤 근거를 왜 골랐는지 한 줄")


class JudgeOut(BaseModel):
    """심사 결과."""
    passed: bool = Field(description="통과 여부")
    issues: list[str] = Field(default_factory=list,
                              description="반려 사유. 통과면 빈 리스트")
    reason: str = Field(default="", description="판정 근거 한 줄")


# ---------------------------------------------------------------- 호출

def available() -> bool:
    return config.USE_LLM and bool(config.OPENAI_API_KEY)


def _client():
    global _llm
    if _llm is None:
        from langchain.chat_models import init_chat_model
        _llm = init_chat_model(config.OPENAI_MODEL, model_provider="openai",
                               temperature=0, api_key=config.OPENAI_API_KEY)
    return _llm


def ask(schema: type[BaseModel], system: str, user: str,
        purpose: str = "generate") -> tuple[Any | None, str]:
    """구조화 출력 1회 호출. (결과, 사유) 를 반환한다. 예외를 던지지 않는다."""
    if not available():
        return None, "USE_LLM=False"

    stats["calls"] += 1
    stats["by_purpose"][purpose] = stats["by_purpose"].get(purpose, 0) + 1
    try:
        out = _client().with_structured_output(schema).invoke(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}])
        return out, "ok"
    except Exception as exc:                     # noqa: BLE001
        stats["failures"] += 1
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"


def reset_stats() -> None:
    stats["calls"] = 0
    stats["failures"] = 0
    stats["by_purpose"] = {}


def summary() -> str:
    by = " · ".join(f"{k} {v}" for k, v in sorted(stats["by_purpose"].items()))
    return f"LLM 호출 {stats['calls']}회 (실패 {stats['failures']}){' — ' + by if by else ''}"


if __name__ == "__main__":
    print("모델:", config.OPENAI_MODEL, "· 사용 가능:", available())
    out, why = ask(AdviceOut, "한 문장으로 답하라.",
                   "코스피가 전일 -3.39% 하락했다. [일간-261012] 태그를 달아 사실만 서술하라.")
    print("결과:", out.advice if out else f"실패 — {why}")
    print(summary())
