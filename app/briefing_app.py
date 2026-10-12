"""
데모 앱 — Agent 를 실제로 돌리면서 고객 화면이 채워지는 것을 함께 보여준다.

## 왜 HTML 뷰어가 아니라 이 앱인가

최종발표 요건(2주차 교재 p18)은 **"실제 입력을 넣고 Agent가 실행되는 화면"** 을
필수로 요구한다. HTML 뷰어는 이미 만들어진 JSON 을 그리는 것이라 그 요건을
만족하지 못한다. 이 앱은 버튼을 누르면 **LangGraph 가 실제로 돌고**,
노드가 끝날 때마다 왼쪽 로그가 늘고 오른쪽 화면이 채워진다.

HTML 뷰어(`demo/viewer.html`)는 **백업**으로 남긴다 — 발표장에서 네트워크나
파이썬 환경이 막히면 그쪽을 연다.

## 실행

    ./run_local.sh app          # streamlit run

## 두 가지 모드

- **승인본 재생** — `output/approved/*.json` 을 읽어 즉시 그린다. LLM 호출 없음.
  실제 Runtime 과 같은 경로다 (고객 진입 시점에 모델을 부르지 않는다)
- **지금 생성** — 그래프를 실제로 실행한다. Batch 에서 일어나는 일이다
"""

import json
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import briefing_agent as ba          # noqa: E402
import config                        # noqa: E402
import followups                     # noqa: E402
import llm                           # noqa: E402

APPROVED = ROOT / "output" / "approved"

st.set_page_config(page_title="디지털PB 브리핑", page_icon="◆", layout="wide")

# ──────────────────────────────────────────────────────────── 스타일
#  실제 투자홈(asis.png) 기준 보라 팔레트. 상승=빨강 / 하락=파랑.
st.markdown("""<style>
.block-container{padding-top:1.6rem;max-width:1420px}
#MainMenu,footer,header{visibility:hidden}
:root{--pp:#6B4EFF;--pp-d:#5538E8;--pp-l:#EDE9FE;--pp-ll:#F6F3FF;
 --ink:#1C1A22;--ink2:#44414E;--gray:#8B8794;--line:#E8E5EF;
 --up:#E8453C;--down:#2B6CF6;--amber:#FFB800;--green:#12A150}

.phone{width:392px;margin:0 auto;border:1px solid var(--line);border-radius:22px;
 overflow:hidden;background:#fff;box-shadow:0 4px 22px rgba(28,26,34,.10)}
.sbar{height:28px;display:flex;align-items:center;justify-content:space-between;
 padding:0 16px;font-size:10.5px;color:var(--gray);font-weight:600}
.cbar{padding:11px 15px;display:flex;align-items:center;gap:10px;
 border-bottom:1px solid #F1EFF6;background:linear-gradient(180deg,#FBFAFF,#fff)}
.ava{width:30px;height:30px;border-radius:10px;background:linear-gradient(135deg,#6B4EFF,#9B7BFF);
 display:grid;place-items:center;color:#fff;font-size:14px;font-weight:700}
.cbar b{font-size:14px} .cbar i{font-size:10.5px;color:var(--green);font-style:normal;
 display:block;margin-top:2px;font-weight:600}
.chat{padding:14px 13px 18px;background:#FBFAFD;min-height:300px}

.b{border-radius:16px 16px 16px 4px;padding:13px 14px;font-size:13.5px;line-height:1.75;
 background:#fff;border:1px solid var(--line);margin-bottom:10px;
 box-shadow:0 1px 3px rgba(28,26,34,.04)}
.b.me{background:var(--ink);color:#fff;border-radius:16px 16px 4px 16px;
 margin-left:auto;width:fit-content;max-width:86%;border:none;font-size:13px}
.b.plain{background:#F3F1F8;border-color:transparent;box-shadow:none;width:fit-content}
.b.hero{background:linear-gradient(135deg,#F8F5FF,#fff);border-color:#E4DCFF}

.mh{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:800;color:var(--pp);
 margin-bottom:9px}
.mh .d{width:5px;height:5px;border-radius:50%;background:var(--pp)}
.mh .r{margin-left:auto;font-weight:600;color:#B5B1BE;font-size:10.5px}

.ig{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.ix{border:1px solid var(--line);border-radius:11px;padding:10px 11px;position:relative;
 overflow:hidden;background:#fff}
.ix::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:#8B8794}
.ix.up::before{background:var(--up)} .ix.down::before{background:var(--down)}
.ix .n{font-size:11px;color:var(--gray);font-weight:600;display:block}
.ix .v{font-size:15px;font-weight:800;display:block;margin:3px 0 1px;
 font-variant-numeric:tabular-nums}
.ix .c{font-size:11.5px;font-weight:700} .ix.up .c{color:var(--up)} .ix.down .c{color:var(--down)}
.ix.flat .c{color:var(--gray)}
.vt{display:inline-block;margin-top:9px;font-size:11.5px;padding:6px 10px;border-radius:7px;
 font-weight:700}
.vt.bad{background:#EEF4FF;color:var(--down)} .vt.good{background:#FFF1F0;color:var(--up)}
.vt.mid{background:#F1EFF6;color:var(--ink2)}

.cap{font-size:11.5px;color:var(--gray);font-weight:600}
.big{font-size:30px;font-weight:800;letter-spacing:-1.3px;display:block;margin:4px 0 2px;
 font-variant-numeric:tabular-nums}
.big.up{color:var(--up)} .big.down{color:var(--down)} .big.flat{color:var(--ink)}
.s2{font-size:11.5px;color:var(--ink2)}
.pr{display:flex;gap:5px;flex-wrap:wrap;margin-top:10px}
.pl{font-size:10.5px;font-weight:700;padding:4px 9px;border-radius:20px;background:#F1EFF6;
 color:var(--ink2)}
.pl.w{background:#FFF8E5;color:#8A6200} .pl.p{background:var(--pp-l);color:var(--pp-d)}

.mk{display:inline-block;background:var(--pp);color:#fff;font-size:10.5px;font-weight:800;
 width:17px;height:17px;line-height:17px;text-align:center;border-radius:50%;vertical-align:2px}

.hd{display:flex;align-items:center;gap:9px;font-size:12.5px;margin-bottom:9px}
.hd .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.hd .ba{width:58px;height:6px;background:#EDEBF2;border-radius:4px;overflow:hidden;flex:none}
.hd .ba i{display:block;height:100%;background:var(--pp);border-radius:4px}
.hd .ba i.hot{background:var(--amber)}
.hd .w{width:32px;text-align:right;color:var(--gray);font-size:11px;font-weight:600;flex:none}
.hd .dl{width:78px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums;flex:none}
.hd .dl.up{color:var(--up)} .hd .dl.down{color:var(--down)}

.pb{border-left:3px solid var(--pp);background:var(--pp-ll);border-radius:0 11px 11px 0;
 padding:12px 13px}
.pbi{display:flex;gap:9px;margin-bottom:10px} .pbi:last-child{margin-bottom:0}
.pbc{flex:none;width:21px;height:21px;border-radius:7px;background:#fff;display:grid;
 place-items:center;font-size:11px;border:1px solid #E0D9FF}
.pbt{font-size:12.5px;font-weight:800;line-height:1.5;display:block;margin-bottom:3px}
.pbd{font-size:11.5px;line-height:1.65;color:var(--ink2);display:block}
.pbd em{font-style:normal;font-weight:700;color:var(--pp-d)}

.cd{display:flex;gap:10px;padding:11px 12px;border:1px solid var(--line);border-radius:11px;
 background:#fff;text-decoration:none;color:inherit;margin-bottom:8px}
.cd:hover{border-color:var(--pp)}
.cn{flex:none;width:20px;height:20px;border-radius:50%;background:var(--pp);color:#fff;
 font-size:10.5px;font-weight:800;display:grid;place-items:center}
.cn.a{background:var(--amber);color:#4A3600}
.cb{min-width:0;display:flex;flex-direction:column;gap:4px}
.ck{display:block;font-size:10px;font-weight:800;color:var(--pp)} .ck.a{color:#8A6200}
.ct{display:block;font-size:12.5px;font-weight:700;line-height:1.52}
.cs{display:block;font-size:11.5px;line-height:1.65;color:var(--ink2)}
.cf{display:block;font-size:10.5px;color:#B5B1BE;font-weight:600}

.nr{display:flex;gap:9px;overflow-x:auto;padding-bottom:5px}
.nc{flex:none;width:196px;padding:11px 12px;border:1px solid var(--line);border-radius:11px;
 background:#fff;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:6px}
.nm2{display:block;font-size:9.5px;font-weight:800;color:var(--pp-d);background:var(--pp-l);
 padding:3px 7px;border-radius:5px;align-self:flex-start}
.nt{display:block;font-size:12px;font-weight:700;line-height:1.55;
 display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.np{display:block;font-size:10.5px;color:#B5B1BE;font-weight:600}
.cta{padding:13px;border-radius:11px;background:var(--pp);color:#fff;text-align:center;
 font-size:13.5px;font-weight:800;margin-top:2px}
.chipHint{font-size:11px;color:var(--gray);text-align:center;padding:4px 0 2px}
div[data-testid="stHorizontalBlock"] button{border-radius:18px!important;font-size:12.5px!important}
</style>""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────── 렌더 헬퍼
NAMES = {"personal_briefing": "개인 브리핑", "domestic_market": "시황",
         "fx": "환율", "content": "투자 콘텐츠"}


def won(n):
    return ("-" if n < 0 else "") + f"{abs(int(n)):,}원"


def dirk(v):
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def arrow(v):
    return "▲" if v > 0 else ("▼" if v < 0 else "―")


def spark(v):
    pts = "0,11 9,8 18,9 27,4 36,1" if v >= 0 else "0,1 9,4 18,3 27,8 36,11"
    c = "#E8453C" if v >= 0 else "#2B6CF6"
    return (f'<svg style="position:absolute;right:9px;top:9px;opacity:.5" width="36" height="12">'
            f'<polyline points="{pts}" stroke="{c}" stroke-width="1.6" fill="none" '
            f'stroke-linecap="round"/></svg>')


def blk_market(s):
    mk, dg = s.get("market", {}), s.get("diagnosis", {})
    rows = []
    for key, label in (("국내", "코스피"), ("해외", "S&P500")):
        v = mk.get(key, {})
        if v.get("change_1d") is not None:
            rows.append((label, None, v["change_1d"]))
    fx = mk.get("환율", {})
    if fx.get("price") is not None:
        rows.append(("원/달러", f"{round(fx['price']):,}", fx.get("change_1d", 0)))
    rows.append(("내 자산", None, s.get("metrics", {}).get("rate", 0)))

    cells = ""
    for n, v, c in rows:
        k = dirk(c)
        val = v if v else f"{c:+.2f}%"
        sub = (f"{arrow(c)} {abs(c):.2f}%" if v
               else {"up": "상승", "down": "하락", "flat": "보합"}[k])
        cells += (f'<div class="ix {k}">{spark(c)}<span class="n">{n}</span>'
                  f'<span class="v">{val}</span><span class="c">{sub}</span></div>')
    out = dg.get("outlook", "보통")
    cls = {"나쁨": "bad", "좋음": "good"}.get(out, "mid")
    return (f'<div class="b"><div class="mh"><span class="d"></span>오늘 시장'
            f'<span class="r">실시간 시세</span></div><div class="ig">{cells}</div>'
            f'<div class="vt {cls}">단기 전망 · {dg.get("outlook_region","국내")} {out}</div></div>')


def blk_delta(s):
    m, dg = s.get("metrics", {}), s.get("diagnosis", {})
    d = m.get("delta", 0)
    k = dirk(d)
    pills = (f'<span class="pl p">{dg.get("change_type","")}</span>'
             f'<span class="pl {"" if dg.get("gap_type")=="정합" else "w"}">{dg.get("gap_type","")}</span>')
    if m.get("max_weight"):
        pills += f'<span class="pl">최대비중 {round(m["max_weight"]*100)}%</span>'
    return (f'<div class="b hero"><div class="mh"><span class="d"></span>내 투자자산'
            f'<span class="r">전 거래일 대비</span></div>'
            f'<span class="cap">{dg.get("days_since",1)}일 전 방문 대비</span>'
            f'<span class="big {k}">{"+" if d>0 else ""}{won(d)}</span>'
            f'<span class="s2">평가액 {m.get("total",0):,}원 · {m.get("rate",0):+.2f}%</span>'
            f'<div class="pr">{pills}</div></div>')


def blk_advice(s):
    import re
    txt = re.sub(r"[①②③④⑤⑥⑦⑧⑨]",
                 lambda mm: f'<span class="mk">{mm.group()}</span>',
                 s.get("advice_display", ""))
    src = "gpt-5.5" if s.get("llm", {}).get("used") else "Rule 생성"
    return (f'<div class="b"><div class="mh"><span class="d"></span>무슨 일이 있었나요'
            f'<span class="r">{src}</span></div>'
            f'<div style="font-size:13.5px;line-height:1.82">{txt}</div></div>')


def blk_sources(s):
    if not s.get("sources"):
        return ""
    items = "".join(
        f'<a class="cd" href="{x.get("url","#")}" target="_blank">'
        f'<span class="cn">{x["marker"]}</span><span class="cb">'
        f'<span class="ck">{x["kind"]}</span>'
        f'<span class="ct">{x["title"]} ↗</span>'
        f'<span class="cs">{x.get("summary","")}</span>'
        f'<span class="cf">{x.get("publisher","")}'
        + (f' · {x["date"]}' if x.get("date") else "") + '</span></span></a>'
        for x in s["sources"])
    return (f'<div class="b"><div class="mh"><span class="d"></span>설명의 근거'
            f'<span class="r">눌러서 원문 보기</span></div>{items}</div>')


def blk_holdings(s):
    hs = sorted(s.get("contributions", []), key=lambda h: -abs(h["delta"]))
    rows = "".join(
        f'<div class="hd"><span class="nm">{h["name"]}</span>'
        f'<span class="ba"><i class="{"hot" if h.get("weight",0)>=.4 else ""}" '
        f'style="width:{round(h.get("weight",0)*100)}%"></i></span>'
        f'<span class="w">{round(h.get("weight",0)*100)}%</span>'
        f'<span class="dl {dirk(h["delta"])}">{"+" if h["delta"]>0 else ""}{won(h["delta"])}</span>'
        f'</div>' for h in hs)
    return (f'<div class="b"><div class="mh"><span class="d"></span>어느 자산이 움직였나'
            f'<span class="r">자체 계산</span></div>{rows}</div>')


def blk_pbpoints(s):
    dg, m = s.get("diagnosis", {}), s.get("metrics", {})
    top = max(s.get("contributions", []), key=lambda h: h.get("weight", 0), default=None)
    it = []
    if dg.get("gap_type") == "과편중" and top:
        it.append(("◉", f'한 종목에 {round(top["weight"]*100)}%가 몰려 있어요',
                   f'<em>{top["name"]}</em> 비중이 커서 이 업종이 움직이면 '
                   f'지수보다 큰 폭으로 반응해요.'))
    if dg.get("gap_type") == "과보수":
        it.append(("◐", "위험자산 비중이 하우스뷰 권고보다 낮아요",
                   "10월 하우스뷰는 위험중립 기준 위험자산 <em>40%</em>를 권고해요. "
                   "현재 구성은 현금성·채권 중심이에요."))
    if dg.get("gap_type") == "정합":
        mix = " · ".join(f'{k} <em>{round(v*100)}%</em>'
                         for k, v in (m.get("region_mix") or {}).items())
        it.append(("◉", "지역 분산이 균형 범위에 있어요",
                   f'{mix} 구성이에요. 하우스뷰 권고 범위와 큰 차이가 없어요.'))
    if dg.get("days_since", 0) >= 30:
        it.append(("⏱", f'<em>{dg["days_since"]}일</em> 만에 오셨어요',
                   "그동안 쌓인 변동을 한 번에 보시게 돼요. 기간을 나눠 보면 원인을 찾기 쉬워요."))
    if not it:
        return ""
    body = "".join(f'<div class="pbi"><span class="pbc">{i}</span><span>'
                   f'<span class="pbt">{t}</span><span class="pbd">{d}</span></span></div>'
                   for i, t, d in it[:3])
    return (f'<div class="b"><div class="mh"><span class="d"></span>제가 본 점검 포인트'
            f'<span class="r">자동 진단 · 권유 아님</span></div>'
            f'<div class="pb">{body}</div></div>')


def blk_fx(s):
    fx = s.get("market", {}).get("환율", {})
    ovs = (s.get("metrics", {}).get("region_mix") or {}).get("해외", 0)
    c = fx.get("change_1d", 0)
    msg = ("원화가 강해지면 달러자산을 원화로 바꾼 평가액은 줄어요."
           if c < 0 else "원화가 약해지면 달러자산 평가액은 늘어요.")
    return (f'<div class="b"><div class="mh"><span class="d"></span>환율 영향'
            f'<span class="r">실시간 시세</span></div>'
            f'<div style="font-size:13.5px;line-height:1.8">'
            f'원/달러는 <b>{round(fx.get("price",0)):,}원</b>으로 전일 '
            f'<b style="color:var(--{dirk(c)})">{c:+.2f}%</b> 움직였어요. {msg}<br>'
            f'고객님 해외 비중은 <b>{round(ovs*100)}%</b>라 환율이 함께 반영돼요. '
            f'환헤지 여부에 따라 체감이 달라요.</div></div>')


def blk_news(s):
    if not s.get("news"):
        return ""
    cards = "".join(
        f'<a class="nc" href="{n["url"]}" target="_blank">'
        f'<span class="nm2">{n.get("matched","시황")}</span>'
        f'<span class="nt">{n["title"]}</span>'
        f'<span class="np">{n.get("publisher","")}'
        + (f' · {n["date"]}' if n.get("date") else "") + '</span></a>'
        for n in s["news"])
    return (f'<div class="b"><div class="mh"><span class="d"></span>내 보유 종목 관련 오늘 기사'
            f'<span class="r">{len(s["news"])}건</span></div>'
            f'<div class="nr">{cards}</div></div>')


def blk_contents(s):
    if not s.get("contents"):
        return ""
    items = "".join(
        f'<a class="cd" href="{c.get("url","#")}" target="_blank">'
        f'<span class="cn a">＋</span><span class="cb">'
        f'<span class="ck a">{c.get("section","KB Think")}</span>'
        f'<span class="ct">{c["title"]} ↗</span>'
        f'<span class="cs">{c.get("summary","")}</span>'
        f'<span class="cf">KB Think'
        + (f' · {c["published"]}' if c.get("published") else "") + '</span></span></a>'
        for c in s["contents"])
    return (f'<div class="b"><div class="mh"><span class="d"></span>이어서 읽어볼 콘텐츠'
            f'<span class="r">상황 태그 매칭</span></div>{items}</div>')


def blk_cta(s):
    return (f'<div class="b"><div style="font-size:12px;color:var(--ink2);margin-bottom:9px">'
            f'{s.get("서브조언","")}</div>'
            f'<div class="cta">{s.get("버튼명","")} →</div></div>')


BLOCKS = {"market": blk_market, "delta": blk_delta, "advice": blk_advice,
          "sources": blk_sources, "holdings": blk_holdings, "pbpoints": blk_pbpoints,
          "fx": blk_fx, "news": blk_news, "contents": blk_contents, "cta": blk_cta}


def render_phone(spec, shown):
    html = ['<div class="phone">',
            '<div class="sbar"><span>9:41</span><span></span><span>▪▪ ▪</span></div>',
            '<div class="cbar"><div class="ava">◆</div><div><b>디지털PB</b>',
            '<i>● 오늘 시황 반영 완료 · 담당자 승인</i></div></div>',
            '<div class="chat">',
            '<div class="b me">오늘 내 투자자산 어때?</div>',
            '<div class="b plain">오늘 시장부터 같이 볼게요.</div>']
    for key in shown:
        fn = BLOCKS.get(key)
        if fn:
            html.append(fn(spec) or "")
    html.append('</div></div>')
    return "".join(html)


# ──────────────────────────────────────────────────────────── 상태
if "shown" not in st.session_state:
    st.session_state.shown = list(followups.DEFAULT_BLOCKS)
if "spec" not in st.session_state:
    st.session_state.spec = None

specs = {f.stem: f for f in sorted(APPROVED.glob("*.json"))}

# ──────────────────────────────────────────────────────────── 사이드바
with st.sidebar:
    st.markdown("### 디지털PB 브리핑")
    case = st.selectbox("고객 케이스", list(specs) or ["(없음)"])
    mode = st.radio("모드", ["승인본 재생 (Runtime)", "지금 생성 (Batch)"],
                    captions=["LLM 호출 없음 — 실제 고객 경로",
                              "그래프를 실제로 실행 — 전날 배치에서 일어나는 일"])
    go = st.button("▶ 실행", type="primary", use_container_width=True)
    if st.button("↺ 화면 초기화", use_container_width=True):
        st.session_state.shown = list(followups.DEFAULT_BLOCKS)
    st.divider()
    st.caption(f"모델 {config.OPENAI_MODEL} · USE_LLM={config.USE_LLM}")
    st.caption("Runtime 경로에는 LLM 호출이 없습니다. "
               "문구는 전날 Batch 에서 생성·3축 심사·담당자 승인을 거칩니다.")

st.markdown("## 디지털PB 브리핑 Agent")
st.caption("왼쪽에서 Agent 가 실행되고, 오른쪽 고객 화면이 그 결과로 채워집니다.")

left, right = st.columns([1.05, 1], gap="large")

# ──────────────────────────────────────────────────────────── 실행
if go and specs:
    st.session_state.shown = list(followups.DEFAULT_BLOCKS)
    if mode.startswith("승인본"):
        st.session_state.spec = json.loads(specs[case].read_text(encoding="utf-8"))
        with left:
            st.success("승인본 재생 — LLM 호출 0회. 실제 고객 진입 시 경로입니다.")
    else:
        with left:
            st.markdown("#### 그래프 실행")
            box, bar = st.container(), st.progress(0.0, "시작")
            llm.reset_stats()
            app = ba.build_graph()
            pf = ba.MOCK_PORTFOLIOS.get(case) or list(ba.MOCK_PORTFOLIOS.values())[0]
            seen, t0 = [], time.perf_counter()
            final = None
            for chunk in app.stream(ba.initial_state(pf),
                                    config={"configurable": {"thread_id": f"app-{case}"},
                                            "recursion_limit": 60},
                                    stream_mode="updates"):
                for node, upd in chunk.items():
                    seen.append(node)
                    bar.progress(min(len(seen) / 14, 1.0), f"{node}")
                    with box:
                        for line in (upd or {}).get("logs", []):
                            st.markdown(f"<span style='font-family:ui-monospace;font-size:11.5px'>"
                                        f"<b>{node}</b> · {line}</span>", unsafe_allow_html=True)
                    if (upd or {}).get("card_spec"):
                        final = upd["card_spec"]
            bar.progress(1.0, f"완료 {time.perf_counter()-t0:.1f}초")
            st.session_state.spec = final
            st.success(f"{len(seen)}개 노드 실행 · {time.perf_counter()-t0:.1f}초 · {llm.summary()}")

spec = st.session_state.spec

# ──────────────────────────────────────────────────────────── 화면
with right:
    if not spec:
        st.info("왼쪽 사이드바에서 케이스를 고르고 **실행**을 누르세요.")
    else:
        st.markdown(render_phone(spec, st.session_state.shown), unsafe_allow_html=True)
        chips = [c for c in followups.chips_for(spec)
                 if c["block"] not in st.session_state.shown]
        if chips:
            st.markdown('<div class="chipHint">궁금한 걸 눌러보세요</div>',
                        unsafe_allow_html=True)
            cols = st.columns(min(len(chips), 3))
            for i, c in enumerate(chips):
                if cols[i % len(cols)].button(c["label"], key=f"chip-{c['block']}",
                                              use_container_width=True):
                    st.session_state.shown.append(c["block"])
                    st.rerun()
        elif "cta" not in st.session_state.shown:
            st.session_state.shown.append("cta")
            st.rerun()

if spec:
    with left:
        st.markdown("#### 심사 결과")
        r = spec.get("review", {})
        cs = st.columns(4)
        for i, (k, ko) in enumerate([("compliance", "컴플라이언스"),
                                     ("grounding", "근거 결속"), ("format", "형식")]):
            v = r.get(k, {})
            cs[i].metric(ko, "통과" if v.get("passed") else "반려")
        cs[3].metric("재작성", f'{spec.get("review_rounds",1)-1}회')

        st.markdown("#### 카드 선택 — 랜덤 대신 스코어링")
        sc = spec.get("card_scores", {})
        if sc:
            st.bar_chart({NAMES.get(k, k): v for k, v in sc.items()}, height=170)
        st.caption(f"선택: **{NAMES.get(spec['card_type'], spec['card_type'])}** · "
                   f"제친 카드 {', '.join(NAMES.get(c, c) for c in spec.get('selected_over', []))}")
        st.caption(f"선택 이유: {spec.get('selection_reason','')}")

        with st.expander("실행 로그"):
            for l in spec.get("logs", []):
                st.text(l)
        with st.expander("카드 스펙 JSON (어드민 검수 화면이 받는 것)"):
            st.json({k: v for k, v in spec.items()
                     if k not in ("review_history", "evidence", "logs")})
