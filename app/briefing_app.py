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
from langgraph.types import Command

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import briefing_agent as ba          # noqa: E402
import config                        # noqa: E402
import followups                     # noqa: E402
import case_labels                   # noqa: E402
import langfuse_api                  # noqa: E402
import tracing                       # noqa: E402
import graph_meta                    # noqa: E402
import llm                           # noqa: E402

APPROVED = ROOT / "output" / "approved"

st.set_page_config(page_title="디지털PB 브리핑", page_icon="◆", layout="wide")

# ──────────────────────────────────────────────────────────── 스타일
#  실제 투자홈(asis.png) 기준 보라 팔레트. 상승=빨강 / 하락=파랑.
st.markdown("""<style>
/*  다크모드 방어 — 카드 배경이 흰색으로 고정돼 있으므로 글자색도 고정한다.
    .streamlit/config.toml 로 라이트 테마를 강제하지만, 그 설정을 못 읽는
    실행 경로(`streamlit run` 외)에서도 글씨가 보여야 한다.  */
.stApp, .block-container{background:#fff!important;color:#1C1A22!important}
.block-container *:not(svg):not(path){color:inherit}
.block-container{padding-top:1.6rem;max-width:1420px}
#MainMenu,footer,header{visibility:hidden}
:root{--pp:#6B4EFF;--pp-d:#5538E8;--pp-l:#EDE9FE;--pp-ll:#F6F3FF;
 --ink:#1C1A22;--ink2:#44414E;--gray:#8B8794;--line:#E8E5EF;
 --up:#E8453C;--down:#2B6CF6;--amber:#FFB800;--green:#12A150}

.phone{width:392px;margin:0 auto;border:1px solid var(--line);border-radius:22px;
 overflow:hidden;background:#fff;color:var(--ink);box-shadow:0 4px 22px rgba(28,26,34,.10)}
.phone *{color:inherit}
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
 background:#fff;color:var(--ink);border:1px solid var(--line);margin-bottom:10px;
 box-shadow:0 1px 3px rgba(28,26,34,.04)}
.b.me{background:var(--ink);color:#fff;border-radius:16px 16px 4px 16px;
 margin-left:auto;width:fit-content;max-width:86%;border:none;font-size:13px}
.b.plain{background:#F3F1F8;color:var(--ink);border-color:transparent;box-shadow:none;
 width:fit-content}
.b.me,.b.me *{color:#fff!important}
.mk{color:#fff!important} .cn,.cn *{color:#fff!important} .cn.a,.cn.a *{color:#4A3600!important}
.cta,.cta *{color:#fff!important} .nm2{color:var(--pp-d)!important}
.ix .n,.cap,.s2,.cf,.np,.holdW,.hd .w{color:var(--gray)!important}
.cs,.pbd,.ck{color:var(--ink2)!important} .ck{color:var(--pp)!important}
.ck.a{color:#8A6200!important} .mh,.mh *{color:var(--pp)!important}
.mh .r{color:#B5B1BE!important}
.ix.up .c,.big.up,.hd .dl.up{color:var(--up)!important}
.ix.down .c,.big.down,.hd .dl.down{color:var(--down)!important}
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

.mk{display:inline-block;background:var(--pp);color:#fff!important;font-size:10.5px;
 font-weight:800;width:17px;height:17px;line-height:17px;text-align:center;
 border-radius:50%;vertical-align:2px;text-decoration:none!important;cursor:pointer}
a.mk:hover{background:var(--pp-d)}

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
.fold{border:1px dashed var(--line);border-radius:12px;padding:9px 12px;margin-bottom:10px;
 background:#F7F6FA;font-size:11.5px;color:var(--gray)!important;text-align:center}
.fold b{color:var(--ink2)!important;font-weight:700}

/* ── 왼쪽 패널 — 입력 / 실행 타임라인 ── */
.sec{font-size:13px;font-weight:800;color:var(--ink);margin:18px 0 9px;
 display:flex;align-items:center;gap:7px}
.sec .n{width:19px;height:19px;border-radius:6px;background:var(--pp);color:#fff!important;
 font-size:11px;display:grid;place-items:center;flex:none}
.sec .tail{margin-left:auto;font-size:11px;font-weight:600;color:var(--gray)}

.inbox{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff}
.inrow{display:flex;gap:11px;padding:11px 13px;border-bottom:1px solid var(--line2)}
.inrow:last-child{border-bottom:none}
.inkey{flex:none;width:104px;font-size:11.5px;font-weight:800;color:var(--pp)!important;
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.inval{min-width:0;font-size:12.5px;line-height:1.6;color:var(--ink)}
.inval b{font-weight:700}
.insrc{display:block;font-size:11px;color:var(--gray)!important;margin-top:3px}

.stage{margin:11px 0 0}
.stagehd{font-size:11.5px;font-weight:800;color:var(--pp)!important;margin-bottom:6px;
 display:flex;align-items:center;gap:6px}
.stagehd .par{font-size:10px;font-weight:700;background:var(--pp-l);color:var(--pp-d)!important;
 padding:2px 7px;border-radius:5px}
.nd{display:flex;gap:10px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;
 background:#fff;margin-bottom:6px}
.nd.run{border-color:var(--pp);background:var(--pp-ll)}
.nd.ok{border-left:3px solid var(--green)}
.nd.no{border-left:3px solid var(--up);background:#FFF7F6}
.ndic{flex:none;width:20px;height:20px;border-radius:6px;display:grid;place-items:center;
 font-size:11px;background:#F1EFF6;color:var(--ink2)!important;font-weight:800}
.nd.ok .ndic{background:var(--green-l,#EAF8F0);color:var(--green)!important}
.nd.no .ndic{background:#FBE9E9;color:var(--up)!important}
.ndb{min-width:0;flex:1}
.ndt{font-size:12.5px;font-weight:700;color:var(--ink);display:block}
.ndio{font-size:10.5px;color:var(--gray)!important;font-family:ui-monospace,Menlo,monospace;
 display:block;margin-top:2px;line-height:1.5;word-break:break-all}
.ndmsg{font-size:11.5px;color:var(--ink2)!important;display:block;margin-top:4px;line-height:1.55}
.ndt .ms{float:right;font-size:10.5px;color:var(--gray-l,#B5B1BE)!important;font-weight:600}

.modebox{border:1px solid var(--line);border-left:4px solid var(--pp);border-radius:10px;
 padding:12px 14px;background:var(--pp-ll);margin-bottom:4px}
.modet{font-size:13px;font-weight:800;color:var(--ink);display:block;margin-bottom:5px}
.moded{font-size:12px;line-height:1.7;color:var(--ink2)!important;display:block}
.moded b{color:var(--pp-d)!important}
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
    """문구 + 출처 마커.

    마커를 `<span>` 으로 두면 **눌러도 아무 일이 없다.** 고객이 ①을 누르는
    이유는 그 근거를 보려는 것이므로 실제 링크여야 한다.
    """
    import re
    url_of = {x["marker"]: x.get("url", "")
              for x in (s.get("sources") or []) if isinstance(x, dict)}

    def mark(mm):
        m = mm.group()
        u = url_of.get(m)
        if not u:
            return f'<span class="mk">{m}</span>'
        return (f'<a class="mk" href="{u}" target="_blank" rel="noopener" '
                f'title="출처 열기">{m}</a>')

    txt = re.sub(r"[①②③④⑤⑥⑦⑧⑨]", mark, s.get("advice_display", ""))
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


def render_phone(spec, shown, folded=0):
    """shown 은 블록 id 또는 (블록 id, 고객이 누른 질문) 쌍.

    질문 칩을 누르면 **그 질문이 말풍선으로 남습니다.** 답만 불쑥 나오면
    대화가 아니라 아코디언이 됩니다. 무엇을 물어서 나온 답인지 보여야
    "고객이 자유 입력 없이 대화한다"는 설계가 화면에서 읽힙니다.
    """
    html = ['<div class="phone">',
            '<div class="sbar"><span>9:41</span><span></span><span>▪▪ ▪</span></div>',
            '<div class="cbar"><div class="ava">◆</div><div><b>디지털PB</b>',
            '<i>● 오늘 시황 반영 완료 · 담당자 승인</i></div></div>',
            '<div class="chat">']
    if folded:
        #  질문을 거듭 누르면 화면이 길어진다. 앞부분을 접어 **방금 물은 것**이
        #  눈에 들어오게 한다. 실제 메신저가 하는 일이다.
        html.append(f'<div class="fold">↑ 이전 대화 <b>{folded}개</b> 접힘 — '
                    f'사이드바 <b>대화 펼치기</b>로 다시 볼 수 있어요</div>')
    else:
        html += ['<div class="b me">오늘 내 투자자산 어때?</div>',
                 '<div class="b plain">오늘 시장부터 같이 볼게요.</div>']
    for item in shown:
        key, asked = item if isinstance(item, (list, tuple)) else (item, None)
        if asked:
            html.append(f'<div class="b me">{asked}</div>')
        fn = BLOCKS.get(key)
        if fn:
            html.append(fn(spec) or "")
    html.append('</div></div>')
    return "".join(html)


def render_inputs(case_name):
    """Agent 가 **무엇을 받는지** 화면에 드러낸다.

    `ba.inputs_for()` 는 실행 경로가 쓰는 바로 그 함수다. 따로 만들면
    화면이 보여주는 것과 실제 입력이 갈린다.
    """
    i = ba.inputs_for(case_name)
    pf, prof, views = i["portfolio"], i["profile"], i["recent_views"]
    hs = sorted(pf.get("holdings", []), key=lambda h: -h.get("weight", 0))
    holding_txt = ("<br>".join(
        f"· {h['name']} <b>{round(h['weight'] * 100)}%</b> "
        f"{'+' if h['delta'] >= 0 else '−'}{abs(h['delta']):,}원 ({h['region']})"
        for h in hs) or "· (보유 자산 없음)")

    rows = [
        ("portfolio",
         f"평가액 <b>{pf.get('total', 0):,}원</b> · "
         f"직전 접속 <b>{pf.get('days_since', '-')}일 전</b> · "
         f"종목 <b>{len(hs)}개</b><br>{holding_txt}",
         "스타뱅킹 투자홈이 조회한 고객 자산 전문 (데모는 목데이터)"),
        ("profile",
         f"<b>{prof.get('risk', '')}</b> · {prof.get('age_band', '')} · "
         f"WMTI {prof.get('wmti', '')} · 콘텐츠 {prof.get('level', '')}",
         "고객 프로파일"),
        ("recent_views", " · ".join(views) or "(없음)", "KB Think 열람 이력"),
    ]
    html = '<div class="inbox">'
    for k, v, srcl in rows:
        html += (f'<div class="inrow"><span class="inkey">{k}</span>'
                 f'<span class="inval">{v}<span class="insrc">← {srcl}</span></span></div>')
    return html + "</div>"


def render_fetched():
    html = '<div class="inbox">'
    for name, detail, srcl in graph_meta.FETCHED:
        html += (f'<div class="inrow"><span class="inkey">{name}</span>'
                 f'<span class="inval">{detail}'
                 f'<span class="insrc">← {srcl}</span></span></div>')
    return html + "</div>"


MODE_DESC = {
    "지금 생성": ("① 전날 밤 18:00 — Batch",
                "장 마감 후 Agent 가 <b>41건을 다시 씁니다.</b> 지금 그래프가 "
                "실제로 돌고 LLM 을 부릅니다. 3축 심사를 통과한 것만 담당자에게 "
                "넘어갑니다. <b>고객은 이 장면을 보지 않습니다.</b>"),
    "담당자 검수": ("② 그날 밤 — 담당자 검수 (HITL)",
                 "<code>interrupt()</code> 로 그래프가 멈춥니다. "
                 "<b>승인 전에는 고객에게 나가지 않습니다.</b> 검수 단위는 고객이 "
                 "아니라 <b>케이스</b>라서, 1건 승인이 같은 유형 <b>약 3,000명</b>의 "
                 "화면을 바꿉니다."),
    "승인본 재생": ("③ 다음날 — 고객이 앱에 들어올 때 (Runtime)",
                 "승인된 JSON 을 그대로 그립니다. <b>LLM 호출 0회.</b> "
                 "금소법상 투자 문구는 사람 책임 하에 나가야 하므로 고객 요청 "
                 "시점에 모델을 부르지 않습니다. 고객이 늘어도 비용이 늘지 않습니다."),
}


def render_mode(mode_label):
    key = next((k for k in MODE_DESC if mode_label.startswith(k)), None)
    if not key:
        return ""
    t, d = MODE_DESC[key]
    return (f'<div class="modebox"><span class="modet">{t}</span>'
            f'<span class="moded">{d}</span></div>')


def node_card(node, msgs, ms=None, state="ok"):
    """실행된 노드 1개를 카드로. 로그 원문 대신 **무엇을 했는지**를 보여준다."""
    icon = {"ok": "✓", "no": "✕", "run": "●"}.get(state, "·")
    body = "<br>".join(msgs) if msgs else graph_meta.desc_of(node)
    ms_txt = f'<span class="ms">{ms:.1f}s</span>' if ms else ""
    return (f'<div class="nd {state}"><span class="ndic">{icon}</span>'
            f'<span class="ndb"><span class="ndt">{graph_meta.label_of(node)}{ms_txt}</span>'
            f'<span class="ndio">{graph_meta.io_of(node)}</span>'
            f'<span class="ndmsg">{body}</span></span></div>')


# ──────────────────────────────────────────────────────────── 상태
if "shown" not in st.session_state:
    st.session_state.shown = list(followups.DEFAULT_BLOCKS)
if "spec" not in st.session_state:
    st.session_state.spec = None
if "hitl" not in st.session_state:
    st.session_state.hitl = None
if "obs" not in st.session_state:
    st.session_state.obs = None
if "hitl_msg" not in st.session_state:
    st.session_state.hitl_msg = None
if "fold" not in st.session_state:
    st.session_state.fold = True        # 기본 접기 — 화면이 길어지는 것을 막는다

specs = {f.stem: f for f in sorted(APPROVED.glob("*.json"))}

# ──────────────────────────────────────────────────────────── 사이드바
with st.sidebar:
    st.markdown("### 디지털PB 브리핑")
    #  MOCK_PORTFOLIOS 의 이름이 곧 고객 유형이다. 어떤 상황인지 같이 보여준다.
    PF_DESC = {
        "반도체편중": "반도체 42% 집중 · 5일만에 방문 · 하락",
        "안정형과보수": "채권·MMF 100% · 40일만에 방문 · 변동 거의 없음",
        "해외분산상승": "해외 67% 분산 · 3일만에 방문 · 상승",
        "신규고객": "투자자산 없음 · 12일만에 방문",
        "첫투자시작": "첫 투자 · 1종목 100% · 2일만에 방문",
    }
    #  배치가 CASE1~41 을 같은 폴더에 쌓는다. 이름 붙은 데모 케이스를 앞에 두고,
    #  CASE* 는 cond 에서 뽑은 라벨을 붙여 무슨 상황인지 보이게 한다.
    all_names = list(specs) or ["(없음)"]
    named = [n for n in PF_DESC if n in all_names]
    rest = sorted([n for n in all_names if n not in PF_DESC],
                  key=lambda n: int(n[4:]) if n.startswith("CASE") and n[4:].isdigit()
                  else 999)
    names = named + rest

    def fmt(n):
        if n in PF_DESC:
            return f"{n} — {PF_DESC[n]}"
        lab = case_labels.label(n) if n.startswith("CASE") else ""
        return f"{n} — {lab}" if lab and lab != n else n

    case = st.selectbox("고객 케이스", names, format_func=fmt)
    st.caption(fmt(case).split(" — ", 1)[-1] if " — " in fmt(case) else "")
    mode = st.radio("모드", ["승인본 재생 (Runtime)", "지금 생성 (Batch)",
                            "담당자 검수 (HITL)"],
                    captions=["LLM 호출 없음 — 실제 고객 경로",
                              "그래프를 실제로 실행 — 전날 배치에서 일어나는 일",
                              "human_review 에서 멈춘 건을 승인·수정·반려"])
    go = st.button("▶ 실행", type="primary", use_container_width=True)
    auto_ok = st.checkbox(
        "검수 자동 승인", value=True,
        help="끄면 '지금 생성' 이 human_review 에서 멈추고 검수 화면으로 넘어갑니다")
    if st.button("↺ 화면 초기화", use_container_width=True):
        st.session_state.shown = list(followups.DEFAULT_BLOCKS)
        st.session_state.fold = True
    st.divider()
    st.caption(f"모델 {config.OPENAI_MODEL} · USE_LLM={config.USE_LLM}")
    st.caption(f"Langfuse {tracing.state()}")
    if tracing.enabled():
        #  대시보드는 **브라우저 세션이 키를 발급한 계정과 같아야** 열린다.
        #  다른 계정이면 Project Not Found 가 뜬다. 발표가 로그인 상태에
        #  걸리면 안 되므로 지표는 API 로 직접 읽어 아래에 띄운다.
        st.markdown(f"[Traces]({langfuse_api.project_url('/traces')}) ↗ · "
                    f"[Scores]({langfuse_api.project_url('/scores')}) ↗")
        st.caption("대시보드가 'Project Not Found' 면 브라우저 계정이 다른 것입니다. "
                   "아래 지표는 로그인 없이 API 로 읽습니다.")
        if st.button("관측 지표 새로고침", use_container_width=True):
            st.session_state.obs = None
        if st.session_state.get("obs") is None:
            with st.spinner("Langfuse 조회 중"):
                st.session_state.obs = {"sum": langfuse_api.summary(),
                                        "runs": langfuse_api.recent_runs(8),
                                        "health": langfuse_api.health()}
        obs = st.session_state.obs
        st.caption(f"프로젝트 {obs['health']}")
    st.caption("Runtime 경로에는 LLM 호출이 없습니다. "
               "문구는 전날 Batch 에서 생성·3축 심사·담당자 승인을 거칩니다.")

st.markdown("## 디지털PB 브리핑 Agent")
st.caption("왼쪽에서 Agent 가 실행되고, 오른쪽 고객 화면이 그 결과로 채워집니다.")

left, right = st.columns([1.12, 1], gap="large")

with left:
    st.markdown(render_mode(mode), unsafe_allow_html=True)
    st.markdown('<div class="sec"><span class="n">IN</span>Agent 입력'
                '<span class="tail">이 세 가지만 받습니다</span></div>',
                unsafe_allow_html=True)
    st.markdown(render_inputs(case), unsafe_allow_html=True)
    with st.expander("Agent 가 스스로 끌어오는 것 (입력이 아님)"):
        st.markdown(render_fetched(), unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────── 실행
if go and specs:
    st.session_state.shown = list(followups.DEFAULT_BLOCKS)
    st.session_state.hitl = None
    if mode.startswith("담당자"):
        #  interrupt 까지만 돌리고 멈춘다. 승인 전에는 card_spec 이 없다.
        from langgraph.types import interrupt  # noqa: F401  (문서용)
        app = ba.build_graph()
        cfg = {"configurable": {"thread_id": f"hitl-{case}-{int(time.time())}"},
               "recursion_limit": 60}
        with left:
            with st.spinner("그래프 실행 중 — human_review 에서 멈춥니다"):
                out = app.invoke(ba.initial_state_for(case), config=cfg)
        snap = app.get_state(cfg)
        if "card_spec" in out:
            st.session_state.spec = out["card_spec"]
        else:
            st.session_state.hitl = {
                "app": app, "cfg": cfg,
                "payload": snap.interrupts[0].value if snap.interrupts else {}}
            st.session_state.spec = None
    elif mode.startswith("승인본"):
        st.session_state.spec = json.loads(specs[case].read_text(encoding="utf-8"))
        with left:
            st.success("승인본 재생 — LLM 호출 0회. 실제 고객 진입 시 경로입니다.")
    else:
        with left:
            st.markdown('<div class="sec"><span class="n">▶</span>그래프 실행'
                        '<span class="tail">노드가 끝날 때마다 쌓입니다</span></div>',
                        unsafe_allow_html=True)
            bar = st.progress(0.0, "시작")
            stage_boxes = {}
            llm.reset_stats()
            app = ba.build_graph()
            cfg = {"configurable": {"thread_id": f"app-{case}-{int(time.time())}"},
                   "recursion_limit": 60, "callbacks": tracing.callbacks()}
            t0 = time.perf_counter()

            #  이 블록은 모듈 스코프다. 중첩 함수가 아니라서 nonlocal 을 쓸 수 없다.
            #  상태를 가변 홀더 하나에 담아 들고 다닌다.
            run = {"t": t0, "seen": [], "final": None}

            def draw(node, upd, now):
                """노드 1개를 단계 박스에 그린다."""
                stg = graph_meta.stage_of(node) or "final"
                if stg not in stage_boxes:
                    par = (' <span class="par">병렬</span>'
                           if stg in ("search", "review") else "")
                    st.markdown(
                        f'<div class="stagehd">{graph_meta.STAGES.get(stg, stg)}'
                        f'{par}</div>', unsafe_allow_html=True)
                    stage_boxes[stg] = st.container()
                msgs = list((upd or {}).get("logs") or [])
                rv = (upd or {}).get("reviews") or []
                kind = "no" if any(not r.get("passed") for r in rv) else "ok"
                with stage_boxes[stg]:
                    st.markdown(node_card(node, msgs, now - run["t"], kind),
                                unsafe_allow_html=True)
                run["t"] = now

            def run_stream(inp):
                """스트림을 돌며 그린다. interrupt 를 만나면 그 값을 돌려준다.

                `human_review` 가 `interrupt()` 를 걸면 LangGraph 는
                `{"__interrupt__": (Interrupt(...),)}` 를 흘린다. **튜플**이라
                노드 업데이트(dict)처럼 다루면 터진다.
                """
                stop = None
                for chunk in app.stream(inp, config=cfg, stream_mode="updates"):
                    for node, upd in chunk.items():
                        if node == "__interrupt__":
                            stop = (upd[0].value
                                    if isinstance(upd, (list, tuple)) and upd
                                    else upd)
                            continue
                        run["seen"].append(node)
                        bar.progress(
                            min(len(run["seen"]) / 16, 1.0),
                            f'{graph_meta.label_of(node)}  ({len(run["seen"])}/16)')
                        draw(node, upd, time.perf_counter())
                        if isinstance(upd, dict) and upd.get("card_spec"):
                            run["final"] = upd["card_spec"]
                return stop

            paused = run_stream(ba.initial_state_for(case))

            if paused is not None:
                if auto_ok:
                    #  검수 자동 승인 — 배치 장면을 끊지 않고 끝까지 보여준다
                    if "final" not in stage_boxes:
                        stage_boxes["final"] = st.container()
                    with stage_boxes["final"]:
                        st.markdown(node_card("human_review",
                                              ["검수 자동 승인 (데모)"], 0.0, "ok"),
                                    unsafe_allow_html=True)
                    run_stream(Command(resume={"action": "approve",
                                               "by": "배치 자동승인"}))
                else:
                    #  멈춘 상태 그대로 검수 화면으로 넘긴다
                    st.session_state.hitl = {"app": app, "cfg": cfg,
                                             "payload": paused}
                    st.session_state.spec = None

            el = time.perf_counter() - t0
            bar.progress(1.0, f"완료 {el:.1f}초")
            if run["final"]:
                st.session_state.spec = run["final"]
            c = st.columns(3)
            c[0].metric("노드 실행", f'{len(run["seen"])}개')
            c[1].metric("소요", f"{el:.1f}초")
            c[2].metric("LLM 호출", f"{llm.stats['calls']}회")
            st.caption(llm.summary())
            if st.session_state.hitl:
                st.warning("`human_review` 에서 멈췄습니다 — 아래에서 검수하세요.")

#  rerun 이 화면을 지우므로 메시지를 세션에 담았다가 한 번 띄운다.
if st.session_state.hitl_msg:
    kind, text = st.session_state.hitl_msg
    {"success": st.success, "warning": st.warning}.get(kind, st.info)(text)
    st.session_state.hitl_msg = None

spec = st.session_state.spec
hitl = st.session_state.hitl

# ──────────────────────────────────────────────────────────── 검수 화면
if hitl:
    p = hitl["payload"]
    rounds = hitl.get("rounds", [])          # [(회차, 반려된 문구, 사유)]
    with left:
        st.markdown("#### 담당자 검수 — 승인 전에는 고객에게 나가지 않습니다")
        st.caption("금소법상 투자 문구는 사람 책임 하에 노출되어야 합니다. "
                   "검수 단위는 고객이 아니라 **케이스**입니다 — "
                   "1건 승인이 같은 유형 약 3,191명의 화면을 바꿉니다.")

        rev = p.get("revision", 0)
        if rev:
            st.markdown(
                '<div class="modebox"><span class="modet">'
                f'재작성 {rev}회차 — 반려 사유를 반영해 다시 썼습니다</span>'
                f'<span class="moded">남은 기회 <b>{max(3 - rev, 0)}회</b>. '
                '3회를 넘기면 41케이스 <b>원본 문구로 폴백</b>합니다 — '
                '현업이 쓴 문장이라 컴플라이언스가 보증됩니다.</span></div>',
                unsafe_allow_html=True)

        if p.get("fallback_used"):
            st.markdown(
                '<div class="modebox" style="border-left-color:#E8453C;'
                'background:#FFF7F6"><span class="modet">'
                '폴백 — 41케이스 원본 문구로 교체했습니다</span>'
                '<span class="moded">재작성 3회로도 심사를 통과하지 못했습니다. '
                '현업이 쓴 문장이라 컴플라이언스가 보증됩니다. '
                '<b>생성이 실패해도 서비스는 죽지 않습니다.</b></span></div>',
                unsafe_allow_html=True)

        st.info(p.get("advice_display", p.get("advice", "")))
        c = st.columns(4)
        for n2, (k, ko) in enumerate([("compliance", "컴플라이언스"),
                                      ("grounding", "근거 결속"),
                                      ("format", "형식")]):
            v = (p.get("review") or {}).get(k, {})
            c[n2].metric(ko, "통과" if v.get("passed") else "반려")
        c[3].metric("재작성", f"{rev}회")
        st.caption(f"**{p.get('case_id')}** — {p.get('case_label', '')}")
        st.caption(f"진단 {p.get('change_type')} / {p.get('gap_type')} · "
                   f"근거 {[e['doc'] for e in p.get('evidence', [])]}")

        #  반려 → 재작성이 **무엇을 바꿨는지** 보여준다.
        #  회차 숫자만 올라가면 루프가 돌았다는 것만 알 뿐 효과를 확인할 수 없다.
        if rounds:
            with st.expander(f"반려 이력 {len(rounds)}건 — 무엇이 달라졌나",
                             expanded=True):
                for r_no, before, why in rounds:
                    st.markdown(f"**{r_no}회차 반려** · 사유: _{why}_")
                    st.caption(f"반려된 문구 — {before}")
                    st.divider()
                st.markdown(f"**현재 {rev}회차 문구**")
                st.caption(p.get("advice_display", ""))

        by = st.text_input("검수자", value="이예나")
        t1, t2, t3 = st.tabs(["승인", "수정 후 승인", "반려"])
        cmd = None
        with t1:
            if st.button("✓ 그대로 승인", type="primary",
                         use_container_width=True):
                cmd = {"action": "approve", "by": by}
        with t2:
            edited = st.text_area("문구 수정", value=p.get("advice", ""),
                                  height=120)
            st.caption("수정본은 **재심사하지 않습니다** — "
                       "사람이 쓴 문장이고 사람이 책임집니다.")
            if st.button("✎ 수정 후 승인", use_container_width=True):
                cmd = {"action": "edit", "by": by, "advice": edited}
        with t3:
            reason = st.text_input("반려 사유", placeholder="예) 수치 표현을 더 쉽게")
            st.caption("사유가 **재작성 지시**가 됩니다. revision+1 후 optimize 로 "
                       "돌아가 3축 심사를 다시 받고 여기로 옵니다.")
            #  반려 4번째가 폴백이다 (revision>=3 에서 반려 → fallback).
            #  버튼을 막으면 폴백 경로를 데모할 수 없다. 대신 라벨로 알린다.
            last = rev >= 3
            if st.button("✕ 반려 → 폴백" if last else "✕ 반려",
                         use_container_width=True,
                         type="secondary"):
                cmd = {"action": "reject", "by": by,
                       "reason": reason or "(사유 없음)"}
            if last:
                st.caption("재작성 기회를 모두 썼습니다. 여기서 반려하면 "
                           "**41케이스 원본 문구로 폴백**합니다 — "
                           "생성이 실패해도 서비스는 죽지 않습니다.")

        if cmd:
            if cmd["action"] == "reject":
                rounds = rounds + [(rev, p.get("advice_display", ""),
                                    cmd["reason"])]
            out = hitl["app"].invoke(Command(resume=cmd), config=hitl["cfg"])
            if "card_spec" in out:
                st.session_state.spec = out["card_spec"]
                st.session_state.hitl = None
                st.session_state.hitl_msg = (
                    ("warning", "3회 반려 — 41케이스 원본 문구로 폴백했습니다")
                    if out["card_spec"].get("fallback_used")
                    else ("success",
                          f"{cmd['action']} — 확정되어 고객 화면으로 내려갑니다"))
            else:
                snap = hitl["app"].get_state(hitl["cfg"])
                st.session_state.hitl = {
                    **hitl, "rounds": rounds,
                    "payload": snap.interrupts[0].value if snap.interrupts else {}}
                st.session_state.hitl_msg = (
                    "warning",
                    "반려 → optimize 로 돌아가 재작성했습니다. 다시 검수해 주세요.")
            st.rerun()

    with right:
        st.info("검수가 끝나면 고객 화면이 여기 뜹니다.")

# ──────────────────────────────────────────────────────────── 화면
if not hitl:
  with right:
      if not spec:
          st.info("왼쪽 사이드바에서 케이스를 고르고 **실행**을 누르세요.")
      else:
          #  질문 칩을 누르면 **앞부분이 자동으로 접힌다.** 토글로 두면
          #  고객이 설정을 만져야 하는 꼴이고, 실제 메신저는 그러지 않는다.
          #  칩을 누르는 순간 접혀야 한다. 2로 두면 세 번째부터 접혀서
          #  "눌렀는데 그대로"로 보인다.
          KEEP = 1
          items = st.session_state.shown
          base = len(followups.DEFAULT_BLOCKS)
          asked = items[base:]
          if st.session_state.fold and len(asked) > KEEP:
              folded, visible = base + len(asked) - KEEP, asked[-KEEP:]
          else:
              folded, visible = 0, items
          st.markdown(render_phone(spec, visible, folded), unsafe_allow_html=True)
          if folded:
              if st.button(f"↑ 이전 대화 {folded}개 펼치기", use_container_width=True):
                  st.session_state.fold = False
                  st.rerun()
          elif len(st.session_state.shown) > len(followups.DEFAULT_BLOCKS) + 2:
              if st.button("↓ 최근 대화만 보기", use_container_width=True):
                  st.session_state.fold = True
                  st.rerun()

          done = {i[0] if isinstance(i, (list, tuple)) else i
                  for i in st.session_state.shown}
          chips = [c for c in followups.chips_for(spec) if c["block"] not in done]
          if chips:
              st.markdown('<div class="chipHint">궁금한 걸 눌러보세요</div>',
                          unsafe_allow_html=True)
              cols = st.columns(min(len(chips), 3))
              for i, c in enumerate(chips):
                  if cols[i % len(cols)].button(c["label"], key=f"chip-{c['block']}",
                                                use_container_width=True):
                      st.session_state.shown.append((c["block"], c["label"]))
                      st.session_state.fold = True   # 새 답이 오면 앞을 접는다
                      st.rerun()
          elif "cta" not in done:
              st.session_state.shown.append("cta")
              st.rerun()

if spec and not hitl:
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
        st.caption(f"41케이스 판정: **{spec['case_id']}** — "
                   f"{spec.get('case_label', '')}")
        st.caption(f"선택: **{NAMES.get(spec['card_type'], spec['card_type'])}** · "
                   f"제친 카드 {', '.join(NAMES.get(c, c) for c in spec.get('selected_over', []))}")
        st.caption(f"선택 이유: {spec.get('selection_reason','')}")

        with st.expander("State 설계 — 칸과 reducer"):
            st.caption("fan-in 되는 칸에는 reducer 가 반드시 있어야 하고, "
                       "루프를 도는 칸은 operator.add 로는 비울 수 없습니다.")
            st.table({"State 칸": [f[0] for f in graph_meta.STATE_FIELDS],
                      "역할": [f[1] for f in graph_meta.STATE_FIELDS],
                      "reducer": [f[2] for f in graph_meta.STATE_FIELDS]})
        obs = st.session_state.get("obs")
        if obs and obs["sum"].get("metrics"):
            with st.expander(
                    f"관측 — 최근 {obs['sum']['scored_runs']}건 심사 품질 (Langfuse)",
                    expanded=False):
                st.caption("매일 41건을 돌리며 쌓습니다. "
                           "프롬프트를 고쳤을 때 **재작성 평균과 폴백 합계**가 "
                           "어떻게 움직이는지를 보는 것이 이 지표의 용도입니다.")
                m = obs["sum"]["metrics"]
                cols = st.columns(4)
                order = ["compliance_pass", "grounding_pass", "format_pass", "fallback"]
                for n3, key in enumerate(order):
                    v = m.get(key)
                    if not v:
                        continue
                    val = (f"{v['pass_rate']}%" if v["pass_rate"] is not None
                           else f"{v['sum']:g}건")
                    cols[n3].metric(v["label"], val)
                cols2 = st.columns(3)
                for n3, key in enumerate(["revisions", "llm_calls", "sources"]):
                    v = m.get(key)
                    if v:
                        cols2[n3].metric(f"{v['label']} 평균", v["avg"])
                if obs["runs"]:
                    st.caption("최근 실행")
                    st.table({
                        "시각": [r["at"][5:] for r in obs["runs"]],
                        "케이스": [r["name"] for r in obs["runs"]],
                        "관측": [r["observations"] for r in obs["runs"]],
                        "점수": [r["scores"] for r in obs["runs"]],
                        "초": [r["latency"] for r in obs["runs"]],
                    })

        logs = spec.get("logs") or []
        with st.expander(f"실행 로그 원문 ({len(logs)}줄)"):
            if logs:
                st.code("\n".join(logs), language=None)
            else:
                st.caption("로그가 없습니다. 승인본이 예전 형식일 수 있습니다 — "
                           "`./run_local.sh batch -- --auto-approve --limit 5` 로 "
                           "다시 생성하세요.")
        if spec.get("trace_url"):
            st.markdown(f"🔎 [Langfuse 에서 이 실행 보기]({spec['trace_url']})")
            st.caption("LLM 호출별 프롬프트·응답·토큰과 심사 점수 7종이 기록돼 있습니다.")
        with st.expander("카드 스펙 JSON (어드민 검수 화면이 받는 것)"):
            st.json({k: v for k, v in spec.items()
                     if k not in ("review_history", "evidence", "logs")})
