"""가방쏙 일정을 바깥 캘린더(구글·애플·삼성 등)로 내보낸다. 계정 연결(OAuth) 없이 링크와 파일(.ics)로 넘긴다.

- entry(): 제목·메모(말투 3가지)·시작/끝·알림 시각을 한 묶음으로
- google_url(): 구글 캘린더의 '일정 만들기' 화면을 채워서 여는 주소(저장은 사람이 누른다)
- to_ics(): 캘린더 파일(RFC 5545). 알림은 전날 19:00, 당일 아침(본체 알림과 같은 시각)
시각은 한국 시간(UTC+9, 서머타임 없음)으로 보고 UTC 로 적는다.
"""
from __future__ import annotations

import urllib.parse
from datetime import date as Date, datetime, timedelta, timezone

from . import tone

KST = timedelta(hours=9)
EVE_AT = "19:00"
MORNING_AT = {"event": "07:30", "deadline": "08:30", "etc": "07:30"}


def _dt(day: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00")


def entry(view: dict, tone_key: str = "basic") -> dict:
    """달력에 넣을 한 건. view 는 service.view() 결과."""
    if tone_key not in tone.TONES:
        tone_key = "basic"
    title, body = tone.calendar_entry(view, tone_key)
    day, start, end = view["date"], view.get("start_time"), view.get("end_time")
    all_day = not start
    prev = (Date.fromisoformat(day) - timedelta(days=1)).isoformat()
    return {
        "tone": tone_key, "title": title, "description": body, "location": view.get("location") or "",
        "date": day, "all_day": all_day,
        "start": None if all_day else f"{day}T{start}:00+09:00",
        "end": None if all_day else f"{day}T{end or start}:00+09:00",
        "reminders": [
            {"at": f"{prev}T{EVE_AT}:00+09:00", "text": f"내일 {view['title']}: 가방 싸기"},
            {"at": f"{day}T{MORNING_AT.get(view.get('kind'), '07:30')}:00+09:00", "text": f"오늘 {view['title']}: 마지막 확인"},
        ],
    }


def _utc(local: datetime) -> str:
    return (local - KST).strftime("%Y%m%dT%H%M%SZ")


def _span(e: dict) -> tuple[datetime, datetime]:
    """시작과 끝(한국 시간). 하루 종일이면 그날 0시부터 다음 날 0시."""
    if e["all_day"]:
        s = _dt(e["date"], "00:00")
        return s, s + timedelta(days=1)
    s = datetime.fromisoformat(e["start"][:19])
    t = datetime.fromisoformat(e["end"][:19])
    return s, (t if t > s else s + timedelta(hours=1))


def google_url(e: dict) -> str:
    s, t = _span(e)
    dates = f"{s:%Y%m%d}/{t:%Y%m%d}" if e["all_day"] else f"{_utc(s)}/{_utc(t)}"
    q = {"action": "TEMPLATE", "text": e["title"], "dates": dates, "details": e["description"], "ctz": "Asia/Seoul"}
    if e["location"]:
        q["location"] = e["location"]
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(q)


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """한 줄을 75바이트 안으로 접는다(글자 중간은 자르지 않는다)."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 73:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    return "\r\n".join(out + [cur])


def _trigger(alarm: datetime, start: datetime) -> str:
    mins = int((alarm - start).total_seconds() // 60)
    sign, mins = ("-" if mins < 0 else ""), abs(mins)
    return f"{sign}PT{mins // 60}H{mins % 60}M" if mins % 60 else f"{sign}PT{mins // 60}H"


def to_ics(e: dict, uid: str, now: datetime | None = None) -> str:
    s, t = _span(e)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//gabangssok//bag-check//KO", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}"]
    if e["all_day"]:
        lines += [f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{t:%Y%m%d}"]
    else:
        lines += [f"DTSTART:{_utc(s)}", f"DTEND:{_utc(t)}"]
    lines += [f"SUMMARY:{_esc(e['title'])}", f"DESCRIPTION:{_esc(e['description'])}"]
    if e["location"]:
        lines.append(f"LOCATION:{_esc(e['location'])}")
    for r in e["reminders"]:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(r['text'])}",
                  f"TRIGGER:{_trigger(datetime.fromisoformat(r['at'][:19]), s)}", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def bundle(view: dict, tone_key: str = "basic") -> dict:
    """entry + 구글 주소 + 캘린더 파일 글."""
    e = entry(view, tone_key)
    return e | {"google_url": google_url(e), "ics": to_ics(e, f"gabangssok-{view['id']}-{view['date']}-{e['tone']}@gabangssok"),
                "filename": f"gabangssok-{view['date']}.ics"}
