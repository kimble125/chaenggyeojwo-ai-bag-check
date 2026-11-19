#!/usr/bin/env python3
"""챙겼지 예시 서버: 설치 없이 도는 판(파이썬 표준 라이브러리만, 3.10 이상).

    python3 demo_server.py            # http://127.0.0.1:6111
    PORT=7000 python3 demo_server.py

- FastAPI 본체(app/main.py)와 같은 화면(app/static)과 같은 저장소(app/db.py)를 쓴다.
- 모델을 부르지 않는다. 알림장은 규칙으로 읽고(app/chaeng/simple_extract.py),
  사진 확인은 '예시 결과'를 돌려준다(화면에 예시라고 적힌다). API 키가 필요 없다.
- 캘린더 등록은 MCP 를 거치지 않고 같은 DB 에 바로 넣는다.
- 날씨는 Open-Meteo 를 그대로 부른다(키 없음). 안 되면 날씨 없이 돈다.
- 처음 켜면 지어낸 예시 일정 두 개를 넣는다(실제 학교 문서가 아니다).
"""
from __future__ import annotations

import email
import email.policy
import json
import mimetypes
import os
import re
import sys
import types
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("DB_PATH", os.path.join(ROOT, "data", "demo.db"))
sys.path.insert(0, ROOT)
try:
    import httpx  # noqa: F401
except ImportError:                       # weather.py 가 맨 위에서 httpx 를 찾는다. 여기서는 쓰지 않으니 빈 껍데기를 준다
    _stub = types.ModuleType("httpx")
    _stub.HTTPError = Exception
    sys.modules["httpx"] = _stub

from app import db, reminders, weather  # noqa: E402
from app.chaeng import service, simple_extract  # noqa: E402

STATIC = os.path.join(ROOT, "app", "static")
MAX_BODY = 8 * 1024 * 1024
SIMULATE = {
    "rain": {"weather": "비", "rain_prob": 80, "rain_prob_window": 80, "rain_mm": 12.0, "rain_signal": "rain"},
    "dust": {"pm10": 120, "pm25": 58, "pm10_grade": "나쁨", "pm25_grade": "나쁨"},
}


# ---------- 날씨(본체 weather.py 의 계산을 그대로 쓰고, 받아 오는 부분만 urllib 로) ----------
def _get_json(url: str, params: dict) -> dict:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=weather.UA)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_outlook(lat, lon, day, start_time=None, end_time=None) -> dict | None:
    ahead = (date.fromisoformat(day) - date.today()).days
    if ahead < 0:
        return {"status": "past"}
    if ahead >= weather.FORECAST_DAYS:
        return {"status": "too_far", "days_ahead": ahead, "available_from": weather.FORECAST_DAYS - 1}
    s, e = weather._hours(start_time, end_time)
    base = {"latitude": lat, "longitude": lon, "timezone": "Asia/Seoul", "start_date": day, "end_date": day}
    j = _get_json(weather.FORECAST, base | {
        "daily": "weather_code,precipitation_probability_max,precipitation_sum,temperature_2m_max,temperature_2m_min",
        "hourly": "precipitation_probability"})
    dd = j["daily"]
    hp = [p for t, p in zip(j["hourly"]["time"], j["hourly"]["precipitation_probability"])
          if p is not None and s <= int(t[11:13]) <= e]
    out = {"status": "ok", "date": day, "lat": lat, "lon": lon, "provider": "Open-Meteo",
           "weather": weather.WMO.get(dd["weather_code"][0], "-"), "rain_prob": dd["precipitation_probability_max"][0],
           "rain_prob_window": max(hp) if hp else None, "rain_mm": dd["precipitation_sum"][0],
           "t_max": dd["temperature_2m_max"][0], "t_min": dd["temperature_2m_min"][0]}
    if ahead < weather.AIR_DAYS:
        try:
            h = _get_json(weather.AIR, base | {"hourly": "pm10,pm2_5"})["hourly"]
            win = [i for i, t in enumerate(h["time"]) if s <= int(t[11:13]) <= e]
            pm10 = [h["pm10"][i] for i in win if h["pm10"][i] is not None]
            pm25 = [h["pm2_5"][i] for i in win if h["pm2_5"][i] is not None]
            out["pm10"], out["pm25"] = (round(max(pm10)) if pm10 else None), (round(max(pm25)) if pm25 else None)
        except Exception:
            out["air_note"] = "미세먼지 정보를 못 가져왔어요"
    else:
        out["air_note"] = f"미세먼지 예보는 {weather.AIR_DAYS}일 전부터 확인돼요"
    out["pm10_grade"] = weather.grade(out.get("pm10"), weather.PM10_GRADES)
    out["pm25_grade"] = weather.grade(out.get("pm25"), weather.PM25_GRADES)
    out["fetched_at"] = reminders.now_str()
    return out


def refresh_weather(ev: dict, force=False, simulate: str | None = None) -> dict:
    if not force and ev.get("weather_at"):
        if datetime.now() - datetime.strptime(ev["weather_at"], "%Y-%m-%d %H:%M") < timedelta(minutes=180):
            return ev
    home = db.get_setting("home")
    lat, lon = (ev["lat"], ev["lon"]) if ev.get("lat") and ev.get("lon") else (home["lat"], home["lon"])
    try:
        o = fetch_outlook(lat, lon, ev["date"], ev.get("start_time"), ev.get("end_time"))
    except Exception:
        o = None
    if simulate in SIMULATE:
        if not o or o.get("status") != "ok":
            o = {"status": "ok", "date": ev["date"], "weather": "흐림", "t_min": 10, "t_max": 18, "rain_mm": 0}
        o |= SIMULATE[simulate] | {"simulated": simulate, "provider": "시연용 가정"}
        o.setdefault("fetched_at", reminders.now_str())
    if not o:
        return ev
    if o.get("status") == "ok":
        o["place"] = ev.get("location") if ev.get("lat") else f"{home['name']} (기본 위치)"
    db.replace_weather(ev["id"], o, weather.recommend(o, ev["outdoor"]), reminders.now_str())
    return db.get_event(ev["id"])


# ---------- 예시 사진 확인(사진을 실제로 보지 않는다) ----------
def example_photo_check(eid: int, case: str = "miss") -> dict | None:
    v = service.view(eid)
    if not v:
        return None
    todo = [i for i in v["items"] if not i["checked"] and not i["guardian"] and not i["blocked"]]
    carry = [i for i in todo if i["meta"].get("kind", "carry") == "carry" and not i["meta"].get("conditional")]
    other = [i for i in todo if i not in carry]
    hide = 0 if case == "all" else 1 if (case == "glass" or len(carry) < 3) else 2
    forbidden_seen, held = [], []
    if case == "glass":
        for it in carry:                              # 안 되는 대체물이 놓인 자리: 그 준비물은 '보임'으로 치지 않는다
            if it["meta"].get("not_accepted"):
                forbidden_seen.append(it["meta"]["not_accepted"][0])
                held.append(it)
                break
        if not forbidden_seen and v["plus"]["forbidden"]:
            forbidden_seen.append(v["plus"]["forbidden"][0]["name"])
    rest = [i for i in carry if i not in held]
    not_seen = held + (rest[len(rest) - hide:] if hide else []) + other
    seen = [i for i in carry if i not in not_seen]
    return {"seen": [i["id"] for i in seen], "not_seen": [i["id"] for i in not_seen], "forbidden_seen": forbidden_seen,
            "mode": "example", "note": "예시 모드라 사진을 실제로 보지 않았어요. 준비된 결과예요."}


def seed():
    """지어낸 예시 일정 두 개(실제 학교 문서 아님)."""
    if db.list_events():
        return
    s = simple_extract.sample("a")
    ex = simple_extract.extract(s["text"], s["title"], s["posted"])
    for e in ex["events"]:
        eid = db.insert_event(e | {"source_title": s["title"] + " (예시)", "source_url": None},
                              [{"name": n, "source": "notice"} for n in e["items"]])
        reminders.schedule_for_event(eid)
        service.analyze(eid, s["text"])
        refresh_weather(db.get_event(eid), force=True)
    service.quick_event("swim_academy", (date.today() + timedelta(days=2)).isoformat(), "수영 학원 가는 날")
    service.set_profile({"name": "하늘", "grade": 2, "traits": [], "always": ["교통카드"]})


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "chaeng-demo/0.1"

    def log_message(self, fmt, *args):       # 본문·사진·알림장 글은 기록하지 않는다(주소와 상태만)
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _fail(self, code: int, msg: str):
        self._send(code, {"detail": msg})

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 <= n <= MAX_BODY:
            raise ValueError("요청 크기가 맞지 않아요(8MB까지)")
        return self.rfile.read(n) if n else b""

    def _json(self) -> dict:
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _form(self) -> tuple[dict, list[tuple[str, str, bytes]]]:
        """multipart 를 (글 칸, 파일들)로 나눈다. 파일 내용은 쓰고 버린다(저장 안 함)."""
        raw = self._body()
        msg = email.message_from_bytes(
            b"Content-Type: " + self.headers.get("Content-Type", "").encode() + b"\r\n\r\n" + raw, policy=email.policy.HTTP)
        fields, files = {}, []
        for part in msg.iter_parts() if msg.is_multipart() else []:
            name = part.get_param("name", header="content-disposition")
            if part.get_filename():
                files.append((name, part.get_content_type(), part.get_payload(decode=True) or b""))
            else:
                fields[name] = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        return fields, files

    def _static(self, rel: str):
        root = os.path.realpath(STATIC)
        path = os.path.realpath(os.path.join(root, rel))
        if os.path.commonpath([root, path]) != root or not os.path.isfile(path):   # static 폴더 밖은 열지 않는다(링크 포함)
            return self._fail(404, "없는 파일이에요")
        with open(path, "rb") as f:
            self._send(200, f.read(), (mimetypes.guess_type(path)[0] or "application/octet-stream") +
                       ("; charset=utf-8" if path.endswith((".html", ".js", ".css", ".json")) else ""))

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PATCH(self):
        self._route("PATCH")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method: str):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path
        try:
            for m, pattern, fn in ROUTES:
                hit = re.fullmatch(pattern, path)
                if m == method and hit:
                    out = fn(self, q, *hit.groups())
                    if out is None:
                        return self._fail(404, "찾을 수 없어요")
                    if out is not SENT:
                        self._send(200, out)
                    return
            self._fail(404, "없는 주소예요")
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self._fail(400, f"요청을 읽지 못했어요: {e}")
        except Exception as e:  # 예시 서버: 무엇이 틀렸는지 화면에 보이게
            self._fail(500, f"서버 오류: {type(e).__name__}")
            raise


SENT = object()


def _page(name):
    def fn(h, q):
        h._static(name)
        return SENT
    return fn


def r_static(h, q, rel):
    h._static(rel)
    return SENT


def r_fetch(h, q):
    url = (h._json().get("url") or "").strip()
    key = url.split(":")[-1] if url.startswith("sample:") else "a"
    return simple_extract.sample(key) | {"url": url or "sample:a",
                                         "note": "예시 서버는 실제 주소를 열지 않고 지어낸 예시 통신문을 돌려줘요."}


def r_extract(h, q):
    fields, files = h._form()
    text = (fields.get("text") or "").strip()
    if not text and files:
        s = simple_extract.sample("a")              # 사진은 읽지 못한다: 예시 통신문으로 대신
        return simple_extract.extract(s["text"], s["title"], s["posted"]) | {"note": "예시 서버는 사진을 읽지 못해 예시 통신문으로 대신했어요."}
    if not text:
        raise ValueError("통신문 내용이나 사진을 넣어 주세요")
    return simple_extract.extract(text, fields.get("title") or None, fields.get("posted") or None)


def r_commit(h, q):
    body = h._json()
    created = []
    for ev in body.get("events", []):
        date.fromisoformat(ev["date"])               # 날짜가 틀리면 저장 전에 멈춘다
        rows = [{"name": n, "source": "notice"} for n in ev.get("items") or []]
        rows += [{"name": a["name"], "source": "ai", "reason": a.get("reason")} for a in ev.get("ai_items") or []]
        eid = db.insert_event(ev | {"source_title": body.get("source_title"), "source_url": body.get("source_url")}, rows)
        reminders.schedule_for_event(eid)
        refresh_weather(db.get_event(eid), force=True)
        created.append({"id": eid, "title": ev["title"], "date": ev["date"]})
    return {"created": created, "via": "예시 서버(직접 저장)"}


def r_event(h, q, eid):
    return db.get_event(int(eid))


def r_event_patch(h, q, eid):
    body = h._json()
    if not db.get_event(int(eid)):
        return None
    if "date" in body:
        date.fromisoformat(body["date"])
    db.update_event(int(eid), body)
    reminders.schedule_for_event(int(eid))
    ev = db.get_event(int(eid))
    return refresh_weather(ev, force=True) if {"date", "start_time", "end_time", "lat", "lon", "outdoor"} & body.keys() else ev


def r_weather(h, q, eid):
    ev = db.get_event(int(eid))
    return refresh_weather(ev, force=True, simulate=q.get("simulate")) if ev else None


def r_item_check(h, q, iid):
    db.set_item_checked(int(iid), bool(h._json().get("checked")))
    return {"ok": True}


def r_home_put(h, q):
    b = h._json()
    db.set_setting("home", {"name": b["name"], "lat": float(b["lat"]), "lon": float(b["lon"])})
    return {"ok": True}


def r_photo_plus(h, q, eid):
    h._body()                                        # 사진은 받되 읽지도 저장하지도 않는다
    r = example_photo_check(int(eid), q.get("case", "miss"))
    if r:
        service.flag_forbidden(int(eid), r["forbidden_seen"])
    return r


def r_photo_basic(h, q, eid):
    r = r_photo_plus(h, q, eid)
    return {"seen": r["seen"], "not_seen": r["not_seen"]} if r else None


J = lambda h: h._json()  # noqa: E731
E = r"/api/events/(\d+)"
P = r"/api/plus/events/(\d+)"
ROUTES = [
    ("GET", r"/", _page("index.html")), ("GET", r"/kid", _page("kid.html")), ("GET", r"/static/(.+)", r_static),
    ("GET", r"/healthz", lambda h, q: {"ok": True, "mode": "demo"}),
    ("POST", r"/api/notice/fetch", r_fetch), ("POST", r"/api/notice/extract", r_extract), ("POST", r"/api/notice/commit", r_commit),
    ("GET", r"/api/events", lambda h, q: db.list_events(q.get("start"), q.get("end"))),
    ("GET", E, r_event), ("PATCH", E, r_event_patch),
    ("DELETE", E, lambda h, q, eid: ({"deleted": db.delete_event(int(eid))}, service.sweep(int(eid)))[0]),
    ("POST", E + "/weather", r_weather),
    ("POST", E + "/items", lambda h, q, eid: {"id": db.add_item(int(eid), J(h)["name"].strip())}),
    ("PATCH", r"/api/items/(\d+)", r_item_check),
    ("DELETE", r"/api/items/(\d+)", lambda h, q, iid: (db.delete_item(int(iid)), service.sweep(), {"ok": True})[2]),
    ("POST", E + "/photo-check", r_photo_basic),
    ("POST", E + "/kid-report", lambda h, q, eid: reminders.kid_report(int(eid))),
    ("GET", r"/api/notifications/due", lambda h, q: reminders.due_notifications()),
    ("GET", r"/api/notifications", lambda h, q: reminders.history()),
    ("POST", E + "/test-notify", lambda h, q, eid: reminders.fire_test(int(eid))),
    ("GET", r"/api/settings", lambda h, q: {"home": db.get_setting("home")}),
    ("PUT", r"/api/settings/home", r_home_put),
    # ----- 챙겼지 추가 기능(본체에서는 app/chaeng/router.py 가 같은 주소를 연다) -----
    ("GET", r"/api/plus/mode", lambda h, q: {"demo": True, "ai": False, "stickers": service.STICKERS,
                                             "traits": [{"id": t, "label": l} for t, l in service.TRAITS]}),
    ("GET", r"/api/plus/scenarios", lambda h, q: service.scenario_list()),
    ("POST", r"/api/plus/quick-event", lambda h, q: (lambda b: {"id": service.quick_event(b["scenario"], b["date"], b.get("title"))})(J(h))),
    ("GET", r"/api/plus/profile", lambda h, q: service.get_profile()),
    ("PUT", r"/api/plus/profile", lambda h, q: service.set_profile(J(h))),
    ("GET", r"/api/plus/stickers", lambda h, q: service.stickers()),
    ("GET", P, lambda h, q, eid: service.view(int(eid))),
    ("POST", P + "/analyze", lambda h, q, eid: service.analyze(int(eid), J(h).get("text", ""))),
    ("POST", P + "/recs/accept", lambda h, q, eid: service.accept_rec(int(eid), J(h)["name"])),
    ("POST", P + "/recs/decline", lambda h, q, eid: service.decline_rec(int(eid), J(h)["name"])),
    ("POST", P + "/alerts", lambda h, q, eid: (lambda b: service.alert_removed(int(eid), b["name"], b.get("removed", True)))(J(h))),
    ("POST", P + "/photo-check", r_photo_plus),
    ("POST", P + "/kid-report", lambda h, q, eid: service.kid_report(int(eid))),
    ("POST", P + "/stickers", lambda h, q, eid: (lambda b: service.give_sticker(int(eid), b["sticker"], b.get("message", ""), b.get("giver", "엄마")))(J(h))),
    ("GET", P + "/return", lambda h, q, eid: service.return_view(int(eid))),
    ("POST", P + "/return", lambda h, q, eid: (lambda b: service.set_returned(int(eid), int(b["item_id"]), bool(b.get("returned", True))))(J(h))),
    ("POST", P + "/return/report", lambda h, q, eid: service.return_report(int(eid))),
    ("GET", P + "/tones", lambda h, q, eid: service.tone_previews(int(eid))),
]


def main():
    db.init()
    service.init()
    seed()
    port = int(os.environ.get("PORT", "6111"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"챙겼지 예시 서버: http://127.0.0.1:{port}  (끄려면 Ctrl+C) · DB {os.environ['DB_PATH']}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
