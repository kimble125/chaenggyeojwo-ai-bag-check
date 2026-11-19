"""알림 예약과 메시지 생성.

일정마다 두 번 알림: 전날 19:00(가방 싸기) · 당일 07:30(마지막 확인 + 날씨).
마감(deadline) 일정은 전날 19:00 · 당일 08:30.
메시지는 발송 시점에 만들어서 최신 날씨·체크 상태를 반영합니다.
"""
from datetime import date as Date, datetime, timedelta

from . import db

EVE_AT = "19:00"
MORNING_AT = {"event": "07:30", "deadline": "08:30", "etc": "07:30"}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def schedule_for_event(event_id: int):
    ev = db.get_event(event_id)
    if not ev:
        return
    d = Date.fromisoformat(ev["date"])
    plan = {
        "eve": f"{(d - timedelta(days=1)).isoformat()} {EVE_AT}",
        "morning": f"{d.isoformat()} {MORNING_AT.get(ev['kind'], '07:30')}",
    }
    now = now_str()
    with db.tx() as con:
        con.execute("DELETE FROM notifications WHERE event_id=? AND kind IN ('eve','morning') AND delivered_at IS NULL",
                    (event_id,))
        for kind, at in plan.items():
            if at > now:
                con.execute("INSERT OR IGNORE INTO notifications(event_id,kind,fire_at) VALUES(?,?,?)",
                            (event_id, kind, at))


def build_message(ev: dict, kind: str) -> tuple[str, str]:
    left = [i["name"] for i in ev["items"] if not i["checked"]]
    w = ev.get("weather") or {}
    wx = ""
    if w.get("status") == "ok":
        p = w.get("rain_prob_window") if w.get("rain_prob_window") is not None else w.get("rain_prob")
        wx = f" · {w['weather']}" + (f" {p}%" if p is not None else "")
        if w.get("pm10_grade"):
            wx += f" · 미세먼지 {max(w['pm10_grade'], w.get('pm25_grade') or '좋음', key=['좋음','보통','나쁨','매우나쁨'].index)}"
    gap = (Date.fromisoformat(ev["date"]) - Date.today()).days
    when = {0: "오늘", 1: "내일"}.get(gap, f"{ev['date'][5:].replace('-', '/')}")
    if ev["kind"] == "deadline":
        title = f"📮 {when}까지: {ev['title']}"
    else:
        title = f"🎒 {when} {ev['title']}{wx}"
    if left:
        body = "챙길 것: " + ", ".join(left)
    else:
        body = "준비물 모두 챙겼어요 👍"
    if kind == "morning" and ev.get("start_time"):
        body = f"{ev['start_time']} 시작 · " + body
    return title, body


def due_notifications() -> list[dict]:
    """fire_at 이 지난 미발송 알림을 꺼내 메시지를 채우고 발송 처리."""
    now = now_str()
    out = []
    with db.tx() as con:
        rows = con.execute(
            "SELECT * FROM notifications WHERE delivered_at IS NULL AND fire_at <= ? ORDER BY fire_at", (now,)
        ).fetchall()
    for r in rows:
        ev = db.get_event(r["event_id"])
        if not ev:
            continue
        if r["kind"] == "kid" and r["message"]:
            title, _, body = r["message"].partition("\n")
        else:
            title, body = build_message(ev, "eve" if r["kind"] == "eve" else "morning")
        with db.tx() as con:
            con.execute("UPDATE notifications SET delivered_at=?, message=? WHERE id=?",
                        (now, f"{title}\n{body}", r["id"]))
        out.append({"id": r["id"], "event_id": r["event_id"], "title": title, "body": body, "fire_at": r["fire_at"]})
    return out


def fire_test(event_id: int) -> dict | None:
    ev = db.get_event(event_id)
    if not ev:
        return None
    with db.tx() as con:
        con.execute("DELETE FROM notifications WHERE event_id=? AND kind='test'", (event_id,))
        con.execute("INSERT INTO notifications(event_id,kind,fire_at) VALUES(?, 'test', ?)", (event_id, now_str()))
    return {"ok": True}


def history(limit=30) -> list[dict]:
    with db.tx() as con:
        return [dict(r) for r in con.execute(
            "SELECT n.*, e.title AS event_title, e.date AS event_date FROM notifications n "
            "JOIN events e ON e.id=n.event_id ORDER BY n.fire_at DESC LIMIT ?", (limit,))]


def kid_report(event_id: int) -> dict | None:
    """아이가 '엄마에게 보여 주기'를 누르면 보호자 알림으로 결과를 보냄."""
    ev = db.get_event(event_id)
    if not ev:
        return None
    done = [i["name"] for i in ev["items"] if i["checked"]]
    left = [i["name"] for i in ev["items"] if not i["checked"]]
    title = f"🧒 아이가 가방을 쌌어요 · {ev['title']}"
    body = f"넣음 {len(done)} · 아직 {len(left)}" + (f" ({', '.join(left)})" if left else " — 다 챙겼어요!")
    with db.tx() as con:
        con.execute("DELETE FROM notifications WHERE event_id=? AND kind='kid'", (event_id,))
        con.execute("INSERT INTO notifications(event_id,kind,fire_at,message) VALUES(?, 'kid', ?, ?)",
                    (event_id, now_str(), f"{title}\n{body}"))
    return {"title": title, "body": body, "done": done, "left": left}
