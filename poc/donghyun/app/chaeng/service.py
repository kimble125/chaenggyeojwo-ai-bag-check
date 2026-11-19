"""챙겼지 추가 기능의 저장과 계산. 웹 서버 종류와 상관없이 쓴다(FastAPI 라우터, 예시 서버 둘 다 여기를 부른다).

같은 SQLite 파일에 표 네 개를 더한다. 알림장 전문과 사진은 저장하지 않는다(항목이 나온 줄만 근거로 남긴다).
"""
from __future__ import annotations

import json
from datetime import datetime

from .. import db
from . import guard, recommend, tone

SCHEMA = """
CREATE TABLE IF NOT EXISTS plus_item (item_id INTEGER PRIMARY KEY, meta TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plus_event (event_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plus_sticker (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, sticker TEXT NOT NULL,
  message TEXT, giver TEXT NOT NULL DEFAULT '엄마', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plus_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
OPTIONAL_SOURCES = ("ai", "weather")          # 자동으로 붙은 추천. 안 넣어도 '다 챙겼지'를 막지 않는다
STICKERS = ["⭐", "👍", "💪", "🌈", "🏅", "💜"]
TRAITS = [(p["trait"], p["label"]) for p in recommend.load().get("personal", [])]
DEFAULT_PROFILE = {"name": "", "grade": None, "traits": [], "always": [], "tone": "basic"}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def init():
    with db.tx() as con:
        con.executescript(SCHEMA)
    sweep()


# ---------- 작은 저장소 ----------
def _kv_get(key: str, default):
    with db.tx() as con:
        row = con.execute("SELECT value FROM plus_kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def _kv_set(key: str, value):
    with db.tx() as con:
        con.execute("INSERT INTO plus_kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)))


def get_profile() -> dict:
    return DEFAULT_PROFILE | _kv_get("profile", {})


def set_profile(body: dict) -> dict:
    known = {t for t, _ in TRAITS}
    p = get_profile()
    if "name" in body:
        p["name"] = str(body["name"] or "")[:12]
    if "grade" in body:
        p["grade"] = int(body["grade"]) if str(body["grade"] or "").isdigit() else None
    if "traits" in body:
        p["traits"] = [t for t in (body["traits"] or []) if t in known]
    if "always" in body:
        p["always"] = [str(x).strip()[:12] for x in (body["always"] or []) if str(x).strip()][:6]
    if "tone" in body and body["tone"] in tone.TONES:
        p["tone"] = body["tone"]
    _kv_set("profile", p)
    return p


def _event_data(eid: int) -> dict:
    with db.tx() as con:
        row = con.execute("SELECT data FROM plus_event WHERE event_id=?", (eid,)).fetchone()
    base = {"forbidden": [], "not_needed": [], "list_open": False, "declined": [], "flagged": [], "removed": [],
            "returned": [], "analyzed": False}
    return base | (json.loads(row["data"]) if row else {})


def _event_save(eid: int, data: dict):
    with db.tx() as con:
        con.execute("INSERT INTO plus_event(event_id,data) VALUES(?,?) ON CONFLICT(event_id) DO UPDATE SET data=excluded.data",
                    (eid, json.dumps(data, ensure_ascii=False)))


def _meta_all(item_ids: list[int]) -> dict[int, dict]:
    if not item_ids:
        return {}
    with db.tx() as con:
        rows = con.execute(f"SELECT item_id, meta FROM plus_item WHERE item_id IN ({','.join('?' * len(item_ids))})",
                           item_ids).fetchall()
    return {r["item_id"]: json.loads(r["meta"]) for r in rows}


def _meta_save(item_id: int, meta: dict):
    with db.tx() as con:
        con.execute("INSERT INTO plus_item(item_id,meta) VALUES(?,?) ON CONFLICT(item_id) DO UPDATE SET meta=excluded.meta",
                    (item_id, json.dumps(meta, ensure_ascii=False)))


# ---------- 알림장 분석 ----------
def analyze(eid: int, text: str) -> dict | None:
    """알림장 글에서 금지·조건·근거를 뽑아 일정에 붙인다. 글 자체는 저장하지 않는다."""
    ev = db.get_event(eid)
    if not ev:
        return None
    notice_items = [i for i in ev["items"] if i["source"] in ("notice", "user")]
    res = guard.analyze(text or "", [i["name"] for i in notice_items])
    for it in notice_items:
        _meta_save(it["id"], res["items"][it["name"]])
    data = _event_data(eid)
    data |= {"forbidden": res["forbidden"], "not_needed": res["not_needed"], "list_open": res["list_open"],
             "analyzed": bool((text or "").strip())}       # 글 없이 부르면 '아직 확인 못 함'으로 남는다
    _event_save(eid, data)
    return view(eid)


# ---------- 화면에 주는 묶음 ----------
def view(eid: int) -> dict | None:
    """일정 + 항목별 표시 + 금지 + 추천 + 스티커 + 집계."""
    ev = db.get_event(eid)
    if not ev:
        return None
    data = _event_data(eid)
    metas = _meta_all([i["id"] for i in ev["items"]])
    banned = [f["name"] for f in data["forbidden"] + data["not_needed"]]
    rec = recommend.recommend(ev, get_profile(), _kv_get("forgot", {}), data["declined"], exclude=banned)
    for it in ev["items"]:
        m = metas.get(it["id"])
        if m is None:                                    # 분석 전이거나 나중에 더한 항목: 이름만으로 표시를 만든다
            m = guard.annotate(it["name"], "", data["forbidden"])
        it["meta"] = m
        it["optional"] = it["source"] in OPTIONAL_SOURCES or bool(m.get("optional_by_notice"))
        it["guardian"] = it["blocked"] = False
        if m.get("guardian") or m.get("conditional") == "needed" or recommend.is_medicine(it["name"]):
            it["optional"] = it["guardian"] = True       # 약과 "필요한 학생만": 보호자가 정한다. 아이 미션에는 넣지 않는다
        elif m.get("conditional") == "rain":             # "우천 시": 비 소식이 있을 때만 세는 준비물
            it["optional"] = "rain" not in rec["flags"]
        if any(recommend.same(it["name"], n) for n in banned):
            if it["source"] in ("ai", "weather", "recommend"):
                it["blocked"] = it["optional"] = True    # 자동 추천이 통신문의 금지와 겹치면 아이에게 보이지 않는다
            else:
                it["conflict"] = True                    # 통신문 준비물이 금지와 겹치면 지우지 않고 보호자에게 알린다
    alerts = [f | {"flagged": f["name"] in data["flagged"], "removed": f["name"] in data["removed"]} for f in data["forbidden"]]
    ev["plus"] = {
        "analyzed": data["analyzed"], "list_open": data["list_open"], "forbidden": alerts,
        "not_needed": data["not_needed"], "scenario": rec["scenario"], "flags": rec["flags"],
        "often_forbidden": rec["often_forbidden"] if not alerts else [],
        "recs": [r for r in rec["recs"] if not r["guardian_decides"]],
        "guardian_recs": [r for r in rec["recs"] if r["guardian_decides"]],
        "watch": rec["watch"], "stickers": stickers(eid), "returned": data["returned"],
        "summary": summarize(ev, data),
    }
    return ev


def summarize(ev: dict, data: dict) -> dict:
    """세는 항목(알림장·직접·받아들인 추천)과 선택·자동 추천을 나눠 센다. view() 가 optional 을 붙인 뒤에 부른다."""
    req = [i for i in ev["items"] if not i.get("optional")]
    opt = [i for i in ev["items"] if i.get("optional") and not i.get("blocked") and not i.get("guardian")]
    left = [i["name"] for i in req if not i["checked"]]
    open_alerts = [n for n in data["flagged"] if n not in data["removed"]]      # 사진에 보였는데 아직 안 뺀 것만 막는다
    return {
        "counted": len(req), "packed": len(req) - len(left), "left": left,
        "optional": len(opt), "optional_packed": sum(1 for i in opt if i["checked"]),
        "optional_left": [i["name"] for i in opt if not i["checked"]],
        "open_alerts": open_alerts, "list_open": data["list_open"],
        "all_packed": bool(req) and not left,
        "can_finish": bool(req) and not left and not open_alerts,     # '다 챙겼지'를 말해도 되는가
    }


# ---------- 추천 받아들이기 ----------
def accept_rec(eid: int, name: str) -> dict | None:
    v = view(eid)
    if not v:
        return None
    rec = next((r for r in v["plus"]["recs"] + v["plus"]["guardian_recs"] if r["name"] == name), None)
    if rec:
        iid = db.add_item(eid, rec["name"], source="recommend", reason=f"{rec['why']} · {rec['basis']}")
        _meta_save(iid, guard.annotate(rec["name"]) | {"kind": rec["kind"], "emoji": rec["emoji"], "group": rec["group"],
                                                       "guardian": rec["guardian_decides"]})
    return view(eid)


def decline_rec(eid: int, name: str) -> dict | None:
    data = _event_data(eid)
    if name not in data["declined"]:
        data["declined"].append(name)
        _event_save(eid, data)
    return view(eid)


def flag_forbidden(eid: int, names: list[str]):
    """사진에서 가져오면 안 되는 것이 보였다고 적어 둔다(아이가 '뺐어'를 누를 때까지 결과에 남는다)."""
    if not names:
        return
    data = _event_data(eid)
    data["flagged"] = list(dict.fromkeys(data["flagged"] + list(names)))
    data["removed"] = [n for n in data["removed"] if n not in names]
    _event_save(eid, data)


def alert_removed(eid: int, name: str, removed: bool = True) -> dict | None:
    data = _event_data(eid)
    data["removed"] = [n for n in data["removed"] if n != name] + ([name] if removed else [])
    _event_save(eid, data)
    return view(eid)


def scenario_list() -> list[dict]:
    return [{"id": s["id"], "name": s["name"], "type": s["type"]} for s in recommend.load()["scenarios"]]


def quick_event(scenario_id: str, date: str, title: str | None = None) -> int | None:
    """알림장 없는 평소 일정: 상황을 고르면 기본 준비물이 '추천' 출처로 들어간다."""
    data = recommend.load()
    sc = next((s for s in data["scenarios"] if s["id"] == scenario_id), None)
    if not sc:
        return None
    date = datetime.strptime(str(date), "%Y-%m-%d").date().isoformat()   # 틀린 날짜는 여기서 멈추고, 저장은 늘 YYYY-MM-DD
    recs = [r for r in recommend.starter_items(scenario_id, data) if not r["guardian_decides"]]
    eid = db.insert_event(
        {"title": title or sc["name"], "kind": "event", "date": date, "outdoor": "outdoor" in sc.get("tags", []),
         "notes": "알림장 없이 만든 일정이에요. 준비물은 챙겼지 추천이라 빼거나 더해도 돼요."},
        [{"name": r["name"], "source": "recommend", "reason": f"{r['why']} · {r['basis']}"} for r in recs])
    ev = db.get_event(eid)
    for it, r in zip(ev["items"], recs):
        _meta_save(it["id"], guard.annotate(it["name"]) | {"kind": r["kind"], "emoji": r["emoji"], "group": "scenario"})
    _event_save(eid, _event_data(eid) | {"analyzed": True})
    return eid


# ---------- 아이 결과 보고 ----------
def kid_report(eid: int) -> dict | None:
    """아이가 '엄마에게 보여 주기'를 누르면 보호자 화면 알림함에 결과를 남긴다(실제 푸시가 아니다)."""
    v = view(eid)
    if not v:
        return None
    s = v["plus"]["summary"]
    forgot, data = _kv_get("forgot", {}), _event_data(eid)
    for key in data.get("forgot_logged", []):            # 같은 일정을 다시 보내도 한 번만 센다
        forgot[key] = max(0, forgot.get(key, 0) - 1)
    logged = [guard.split_name(name)[0] for name in s["left"]]
    for key in logged:
        forgot[key] = forgot.get(key, 0) + 1
    _kv_set("forgot", {k: v for k, v in forgot.items() if v > 0})
    _event_save(eid, data | {"forgot_logged": logged})
    title, body = tone.kid_report(v, s, get_profile())
    with db.tx() as con:
        con.execute("DELETE FROM notifications WHERE event_id=? AND kind='kid'", (eid,))
        con.execute("INSERT INTO notifications(event_id,kind,fire_at,message) VALUES(?, 'kid', ?, ?)",
                    (eid, now(), f"{title}\n{body}"))
    return {"title": title, "body": body, "summary": s}


# ---------- 칭찬 스티커 ----------
def stickers(eid: int | None = None) -> list[dict]:
    q, args = "SELECT s.*, e.title AS event_title, e.date AS event_date FROM plus_sticker s JOIN events e ON e.id=s.event_id", []
    if eid is not None:
        q += " WHERE s.event_id=?"
        args.append(eid)
    with db.tx() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY s.id DESC LIMIT 60", args)]


def give_sticker(eid: int, sticker: str, message: str = "", giver: str = "엄마") -> dict | None:
    if not db.get_event(eid) or sticker not in STICKERS:
        return None
    with db.tx() as con:
        con.execute("INSERT INTO plus_sticker(event_id,sticker,message,giver,created_at) VALUES(?,?,?,?,?)",
                    (eid, sticker, (message or "")[:40], (giver or "엄마")[:6], now()))
    return {"stickers": stickers(eid)}


# ---------- 돌아오기 ----------
def return_view(eid: int) -> dict | None:
    """가져간 것 가운데 다시 가져와야 하는 것. 먹고 쓰고 없어지는 것은 뺀다."""
    v = view(eid)
    if not v:
        return None
    back = [i for i in v["items"] if i["checked"] and i["meta"].get("bring_back") and i["meta"].get("kind") != "submit"]
    done = set(v["plus"]["returned"])
    items = [{"id": i["id"], "name": i["meta"].get("base") or i["name"], "returned": i["id"] in done,
              "tag": i["meta"].get("group") == "tag"} for i in back]
    left = [i["name"] for i in items if not i["returned"]]
    return {"id": v["id"], "title": v["title"], "date": v["date"], "items": items,
            "summary": {"counted": len(items), "returned": len(items) - len(left), "left": left}}


def set_returned(eid: int, item_id: int, returned: bool) -> dict | None:
    r = return_view(eid)
    if not r or item_id not in {i["id"] for i in r["items"]}:
        return None                                      # 이 일정의 다시 가져올 물건이 아니다
    data = _event_data(eid)
    data["returned"] = [x for x in data["returned"] if x != item_id] + ([item_id] if returned else [])
    _event_save(eid, data)
    return return_view(eid)


def return_report(eid: int) -> dict | None:
    r = return_view(eid)
    if not r:
        return None
    s = r["summary"]
    title = f"🏠 집에 와서 가방을 확인했어요 · {r['title']}"
    body = f"가져옴 {s['returned']} · 아직 {len(s['left'])}" + (f" ({', '.join(s['left'])})" if s["left"] else " — 다 가져왔어요!")
    with db.tx() as con:
        con.execute("DELETE FROM notifications WHERE event_id=? AND kind='home'", (eid,))
        con.execute("INSERT INTO notifications(event_id,kind,fire_at,message) VALUES(?, 'home', ?, ?)",
                    (eid, now(), f"{title}\n{body}"))
    return {"title": title, "body": body, "summary": s}


def sweep(eid: int | None = None):
    """지운 일정·준비물에 딸린 추가 정보(근거 줄, 스티커, 상태)를 같이 지운다."""
    with db.tx() as con:
        if eid is not None:
            con.execute("DELETE FROM plus_event WHERE event_id=?", (eid,))
            con.execute("DELETE FROM plus_sticker WHERE event_id=?", (eid,))
        con.execute("DELETE FROM plus_event WHERE event_id NOT IN (SELECT id FROM events)")
        con.execute("DELETE FROM plus_sticker WHERE event_id NOT IN (SELECT id FROM events)")
        con.execute("DELETE FROM plus_item WHERE item_id NOT IN (SELECT id FROM items)")


def tone_previews(eid: int) -> dict | None:
    v = view(eid)
    if not v:
        return None
    return {k: dict(zip(("title", "body"), tone.calendar_entry(v, k))) | {"label": t["label"]} for k, t in tone.TONES.items()}
