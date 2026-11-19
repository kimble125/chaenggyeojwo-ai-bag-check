"""모델 없이 알림장 글에서 일정과 준비물을 뽑는 규칙(예시 모드, API 키가 없을 때의 대체 길).

extract.py(모델)와 같은 모양을 돌려준다. 정해진 꼴("준비물 : …", "일시 : …")만 읽는다.
못 읽은 것은 지어내지 않고 notes 에 '확인해 주세요'로 남긴다.
"""
from __future__ import annotations

import re
from datetime import date as Date, timedelta

SAMPLES = [
    {
        "key": "a", "title": "2학년 가을 현장체험학습 안내", "posted": None,
        "text": "2학년 가을 현장체험학습 안내\n1. 일시 : {d1} 09:00–14:30\n2. 장소 : ○○숲체험원\n"
                "3. 준비물 : 도시락, 마실 물(플라스틱 물통), 개인용 돗자리, 모자, 간식, 물티슈, 개인 약품(멀미약 등 필요한 학생), 우천 시 우산 또는 우의 등\n"
                "4. 유의 사항 : 유리병·탄산음료와 장난감, 귀중품은 가져오지 않습니다. 간편한 복장과 운동화를 착용합니다.\n"
                "---- 절 취 선 ----\n참가 신청서({d0}까지 제출)",
    },
    {
        "key": "b", "title": "4학년 현장체험학습(역사박물관) 안내", "posted": None,
        "text": "4학년 현장체험학습(역사박물관) 안내\n1. 일시 : {d1}, 8시 40분까지 교실로 등교\n"
                "2. 준비물 : 필기도구(연필 2자루, 지우개), 체험학습 활동지(지난주에 나눠 준 것), 물통, 작은 가방(백팩) 등\n"
                "3. 선택 : 얇은 겉옷, 손수건\n4. 소요 경비 : 체험비 12,000원(학교 예산 지원)\n"
                " ※ 체험비에 점심 식사 포함(도시락 지참하지 않음)\n5. 교통카드는 필요 없습니다(전세버스 이용).",
    },
    {
        "key": "c", "title": "[1학년 3반 알림장]", "posted": None,
        "text": "[1학년 3반 알림장]\n1. 내일은 가을 소풍입니다. 체육복 입고 오기\n2. 준비물: 도시락, 물, 돗자리, 물티슈, 비닐봉지 2장\n"
                "3. 과자는 한 봉지만! 탄산음료 X\n4. 비가 오면 교실에서 합니다(준비물 같음)\n5. 가정통신문 회신서 내일까지 내기\n"
                "6. 멀미하는 친구는 멀미약 먹고 오기, 개인 약은 가방에",
    },
]
_OUTDOOR = re.compile(r"체험|소풍|숲|운동회|체육대회|탐사|농장|야외|공원|수련|캠프|썰매|갯벌")


def sample(key: str = "a", today: Date | None = None) -> dict:
    """지어낸 예시 알림장(실제 학교 문서 아님). 날짜는 오늘 기준으로 채운다."""
    today = today or Date.today()
    s = next((x for x in SAMPLES if x["key"] == key), SAMPLES[0])
    d1, d0 = today + timedelta(days=1), today
    fmt = lambda d: f"{d.month}월 {d.day}일"
    return {"title": s["title"], "posted": today.isoformat(), "attachments": [], "url": f"sample:{s['key']}",
            "text": s["text"].format(d1=fmt(d1), d0=fmt(d0))}


def split_items(chunk: str) -> list[str]:
    """쉼표로 나누되 괄호 안의 쉼표는 건드리지 않는다. 끝의 '등'은 뗀다."""
    out, buf, depth = [], "", 0
    for ch in chunk:
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth = max(0, depth - 1)
        if ch in ",、" and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    items = []
    for x in out:
        x = re.sub(r"\s+등\s*[.]?\s*$", "", x.strip()).strip(" .")
        if x and x != "등":
            items.append(x)
    return items


def _date(m: re.Match, base: Date) -> Date:
    d = Date(base.year, int(m.group(1)), int(m.group(2)))
    return d.replace(year=base.year + 1) if (base - d).days > 60 else d


def extract(text: str, title: str | None = None, posted: str | None = None, today: Date | None = None) -> dict:
    today = today or Date.today()
    try:
        base = Date.fromisoformat((posted or "").replace(".", "-")[:10]) if posted else today
    except ValueError:
        base = today
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return {"summary": "읽을 글이 없어요", "events": [], "usage": {"input": 0, "output": 0, "model": "규칙(모델 호출 없음)"}}
    ttl = re.sub(r"\s*안내\s*$", "", (title or lines[0]).strip("[] ")).strip() or "학교 일정"
    if "알림장" in ttl:                              # "[1학년 3반 알림장] 내일은 가을 소풍입니다" → "1학년 3반 가을 소풍"
        m = re.search(r"(?:내일은|내일|오늘은)\s*([가-힣 ]{2,14}?)\s*(?:입니다|이에요|예요|가는 날)", text)
        if m:
            ttl = (ttl.replace("알림장", "").strip() + " " + m.group(1).strip()).strip()
    md = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
    notes, when, start, end, loc = [], None, None, None, None
    for l in lines:
        if re.search(r"일시|날짜|언제", l) and md.search(l):
            when = _date(md.search(l), base)
            t = re.search(r"(\d{1,2}):(\d{2})\s*[–\-~]\s*(\d{1,2}):(\d{2})", l)
            if t:
                start, end = f"{int(t.group(1)):02d}:{t.group(2)}", f"{int(t.group(3)):02d}:{t.group(4)}"
            else:
                t = re.search(r"(\d{1,2})시\s*(\d{1,2})?분?", l)
                if t:
                    start = f"{int(t.group(1)):02d}:{int(t.group(2) or 0):02d}"
        if re.match(r"^[\d.\s]*장소", l):
            loc = re.split(r"[:：]", l, 1)[-1].strip()
        if re.search(r"유의|주의|※|비가 오면", l) and not re.match(r"^[\d.\s]*(준비물|선택)", l) and len(notes) < 3:
            notes.append(re.sub(r"^[\d.\s]*", "", l))
    if not when:
        if any("내일" in l for l in lines[:3]):
            when = base + timedelta(days=1)
        else:
            m = next((md.search(l) for l in lines if md.search(l) and not re.search(r"까지|제출|회신", l)), None)
            when = _date(m, base) if m else base + timedelta(days=1)
            if not m:
                notes.append("날짜를 못 찾아 내일로 넣었어요. 확인해 주세요.")
    items: list[str] = []
    for l in lines:
        if re.match(r"^[\d.\s]*(준비물|챙길 것|지참물)", l):
            items += split_items(re.split(r"[:：]", l, 1)[-1])
        elif re.match(r"^[\d.\s]*선택\s*[:：]", l):
            items += [f"{x}(선택)" for x in split_items(re.split(r"[:：]", l, 1)[-1])]
    for l in lines:                                   # '체육복 입고 오기'처럼 준비물 줄 밖에 있는 입고 갈 것
        m = re.search(r"([가-힣]{2,6})\s*(?:을|를)?\s*입고\s*오기", l)
        if m and not any(m.group(1) in i for i in items):
            items.append(f"{m.group(1)} 입고 오기")
    tgt = re.search(r"\d학년(?:\s*\d반)?", " ".join(lines[:2]))
    events = [{
        "title": ttl, "kind": "event", "date": when.isoformat(), "start_time": start, "end_time": end,
        "location": loc, "lat": None, "lon": None, "outdoor": bool(_OUTDOOR.search(" ".join(lines))) and not re.search(r"박물관|미술관|과학관|공연|실내|도서관", " ".join(lines)),
        "target": tgt.group(0) if tgt else None,
        "items": items, "ai_items": [], "notes": "\n".join(notes),
    }]
    for l in lines:                                   # 회신 마감은 따로 일정으로
        m = md.search(l)
        if m and re.search(r"까지\s*(제출|회신|내기)", l):
            events.append({"title": f"{ttl} 회신 마감", "kind": "deadline", "date": _date(m, base).isoformat(),
                           "start_time": None, "end_time": None, "location": None, "lat": None, "lon": None,
                           "outdoor": False, "target": None, "items": ["참가 신청서"], "ai_items": [], "notes": l})
    return {"summary": f"{ttl}: 준비물 {len(items)}개를 찾았어요 (규칙으로 읽은 예시 모드, 꼭 확인해 주세요)",
            "events": events, "usage": {"input": 0, "output": 0, "model": "규칙(모델 호출 없음)"}}
