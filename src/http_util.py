"""
HTTP 공통 — macOS 파이썬의 SSL 인증서 문제를 피한다.

python.org 설치판 파이썬(macOS)은 시스템 인증서를 쓰지 않아서
`urllib` 이 `CERTIFICATE_VERIFY_FAILED` 로 실패한다. 그러면 시세·뉴스·
KB Think 수집이 **조용히** 실패하고 폴백 데이터로 돈다 (발표 PC 에서 실제로
목 리포트가 쓰였다). `certifi` 는 openai/httpx 의존성으로 이미 깔려 있으므로
그 인증서 묶음을 쓰고, 없으면 기본 설정으로 둔다.
"""

import ssl
import urllib.request

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                                # noqa: BLE001
    _CTX = ssl.create_default_context()


def urlopen(req, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX)
