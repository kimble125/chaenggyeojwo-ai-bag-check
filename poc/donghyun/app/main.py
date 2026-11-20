import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel

from . import db, reminders, weather
from .calendar_mcp import mcp
from .extract import extract, photo_check
from .notice import fetch_notice

log = logging.getLogger("helper")
STATIC = os.path.join(os.path.dirname(__file__), "static")
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp/")
WEATHER_REFRESH_MIN = 180

mcp_app = mcp.streamable_http_app()

try:                                   # 챙겼지 추가 기능(추천·금지 표시·스티커·돌아오기). 빠져도 본체는 돈다
    from .chaeng import service as plus_service
    from .chaeng.router import router as plus_router
except Exception as e:                 # noqa: BLE001
    plus_service = plus_router = None
    log.warning("chaeng plus not loaded: %s", e)

if plus_service:                       # 추천·금지·말투를 같은 MCP 서버의 도구로 더한다(read_notice, packing_plan, calendar_entry)
    try:
        from .chaeng import mcp_tools
        mcp_tools.register(mcp)
    except Exception as e:             # noqa: BLE001
        log.warning("chaeng mcp tools not registered: %s", e)


SIMULATE = {  # 발표 시연용: 실제 예보 위에 덮어씀
    "rain": {"weather": "비", "rain_prob": 80, "rain_prob_window": 80, "rain_mm": 12.0, "rain_signal": "rain"},
    "dust": {"pm10": 120, "pm25": 58, "pm10_grade": "나쁨", "pm25_grade": "나쁨"},
}


async def refresh_weather(ev: dict, force=False, simulate: str | None = None) -> dict:
    """일정 하나의 날씨를 받아 날씨 준비물을 다시 계산."""
    if not force and ev.get("weather_at"):
        age = datetime.now() - datetime.strptime(ev["weather_at"], "%Y-%m-%d %H:%M")
        if age < timedelta(minutes=WEATHER_REFRESH_MIN):
            return ev
    home = db.get_setting("home")
    lat, lon = (ev["lat"], ev["lon"]) if ev.get("lat") and ev.get("lon") else (home["lat"], home["lon"])
    try:
        o = await weather.fetch_outlook(lat, lon, ev["date"], ev.get("start_time"), ev.get("end_time"))
        if simulate in SIMULATE:
            if not o or o.get("status") != "ok":
                o = {"status": "ok", "date": ev["date"], "weather": "흐림", "t_min": 10, "t_max": 18, "rain_mm": 0}
            o |= SIMULATE[simulate] | {"simulated": simulate, "provider": "시연용 가정"}
            o.setdefault("fetched_at", reminders.now_str())
        if o and o.get("status") == "ok":
            o["place"] = ev.get("location") if ev.get("lat") else f"{home['name']} (기본 위치)"
    except Exception as e:  # 날씨 실패가 캘린더를 막지 않게
        log.warning("weather failed for %s: %s", ev["id"], e)
        return ev
    db.replace_weather(ev["id"], o, weather.recommend(o, ev["outdoor"]), reminders.now_str())
    return db.get_event(ev["id"])


async def background_loop():
    while True:
        try:
            today = date.today()
            for ev in db.list_events(today.isoformat(), (today + timedelta(days=weather.FORECAST_DAYS - 1)).isoformat()):
                await refresh_weather(ev)
        except Exception as e:
            log.exception("background loop: %s", e)
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    if plus_service:
        plus_service.init()
    task = asyncio.create_task(background_loop())
    async with mcp.session_manager.run():
        yield
    task.cancel()


app = FastAPI(title="가방쏙 — 가정통신문 준비물 헬퍼", lifespan=lifespan)


# ---------- 가정통신문 → 일정 ----------
class FetchReq(BaseModel):
    url: str


@app.post("/api/notice/fetch")
async def api_fetch(req: FetchReq):
    try:
        return await fetch_notice(req.url)
    except Exception as e:
        raise HTTPException(400, f"페이지를 가져오지 못했어요: {e}")


@app.post("/api/notice/extract")
async def api_extract(
    text: str = Form(""), title: str = Form(""), posted: str = Form(""),
    images: list[UploadFile] = File(default=[]),
):
    imgs = []
    for f in images:
        data = await f.read()
        if data:
            imgs.append((f.content_type or "image/jpeg", data))
    if not text.strip() and not imgs:
        raise HTTPException(400, "통신문 내용이나 사진을 넣어 주세요")
    try:
        return await extract(text, title or None, posted or None, imgs)
    except Exception as e:
        log.exception("extract")
        raise HTTPException(502, f"AI 추출 실패: {e}")


class CommitReq(BaseModel):
    events: list[dict]
    source_title: str | None = None
    source_url: str | None = None


@app.post("/api/notice/commit")
async def api_commit(req: CommitReq):
    """추출·수정된 일정을 MCP 캘린더 서버의 add_event 로 등록."""
    created = []
    async with streamablehttp_client(MCP_URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for ev in req.events:
                args = {k: ev.get(k) for k in [
                    "title", "date", "kind", "start_time", "end_time", "location", "lat", "lon",
                    "outdoor", "target", "notes", "items", "ai_items"] if ev.get(k) not in (None, "")}
                args["outdoor"] = bool(ev.get("outdoor"))
                args["source_title"] = req.source_title
                args["source_url"] = req.source_url
                res = await s.call_tool("add_event", args)
                if res.isError:
                    raise HTTPException(500, f"MCP add_event 실패: {res.content}")
                created.append(res.structuredContent or json.loads(res.content[0].text))
    for c in created:
        ev = db.get_event(c["id"])
        if ev:
            await refresh_weather(ev, force=True)
    return {"created": created, "via": "mcp:add_event"}


# ---------- 캘린더 ----------
@app.get("/api/events")
def api_events(start: str | None = None, end: str | None = None):
    return db.list_events(start, end)


@app.get("/api/events/{eid}")
async def api_event(eid: int):
    ev = db.get_event(eid)
    if not ev:
        raise HTTPException(404)
    return ev


@app.post("/api/events/{eid}/weather")
async def api_event_weather(eid: int, simulate: str | None = None):
    ev = db.get_event(eid)
    if not ev:
        raise HTTPException(404)
    return await refresh_weather(ev, force=True, simulate=simulate)


@app.patch("/api/events/{eid}")
async def api_event_patch(eid: int, body: dict):
    if not db.get_event(eid):
        raise HTTPException(404)
    db.update_event(eid, body)
    reminders.schedule_for_event(eid)
    ev = db.get_event(eid)
    if {"date", "start_time", "end_time", "lat", "lon", "outdoor"} & body.keys():
        ev = await refresh_weather(ev, force=True)
    return ev


@app.delete("/api/events/{eid}")
def api_event_delete(eid: int):
    deleted = db.delete_event(eid)
    if plus_service:
        plus_service.sweep(eid)          # 딸린 근거 줄·스티커·상태도 같이 지운다
    return {"deleted": deleted}


class ItemReq(BaseModel):
    name: str


@app.post("/api/events/{eid}/items")
def api_item_add(eid: int, req: ItemReq):
    return {"id": db.add_item(eid, req.name.strip())}


@app.patch("/api/items/{iid}")
def api_item_check(iid: int, body: dict):
    db.set_item_checked(iid, bool(body.get("checked")))
    return {"ok": True}


@app.delete("/api/items/{iid}")
def api_item_delete(iid: int):
    db.delete_item(iid)
    return {"ok": True}


# ---------- 아이 미션 ----------
@app.post("/api/events/{eid}/photo-check")
async def api_photo_check(eid: int, image: UploadFile = File(...)):
    ev = db.get_event(eid)
    if not ev:
        raise HTTPException(404)
    try:
        r = await photo_check([i["name"] for i in ev["items"]], image.content_type or "image/jpeg", await image.read())
    except Exception as e:
        log.exception("photo-check")
        raise HTTPException(502, f"사진 확인 실패: {e}")
    ids = [i["id"] for i in ev["items"]]
    return {"seen": [ids[i] for i in r["seen"]], "not_seen": [ids[i] for i in r["not_seen"]]}


@app.post("/api/events/{eid}/kid-report")
def api_kid_report(eid: int):
    r = reminders.kid_report(eid)
    if not r:
        raise HTTPException(404)
    return r


@app.get("/kid")
def kid_page():
    return FileResponse(os.path.join(STATIC, "kid.html"))


# ---------- 알림 ----------
@app.get("/api/notifications/due")
def api_due():
    return reminders.due_notifications()


@app.get("/api/notifications")
def api_notifications():
    return reminders.history()


@app.post("/api/events/{eid}/test-notify")
def api_test_notify(eid: int):
    if not reminders.fire_test(eid):
        raise HTTPException(404)
    return {"ok": True}


# ---------- 설정 ----------
@app.get("/api/settings")
def api_settings():
    return {"home": db.get_setting("home")}


@app.put("/api/settings/home")
def api_settings_home(body: dict):
    db.set_setting("home", {"name": body["name"], "lat": float(body["lat"]), "lon": float(body["lon"])})
    return {"ok": True}


@app.get("/healthz")
def healthz():
    return {"ok": True}


if plus_router:
    app.include_router(plus_router)
app.mount("/mcp", mcp_app)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
