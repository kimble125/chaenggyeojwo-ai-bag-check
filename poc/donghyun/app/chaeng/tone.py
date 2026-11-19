"""달력·알림에 적는 글의 말투 틀. 숫자와 목록은 코드가 채우고 말투만 바뀐다(모델 호출 없음).

basic: 보통 말투 / cute: 귀엽게 / neat: 또박또박(모범생처럼)
"""
from __future__ import annotations

from datetime import date as Date

TONES = {
    "basic": {"label": "보통"},
    "cute": {"label": "귀엽게"},
    "neat": {"label": "또박또박"},
}


def _when(ev: dict) -> str:
    gap = (Date.fromisoformat(ev["date"]) - Date.today()).days
    return {0: "오늘", 1: "내일"}.get(gap, f"{int(ev['date'][5:7])}월 {int(ev['date'][8:10])}일")


def subject(name: str) -> str:
    """아이 이름에 주격 조사 붙이기: 하늘 → 하늘이가, 지우 → 지우가"""
    if not name:
        return "아이가"
    last = ord(name[-1])
    has_final = 0xAC00 <= last <= 0xD7A3 and (last - 0xAC00) % 28 != 0
    return name + ("이가" if has_final else "가")


def _names(items: list[dict], limit: int = 8) -> str:
    names = [i["name"] for i in items]
    return ", ".join(names[:limit]) + (f" 외 {len(names) - limit}개" if len(names) > limit else "")


def calendar_entry(ev: dict, tone: str = "basic") -> tuple[str, str]:
    """달력에 넣을 제목과 메모. ev 는 service.view() 결과."""
    req = [i for i in ev["items"] if not i.get("optional")]
    opt = [i for i in ev["items"] if i.get("optional") and not i.get("guardian")]
    ban = [f["name"] for f in ev.get("plus", {}).get("forbidden", [])]
    t = ev.get("start_time")
    grd = [i for i in ev["items"] if i.get("guardian")]           # 약처럼 보호자가 정할 것은 따로 적는다
    if tone == "cute":
        title = f"🎒 {ev['title']} 가는 날!"
        body = f"챙길 것 {len(req)}개: {_names(req)}"
        if opt:
            body += f"\n있으면 좋아요: {_names(opt, 4)}"
        if ban:
            body += f"\n이건 두고 가요 🙅 {', '.join(ban)}"
        if t:
            body += f"\n{t}까지 늦지 않게 출발~"
    elif tone == "neat":
        title = f"[준비물 {len(req)}] {ev['title']}"
        body = "\n".join(f"{n}. {i['name']}" for n, i in enumerate(req, 1))
        if opt:
            body += "\n(추천) " + _names(opt, 4)
        if ban:
            body += "\n(금지) " + ", ".join(ban)
        if t:
            body += f"\n(시작) {t}"
    else:
        title = f"{ev['title']} 준비물"
        body = f"준비물: {_names(req)}"
        if opt:
            body += f"\n추천: {_names(opt, 4)}"
        if ban:
            body += f"\n가져오지 않는 것: {', '.join(ban)}"
        if t:
            body += f"\n시작 {t}"
    if grd:
        body += f"\n보호자가 정할 것: {_names(grd, 3)}"
    return title, body


def kid_report(ev: dict, s: dict, profile: dict | None = None) -> tuple[str, str]:
    """아이가 가방을 싼 결과를 보호자 알림함에 남기는 글."""
    tone = (profile or {}).get("tone", "basic")
    who = subject((profile or {}).get("name") or "")
    left = f" ({', '.join(s['left'])})" if s["left"] else ""
    counts = f"준비물 {s['counted']} · 넣음 {s['packed']} · 아직 {len(s['left'])}{left}"
    if s["optional"]:
        counts += f" · 추천 {s['optional']} 중 {s['optional_packed']}"
    if s["open_alerts"]:
        counts += f" · 빼야 할 것: {', '.join(s['open_alerts'])}"
    if s["list_open"]:
        counts += " · 알림장 목록이 '등'으로 끝나요"
    if tone == "cute":
        title = f"🧒 {who} 가방 쌌어요! · {_when(ev)} {ev['title']}"
        body = ("다 챙겼지! 🎉 " if s["all_packed"] and not s["open_alerts"] else "") + counts
    elif tone == "neat":
        title = f"[가방 점검] {ev['title']} ({_when(ev)})"
        body = counts
    else:
        title = f"🧒 {who} 가방을 쌌어요 · {ev['title']}"
        body = counts
    return title, body
