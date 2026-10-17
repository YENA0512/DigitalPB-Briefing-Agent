"""
시황 리포트 생성 — 실제 종가로 일간·주간·월간 목 리포트를 다시 쓴다.

## 왜 필요한가

`data/reports/*.md` 는 목데이터다. 예전 refresh 는 **날짜만** 오늘로 옮기고
본문은 그대로 뒀다. 그래서 "10/17 일간 리포트"가 10/13 의 "코스피 -3.39%"를
말하는 동안, 같은 evidence 안의 시세 Tool 은 그날 실제 값을 가져왔다.
근거 두 개가 서로 다른 숫자를 말하면 grounding 을 통과해도 고객 문구가 틀린다.

여기서는 리포트 본문의 **숫자를 전부 Yahoo Finance 종가에서 계산**한다.
시세 Tool(market_tool)과 같은 데이터 원천이므로 둘이 어긋나지 않는다.

## 규칙

- **Rule 로만 쓴다.** LLM 을 부르지 않는다 — 근거 문서가 생성물이면
  근거가 근거 노릇을 못 한다. 같은 종가면 같은 문장이 나온다
- **데이터에서 계산할 수 없는 사실은 쓰지 않는다.** 수급(외국인 순매수)이나
  업종 등락은 Yahoo 에 없으므로 문장에 넣지 않는다
- 날짜는 **실제 거래일**이다. 주말·휴장일 리포트는 만들지 않고,
  장이 아직 끝나지 않은 오늘은 포함하지 않는다
- 미래 단정·투자권유 표현을 쓰지 않는다 (CLAUDE.md 7절)
- 시세 조회가 실패하면 예외를 던진다. 호출부(refresh_demo)가 기존 파일을
  그대로 두고 경고만 남긴다 — 반쯤 쓴 리포트를 남기지 않는다

    python src/report_builder.py              # 오늘 기준으로 다시 생성
    python src/report_builder.py --dry-run    # 무엇을 쓸지만 출력
"""

import argparse
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import market_tool

REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"

#  목 리포트의 "원문 보기" 대상.
#  본문은 종가로 생성한 것이라 **특정 KB Think 글과 내용이 다르다.**
#  날짜만 맞춘 글 주소를 걸면 제목·내용과 다른 글이 열린다 (실제로 그랬다).
#  일간은 1분 브리핑 목록으로 보내고, 주간·월간은 링크를 비운다(클릭 불가로 렌더).
MOCK_DAILY_URL = "https://kbthink.com/investment/today-pick.html"
N_DAILY, N_WEEKLY = 5, 2

KR = ("^KS11", "^KQ11")
US = ("^GSPC", "^IXIC", "^SOX", "^VIX")
FX = "USDKRW=X"


# ---------------------------------------------------------------- 데이터

def _series(symbol: str, cutoff: date, drop_open: bool = True) -> list[tuple[date, float]]:
    """(거래소 현지 날짜, 종가) 목록. 끝나지 않은 오늘 봉과 cutoff 이후는 뺀다.

    환율은 24시간 거래라 "장 마감"이 없다. drop_open=False 로 오늘 봉을 남겨
    시세 Tool 이 보여주는 현재가와 같은 값을 쓴다.
    """
    res = market_tool._fetch(symbol, "6mo")["chart"]["result"][0]
    meta = res["meta"]
    off = meta.get("gmtoffset", 0)
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for ts, c in zip(res.get("timestamp", []), closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + off, timezone.utc).date()
        if d <= cutoff:
            out.append((d, float(c)))

    #  정규장이 아직 안 끝났으면 마지막 봉은 장중 값이다 — 종가가 아니다
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    if drop_open and out and reg.get("end") and time.time() < reg["end"]:
        today_local = datetime.fromtimestamp(reg["start"] + off, timezone.utc).date()
        if out[-1][0] == today_local:
            out.pop()
    return out


def load(cutoff: date) -> dict[str, list[tuple[date, float]]]:
    data = {s: _series(s, cutoff) for s in KR + US}
    data[FX] = _series(FX, cutoff, drop_open=False)
    if len(data["^KS11"]) < 30:
        raise RuntimeError("코스피 종가가 부족합니다 — 시세 조회 실패")
    return data


def _on(series, d: date) -> tuple[float, float] | None:
    """d 일의 (종가, 전일 대비 %)."""
    for i, (dd, c) in enumerate(series):
        if dd == d and i > 0:
            return c, (c / series[i - 1][1] - 1) * 100
    return None


def _on_or_before(series, d: date) -> tuple[date, float, float] | None:
    """d 이전 마지막 봉의 (날짜, 종가, 전일 대비 %). 환율처럼 봉 날짜가 국내와 어긋나는 지표용."""
    i = _at_or_before(series, d)
    if i is None or i == 0:
        return None
    return series[i][0], series[i][1], (series[i][1] / series[i - 1][1] - 1) * 100


def _last_before(series, d: date) -> int | None:
    """d 보다 앞선 마지막 거래일의 인덱스. 국내 장 전에 끝난 미국 세션을 찾는다."""
    idx = [i for i, (dd, _) in enumerate(series) if dd < d]
    return idx[-1] if idx else None


def _chg(series, i: int, back: int) -> float:
    return (series[i][1] / series[max(i - back, 0)][1] - 1) * 100


def _at_or_before(series, d: date) -> int | None:
    idx = [i for i, (dd, _) in enumerate(series) if dd <= d]
    return idx[-1] if idx else None


# ---------------------------------------------------------------- 문장 조각

def _dir(x: float, up="상승", down="하락") -> str:
    return "보합" if abs(x) < 0.05 else (up if x > 0 else down)


def _pct(x: float) -> str:
    return f"{abs(x):.2f}%"


def _sgn(x: float) -> str:
    return f"{x:+.2f}%"


def _md(d: date) -> str:
    return f"{d.month}월 {d.day}일"


def _ymd(d: date) -> str:
    return f"{d.year % 100:02d}{d.month:02d}{d.day:02d}"


def _week_tag(d: date) -> str:
    return f"{d.year % 100:02d}{d.month:02d}W{(d.day - 1) // 7 + 1}"


def _fx_effect(x: float) -> str:
    if abs(x) < 0.05:
        return ""
    if x < 0:
        return " 원화 강세는 해외자산을 원화로 환산할 때 평가액을 낮추는 방향으로 작용한다."
    return " 원화 약세는 해외자산을 원화로 환산할 때 평가액을 높이는 방향으로 작용한다."


def _frontmatter(**kv) -> str:
    body = "\n".join(f"{k}: {v}" for k, v in kv.items())
    return f"---\n{body}\nmock: true\nsource: Yahoo Finance 종가로 자동 생성 (report_builder.py)\n---\n\n"


# ---------------------------------------------------------------- 일간

def daily(data, d: date) -> tuple[str, str]:
    ks, kq = _on(data["^KS11"], d), _on(data["^KQ11"], d)
    ks_c, ks_x = ks
    kq_c, kq_x = kq if kq else (None, 0.0)

    paras = []
    p = f"{_md(d)} 코스피는 전일 대비 {_pct(ks_x)} {_dir(ks_x)}한 {ks_c:,.2f}에 마감했다."
    if kq:
        p += f" 코스닥은 {_pct(kq_x)} {_dir(kq_x)}한 {kq_c:,.2f}로 마감했다."
        if abs(kq_x) > abs(ks_x) + 0.5:
            p += " 코스닥의 변동폭이 코스피보다 컸다."
        elif abs(ks_x) > abs(kq_x) + 0.5:
            p += " 코스피의 변동폭이 코스닥보다 컸다."
    paras.append(p)

    sox = data["^SOX"]
    i = _last_before(sox, d)
    sp_x = sox_x = 0.0
    if i is not None:
        u = sox[i][0]
        sox_x, sox_1m = _chg(sox, i, 1), _chg(sox, i, 21)
        sp = _on(data["^GSPC"], u)
        nq = _on(data["^IXIC"], u)
        sp_x = sp[1] if sp else 0.0
        bits = []
        if sp:
            bits.append(f"S&P500은 {_sgn(sp[1])}")
        if nq:
            bits.append(f"나스닥은 {_sgn(nq[1])}")
        bits.append(f"필라델피아 반도체지수(SOX)는 {_sgn(sox_x)}")
        paras.append(f"직전 미국 거래일({u.month}/{u.day}) {', '.join(bits)}로 마감했다. "
                     f"SOX의 1개월 수익률은 {_sgn(sox_1m)}다.")

    fxr = _on_or_before(data[FX], d)
    fx = (fxr[1], fxr[2]) if fxr else None
    if fx:
        move = ("전일과 비슷한 수준이었다." if abs(fx[1]) < 0.05
                else f"전일 대비 {_pct(fx[1])} {_dir(fx[1])}했다.")
        paras.append(f"원/달러 환율은 {fx[0]:,.2f}원으로 {move}{_fx_effect(fx[1])}")

    #  해석 — 위 숫자에서 바로 따라 나오는 것만 쓴다
    notes = []
    if ks_x <= -1 and sox_x <= -1:
        notes.append("미국 반도체지수 약세와 국내 지수 하락이 같은 방향으로 나타났다. "
                     "반도체 비중이 높은 포트폴리오는 지수 하락률보다 큰 변동을 경험했을 수 있다.")
    elif ks_x >= 1 and sox_x >= 1:
        notes.append("미국 반도체지수 강세와 국내 지수 상승이 같은 방향으로 나타났다. "
                     "반도체 비중이 높은 포트폴리오는 지수 상승률보다 큰 변동을 경험했을 수 있다.")
    if abs(ks_x) >= 0.3 and abs(sp_x) >= 0.3 and (ks_x > 0) != (sp_x > 0):
        notes.append("국내와 미국 증시의 방향이 엇갈려, 보유자산의 지역 비중에 따라 "
                     "체감 수익률 차이가 컸을 수 있다.")
    if abs(ks_x) >= 2:
        notes.append(f"코스피의 하루 변동폭이 {_pct(ks_x)}로 평소보다 컸다.")
    elif abs(ks_x) < 0.5 and not notes:
        notes.append("지수 변동폭은 제한적이었다.")
    if notes:
        paras.append(" ".join(notes))

    title = (f"코스피 {_pct(ks_x)} {_dir(ks_x)}, {ks_c:,.0f}선 마감"
             if abs(ks_x) >= 0.05 else f"코스피 보합, {ks_c:,.0f}선 마감")
    summary = (f"코스피 {_sgn(ks_x)} · 코스닥 {_sgn(kq_x)}"
               + (f" · 원/달러 {_sgn(fx[1])}" if fx else "") + f" — {_md(d)} 국내 증시 정리.")
    fm = _frontmatter(doc=f"일간-{_ymd(d)}", title=title, date=d.isoformat(), period="daily",
                      region="국내",
                      url=MOCK_DAILY_URL,
                      summary=summary)
    return f"daily-{_ymd(d)}.md", fm + "\n\n".join(paras) + "\n"


# ---------------------------------------------------------------- 주간

def _week_end_index(series, monday: date) -> tuple[int, int] | None:
    """그 주 마지막 거래일 인덱스, 직전 주 마지막 거래일 인덱스."""
    end = _at_or_before(series, monday + timedelta(days=6))
    prev = _at_or_before(series, monday - timedelta(days=1))
    if end is None or prev is None or series[end][0] < monday:
        return None
    return end, prev


def weekly(data, monday: date) -> tuple[str, str]:
    ks = data["^KS11"]
    end, prev = _week_end_index(ks, monday)
    last = ks[end][0]
    wk = lambda s: (lambda r: (s[r[0]][1] / s[r[1]][1] - 1) * 100 if r else None)(
        _week_end_index(s, monday))

    ks_w, kq_w = wk(ks), wk(data["^KQ11"])
    sp_w, nq_w, sox_w = wk(data["^GSPC"]), wk(data["^IXIC"]), wk(data["^SOX"])
    fx_w = wk(data[FX])
    span = f"{monday.month}/{monday.day}~{last.month}/{last.day}"

    paras = []
    p = f"주간({span}) 기준 코스피는 {_pct(ks_w)} {_dir(ks_w)}했다."
    if kq_w is not None:
        p += f" 코스닥은 {_pct(kq_w)} {_dir(kq_w)}했다."
    paras.append(p)

    us = [f"S&P500 {_sgn(sp_w)}" if sp_w is not None else "",
          f"나스닥 {_sgn(nq_w)}" if nq_w is not None else "",
          f"필라델피아 반도체지수(SOX) {_sgn(sox_w)}" if sox_w is not None else ""]
    us = [u for u in us if u]
    if us:
        p = f"같은 주 미국 증시는 {', '.join(us)}로 마감했다."
        vix_i = _at_or_before(data["^VIX"], last)
        if vix_i is not None:
            p += f" 변동성지수(VIX)는 {data['^VIX'][vix_i][1]:.2f}로 마감했다."
        paras.append(p)
        if sp_w is not None and abs(ks_w) >= 0.5 and abs(sp_w) >= 0.5 and (ks_w > 0) != (sp_w > 0):
            paras.append("국내와 해외의 주간 방향이 갈렸다. 보유자산의 지역 비중에 따라 "
                         "체감 수익률 차이가 컸을 수 있다.")

    if fx_w is not None:
        fx_i = _at_or_before(data[FX], last)
        move = ("주간으로는 큰 변동이 없었다" if abs(fx_w) < 0.05
                else f"주간 {_pct(fx_w)} {_dir(fx_w)}했다")
        paras.append(f"원/달러 환율은 {data[FX][fx_i][1]:,.2f}원으로 "
                     f"{move}.{_fx_effect(fx_w)}")

    if sox_w is not None and abs(sox_w) > max(abs(sp_w or 0), abs(ks_w)) + 1:
        paras.append(f"반도체지수의 주간 변동폭({_sgn(sox_w)})이 주요 지수보다 컸다. "
                     "반도체 비중이 높은 포트폴리오는 지수와 다른 흐름을 보였을 수 있다.")

    n = (last.day - 1) // 7 + 1
    tag = _week_tag(last)
    title = f"{last.month}월 {n}주차 주간 금융시장 동향"
    summary = f"코스피 주간 {_sgn(ks_w)}" + (f" · S&P500 {_sgn(sp_w)}" if sp_w is not None else "") \
              + (f" · 원/달러 {_sgn(fx_w)}" if fx_w is not None else "") + f" ({span})."
    fm = _frontmatter(doc=f"주간-{tag}", title=title, date=last.isoformat(), period="weekly",
                      region="국내해외",
                      url="",
                      summary=summary)
    return f"weekly-{tag}.md", fm + "\n\n".join(paras) + "\n"


# ---------------------------------------------------------------- 월간 (House View)

#  자산배분 방향은 **하우스뷰(의견)** 이다. 시세에서 계산할 수 없으므로 고정 문단으로
#  두고, 시장 수치가 들어가는 문단만 종가로 다시 쓴다.
HOUSE_VIEW = [
    "{m}월 자산배분 방향은 위험자산 선호도를 전월 수준으로 유지한다. 주식 비중을 "
    "중립 대비 소폭 상위로 두되, 지역과 업종 분산을 강화할 것을 권고한다.",
    None,   # ← 국내 시장 수치 문단 (자동)
    "해외 주식은 비중 유지다. 미국 기술주 비중이 높아지면서 특정 업종 집중도가 "
    "높아진 상태다. 단일 업종 비중이 40%를 넘는 포트폴리오는 지수 방향과 무관한 "
    "변동을 겪을 수 있다.",
    "채권은 중립이다. 금리 인하 기대가 선반영된 구간으로 듀레이션 확대에는 "
    "신중할 것을 권고한다.",
    "환율은 변동성 확대에 대비한다. 해외자산 비중이 높은 경우 환헤지 여부를 "
    "점검할 시점이다.",
    "투자성향별 위험자산 권고 비중은 안정추구 20%, 위험중립 40%, 적극투자 60%, "
    "공격투자 75%를 기준으로 한다.",
]


def monthly(data, asof: date) -> tuple[str, str]:
    ks, kq = data["^KS11"], data["^KQ11"]
    i, j = _at_or_before(ks, asof), _at_or_before(kq, asof)
    ks_m, kq_m = _chg(ks, i, 21), _chg(kq, j, 21)
    p = f"국내 주식은 중립을 유지한다. 최근 1개월 코스피는 {_sgn(ks_m)}, 코스닥은 {_sgn(kq_m)}다."
    if (ks_m > 0) != (kq_m > 0) and min(abs(ks_m), abs(kq_m)) >= 1:
        p += " 두 지수의 방향이 갈려 단일 지수로 국내 증시를 설명하기 어려운 구간이다."
    elif abs(ks_m - kq_m) >= 3:
        p += " 두 지수의 수익률 차이가 커 단일 지수로 국내 증시를 설명하기 어려운 구간이다."

    m = asof.month
    paras = [x.format(m=m) if x else p for x in HOUSE_VIEW]
    tag = f"{asof.year % 100:02d}{m:02d}"
    fm = _frontmatter(doc=f"월간-{tag}", title=f"KB House View {asof.year}년 {m}월 — 위험자산 선호도 유지",
                      date=asof.replace(day=1).isoformat(), period="monthly", region="전체",
                      url="",
                      summary=f"{m}월 자산배분 방향 — 위험자산 선호도 유지, 지역·업종 분산 강화 권고.")
    return f"monthly-{tag}.md", fm + "\n\n".join(paras) + "\n"


# ---------------------------------------------------------------- 실행

def build(today: date | None = None) -> dict[str, str]:
    """{파일명: 내용}. 쓰지는 않는다."""
    today = today or date.today()
    data = load(today)
    ks = data["^KS11"]
    days = [d for d, _ in ks[-N_DAILY:]]
    last = days[-1]

    out = dict(daily(data, d) for d in reversed(days))
    monday = last - timedelta(days=last.weekday())
    for k in range(N_WEEKLY):
        out.update([weekly(data, monday - timedelta(weeks=k))])
    out.update([monthly(data, last)])
    return out


def write(files: dict[str, str]) -> list[str]:
    """기존 리포트를 지우고 새로 쓴다. build() 가 끝까지 성공한 뒤에만 부른다."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in REPORTS_DIR.glob("*.md"):
        if f.name not in files:
            f.unlink()
    for name, text in files.items():
        (REPORTS_DIR / name).write_text(text, encoding="utf-8")
    return sorted(files)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="실제 종가로 시황 목 리포트 생성")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default="", help="기준일 (기본 오늘)")
    args = ap.parse_args()
    files = build(date.fromisoformat(args.date) if args.date else None)
    if args.dry_run:
        for name, text in files.items():
            print(f"===== {name}\n{text}")
    else:
        for name in write(files):
            print(f"   {name}")
