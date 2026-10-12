"""
뷰어 빌드 — output/approved/*.json 을 viewer.html 에 인라인으로 박는다.

발표장에서 `file://` + `fetch()` 가 CORS 로 막히는 경우가 있다.
환경을 믿지 말고 단일 HTML 로 만든다.

    python demo/build_viewer.py          # output/approved → demo/viewer.html
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "demo" / "viewer.html"
TEMPLATE_SRC = ROOT / "demo" / "_viewer_template.html"
APPROVED = ROOT / "output" / "approved"

#  뷰어가 쓰지 않는 무거운 칸은 뺀다. 파일이 커지면 발표장 로딩이 느려진다.
DROP = {"review_history", "evidence"}


def main() -> int:
    #  최초 실행 시 현재 viewer.html 을 템플릿으로 보존한다
    if not TEMPLATE_SRC.exists():
        TEMPLATE_SRC.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")

    html = TEMPLATE_SRC.read_text(encoding="utf-8")
    if "__DATA__" not in html:
        print("템플릿에 __DATA__ 자리가 없습니다:", TEMPLATE_SRC)
        return 1

    #  뷰어는 **이름 붙은 데모 케이스**만 싣는다.
    #  배치가 CASE1~41 을 같은 폴더에 쌓으므로 전부 넣으면 300KB 가 되고
    #  발표에서 고르기도 어렵다. 배치 산출물은 통계·감사용이다.
    DEMO = ["반도체편중", "안정형과보수", "해외분산상승", "신규고객", "첫투자시작"]
    files = [APPROVED / f"{n}.json" for n in DEMO]
    files = [f for f in files if f.exists()] or sorted(APPROVED.glob("*.json"))[:5]

    specs = {}
    for f in files:
        spec = json.loads(f.read_text(encoding="utf-8"))
        #  현재 방식 비교용 — 41케이스 원본 문구를 같이 싣는다
        spec.setdefault("original_copy", "")
        specs[f.stem] = {k: v for k, v in spec.items() if k not in DROP}

    if not specs:
        print(f"카드 스펙이 없습니다: {APPROVED}")
        print("먼저 `./run_local.sh agent` 로 생성하세요.")
        return 1

    out = html.replace("__DATA__", json.dumps(specs, ensure_ascii=False, indent=1))
    TEMPLATE.write_text(out, encoding="utf-8")
    size = TEMPLATE.stat().st_size
    print(f"demo/viewer.html ← 케이스 {len(specs)}건 인라인 ({size / 1024:.0f}KB)")
    for name, s in specs.items():
        print(f"  {name:<14} {s['case_id']:<7} 출처 {len(s.get('sources', []))} · "
              f"뉴스 {len(s.get('news', []))} · 콘텐츠 {len(s.get('contents', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
