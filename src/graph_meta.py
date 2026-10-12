"""
그래프 메타 — 노드가 **무엇을 받아 무엇을 내보내는지** 한 곳에 적는다.

발표 평가 기준(교재 p20, Agent 설계 구체성 35점)이 이것이다.

> 우수: 입력·출력·State 칸·Node 구성·분기조건·Tool 목록이 모두 정의되어 있고,
> 각 Node 가 무엇을 받아 무엇을 내보내는지 흐름이 명확하며, **설계가 실제
> 구현과 일치한다.**

화면과 문서가 같은 출처를 보게 하려고 코드에 둔다. 주석으로만 적으면
구현이 바뀔 때 설명이 따라오지 않는다.
"""

#  Agent 입력 — initial_state() 가 받는 것. 이게 전부다.
INPUTS = [
    ("portfolio", "보유 자산",
     "종목명 · 비중 · 전일대비 증감액 · 지역, 평가액, 직전 접속일로부터 경과일수",
     "스타뱅킹 투자홈이 조회한 고객 자산 전문 (데모는 MOCK_PORTFOLIOS)"),
    ("profile", "투자성향",
     "WMTI · 연령대 · 위험성향 · 콘텐츠 난이도",
     "고객 프로파일"),
    ("recent_views", "최근 열람",
     "최근 본 콘텐츠의 해시태그",
     "KB Think 열람 이력"),
]

#  Agent 가 스스로 끌어오는 것 (입력이 아니라 Tool 조회 결과)
FETCHED = [
    ("시황 지표", "코스피 · 코스닥 · 원/달러 · SOX · S&P500 · 나스닥 · VIX",
     "Yahoo Finance (MCP: kb-market)"),
    ("시황 리포트", "일간 5 · 주간 2 · 월간 1 — 문단 단위 벡터 검색",
     "data/reports (InMemoryVectorStore)"),
    ("뉴스", "보유 종목 비중 순으로 섹터 어휘 번역 후 조회",
     "Google News RSS (MCP: kb-market)"),
    ("41케이스 원문", "현업이 쓴 케이스 문구 + 서비스 세트",
     "data/cases_41.json"),
    ("KB Think 콘텐츠", "50건 + 태그 19종",
     "data/kbthink_contents.json"),
]

#  노드 — (id, 단계, 표시명, 받는 것 → 내보내는 것, 한 줄 설명)
STAGES = {
    "diagnose": "① 진단",
    "search": "② 근거 수집 (병렬)",
    "generate": "③ 생성",
    "review": "④ 심사 (병렬)",
    "loop": "⑤ 분기",
    "final": "⑥ 확정",
}

NODES = {
    "diagnose": ("diagnose", "상황 진단",
                 "portfolio · profile → metrics · change_type · gap_type · case_id · market",
                 "수익률·비중·집중도를 계산하고 41케이스를 판정한다. 전부 Rule"),
    "search_daily": ("search", "일간 리포트",
                     "gap_type · 기여종목 → evidence[]", "문단 단위 유사도 검색"),
    "search_weekly": ("search", "주간 리포트", "동일 → evidence[]", "주간 동향"),
    "search_monthly": ("search", "월간 하우스뷰", "동일 → evidence[]", "자산배분 방향"),
    "search_market": ("search", "실시간 시황",
                      "region_used → evidence[]", "MCP kb-market · 지수·환율"),
    "search_news": ("search", "보유 종목 뉴스",
                    "holdings[].name → evidence[]", "MCP kb-market · 오늘 기사"),
    "generate": ("generate", "카드 선택 + 문구 생성",
                 "metrics · evidence · 41케이스 원문 → selected_card · draft",
                 "스코어링으로 카드를 고르고 LLM 이 문구를 쓴다"),
    "review_compliance": ("review", "컴플라이언스",
                          "draft → reviews[]", "Rule 금지어 1차 → LLM 2차 (회색지대)"),
    "review_grounding": ("review", "근거 결속",
                         "draft · evidence → reviews[]", "문장별 출처 태그 대조"),
    "review_format": ("review", "형식",
                      "draft → reviews[]", "글자수·문장수·슬롯·금액표기. 전부 Rule"),
    "aggregate": ("loop", "심사 종합", "reviews[] → 분기", "현재 회차만 본다"),
    "optimize": ("loop", "재작성",
                 "reviews[].issues → draft · revision+1", "지적사항을 반영해 다시 쓴다"),
    "fallback": ("loop", "폴백",
                 "case_id → draft", "3회 반려 시 41케이스 원본 문구로"),
    "match_contents": ("final", "콘텐츠 매칭",
                       "change_type · gap_type → contents[]", "루프 밖. 확정 문구 기준"),
    "human_review": ("final", "담당자 검수",
                     "draft → approval", "interrupt() — 승인 전엔 안 나간다"),
    "finalize": ("final", "카드 스펙 확정",
                 "state 전체 → card_spec", "대고객 표기로 변환해 JSON 출력"),
}

#  State 칸 — reducer 가 있는 칸이 왜 그런지가 설계의 핵심이다
STATE_FIELDS = [
    ("portfolio · profile · recent_views", "입력", "—"),
    ("metrics · change_type · gap_type · market · case_id", "진단 = 라우팅 키", "—"),
    ("evidence", "근거 — 검증 대상", "operator.add (병렬 fan-in)"),
    ("contents", "KB Think 링크 — 검증 대상 아님", "—"),
    ("selected_card · card_scores · selection_reason · draft", "생성 결과", "—"),
    ("reviews", "현재 회차 심사", "★ keep_latest_round"),
    ("review_history", "전 회차 누적 — 감사 추적", "operator.add"),
    ("revision", "재작성 횟수", "—"),
    ("approval", "담당자 검수 결과", "—"),
    ("card_spec · fallback_used", "출력", "—"),
    ("logs", "실행 로그", "operator.add"),
]


def stage_of(node: str) -> str:
    return NODES.get(node, ("", "", "", ""))[0]


def label_of(node: str) -> str:
    return NODES.get(node, ("", node, "", ""))[1]


def io_of(node: str) -> str:
    return NODES.get(node, ("", "", "", ""))[2]


def desc_of(node: str) -> str:
    return NODES.get(node, ("", "", "", ""))[3]


if __name__ == "__main__":
    print("Agent 입력")
    for key, name, detail, src in INPUTS:
        print(f"  {key:<14} {name:<10} {detail}")
        print(f"  {'':14} {'':10} ← {src}")
    print(f"\nAgent 가 스스로 끌어오는 것 ({len(FETCHED)}종)")
    for name, detail, src in FETCHED:
        print(f"  {name:<14} {detail}")
        print(f"  {'':14} ← {src}")
    print(f"\n노드 {len(NODES)}개")
    cur = None
    for nid, (stage, label, io, desc) in NODES.items():
        if stage != cur:
            cur = stage
            print(f"\n  {STAGES[stage]}")
        print(f"    {label:<16} {io}")
