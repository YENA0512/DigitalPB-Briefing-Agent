"""
설정 로딩 — .env 를 읽어 키와 플래그를 꺼낸다.

키가 없어도 죽지 않는다. 경고만 내고 USE_LLM 을 False 로 내린다.
발표장에서 네트워크가 막혀도 데모가 돌아야 하기 때문이다.

.env 는 저장소 루트에 둔다. 이 파일이 src/ 로 옮겨가도 찾을 수 있도록
__file__ 에서 위로 올라가며 찾는다. 실행 위치에 의존하지 않는다.
"""

import os
from pathlib import Path


def _find_dotenv() -> Path | None:
    """이 파일에서 위로 올라가며 .env 를 찾는다."""
    for parent in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def _load_dotenv(path: Path) -> None:
    """python-dotenv 가 있으면 쓰고, 없으면 직접 읽는다.

    로컬 파이썬에 의존성이 없는 경우가 있어 폴백을 둔다.
    이미 환경변수에 있는 값은 덮어쓰지 않는다 (셸 지정이 우선).
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


DOTENV_PATH = _find_dotenv()
if DOTENV_PATH:
    _load_dotenv(DOTENV_PATH)

# ---------------------------------------------------------------- 키

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
FMP_API_KEY = os.getenv("FMP_API_KEY", "")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# ---------------------------------------------------------------- 문구 길이

#  41케이스 원본의 13~74자 제한은 **현재 카드 UI 의 제약**이다.
#  채팅형 UI 로 가면서 생성 문구는 더 길게 쓴다. 폴백(원본 문구)에는
#  여전히 원본 제한이 적용된다 — 현업이 그 틀에서 쓴 문장이기 때문이다.
ADVICE_MIN_LEN = int(os.getenv("ADVICE_MIN_LEN", "40"))
ADVICE_MAX_LEN = int(os.getenv("ADVICE_MAX_LEN", "220"))
ADVICE_MAX_SENTENCES = int(os.getenv("ADVICE_MAX_SENTENCES", "6"))

# ---------------------------------------------------------------- 플래그

def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y", "on")


USE_LLM = _flag("USE_LLM", "false")

#  시황·뉴스 Tool 을 MCP 서버로 호출할지. 실패하면 자동으로 직접 호출로 떨어진다.
USE_MCP = _flag("USE_MCP", "true")

warnings: list[str] = []
if DOTENV_PATH is None:
    warnings.append(".env 를 찾지 못했습니다 (.env.example 을 복사해 만드세요)")
if USE_LLM and not OPENAI_API_KEY:
    warnings.append("OPENAI_API_KEY 가 없어 USE_LLM 을 False 로 내립니다")
    USE_LLM = False       # 죽지 않고 Rule 경로로 돈다

LANGFUSE_ENABLED = bool(LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY)
FMP_ENABLED = bool(FMP_API_KEY)


def mask(secret: str) -> str:
    """로그에 찍어도 되는 형태로 줄인다. 키 원문을 출력하지 않는다."""
    if not secret:
        return "(없음)"
    return f"{secret[:7]}…{secret[-4:]} ({len(secret)}자)"


def summary() -> str:
    lines = [
        f"  .env          : {DOTENV_PATH or '(없음)'}",
        f"  USE_LLM       : {USE_LLM}",
        f"  OPENAI_API_KEY: {mask(OPENAI_API_KEY)}",
        f"  모델          : {OPENAI_MODEL} / {OPENAI_EMBED_MODEL}",
        f"  문구 길이     : {ADVICE_MIN_LEN}~{ADVICE_MAX_LEN}자 · 최대 {ADVICE_MAX_SENTENCES}문장",
        f"  MCP           : {'사용' if USE_MCP else '미사용'} (실패 시 직접 호출)",
        f"  Langfuse      : {'사용' if LANGFUSE_ENABLED else '미사용'} · {LANGFUSE_HOST}",
        f"  FMP           : {'사용' if FMP_ENABLED else '미사용'}",
    ]
    for w in warnings:
        lines.append(f"  ⚠ {w}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("설정 확인")
    print(summary())
