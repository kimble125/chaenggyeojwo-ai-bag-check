"""챙겼지 추가 기능의 주소(/api/plus/…). 계산은 service.py 가 하고 여기는 주고받기만 한다.

main.py 에서  app.include_router(router)  한 줄로 붙는다. 예시 서버(demo_server.py)도 같은 주소를 연다.
"""
from __future__ import annotations

import logging
import os
from datetime import date

from fastapi import APIRouter, File, HTTPException, UploadFile

from . import service

log = logging.getLogger("helper.plus")
router = APIRouter(prefix="/api/plus")
MAX_IMAGE = 8 * 1024 * 1024
MAX_TEXT = 20000
DAILY_AI_CAP = int(os.environ.get("CHAENG_DAILY_AI_CAP", "200"))      # 하루에 허용할 사진 확인 수(서버 전체)


def _need(x):
    if x is None:
        raise HTTPException(404, "찾을 수 없어요")
    return x


@router.get("/mode")
def mode():
    return {"demo": False, "ai": bool(os.environ.get("ANTHROPIC_API_KEY")), "stickers": service.STICKERS,
            "traits": [{"id": t, "label": l} for t, l in service.TRAITS]}


@router.get("/scenarios")
def scenarios():
    return service.scenario_list()


@router.post("/quick-event")
def quick_event(body: dict):
    try:
        eid = service.quick_event(str(body.get("scenario")), str(body.get("date")), body.get("title"))
    except ValueError:
        raise HTTPException(400, "날짜는 YYYY-MM-DD 로 적어 주세요")
    return {"id": _need(eid)}


@router.get("/profile")
def profile_get():
    return service.get_profile()


@router.put("/profile")
def profile_put(body: dict):
    return service.set_profile(body)


@router.get("/stickers")
def sticker_board():
    return service.stickers()


@router.get("/events/{eid}")
def event(eid: int):
    return _need(service.view(eid))


@router.post("/events/{eid}/analyze")
def analyze(eid: int, body: dict):
    """알림장 글에서 금지·조건·근거를 뽑아 붙인다. 글은 저장하지 않는다."""
    text = str(body.get("text") or "")
    if len(text) > MAX_TEXT:
        raise HTTPException(413, "통신문 글이 너무 길어요(2만 자까지)")
    return _need(service.analyze(eid, text))


@router.post("/events/{eid}/recs/accept")
def rec_accept(eid: int, body: dict):
    return _need(service.accept_rec(eid, str(body.get("name"))))


@router.post("/events/{eid}/recs/decline")
def rec_decline(eid: int, body: dict):
    return _need(service.decline_rec(eid, str(body.get("name"))))


@router.post("/events/{eid}/alerts")
def alerts(eid: int, body: dict):
    return _need(service.alert_removed(eid, str(body.get("name")), bool(body.get("removed", True))))


@router.post("/events/{eid}/photo-check")
async def photo_check(eid: int, image: UploadFile = File(...)):
    """펼친 준비물 사진 확인. 입고 가는 것·내는 것·조건부 준비물은 사진으로 묻지 않고 직접 확인으로 돌린다."""
    v = _need(service.view(eid))
    if (getattr(image, "size", None) or 0) > MAX_IMAGE:
        raise HTTPException(413, "사진이 너무 커요(8MB까지)")
    data = await image.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise HTTPException(413, "사진이 너무 커요(8MB까지)")
    if not (image.content_type or "").startswith("image/"):
        raise HTTPException(400, "사진 파일만 올릴 수 있어요")
    used_key = f"ai_calls:{date.today().isoformat()}"
    used = service._kv_get(used_key, 0)
    if used >= DAILY_AI_CAP:
        raise HTTPException(429, "오늘 사진 확인 횟수를 다 썼어요. 하나씩 확인해 주세요")
    service._kv_set(used_key, used + 1)
    todo = [i for i in v["items"] if not i["checked"] and not i["guardian"] and not i["blocked"] and not i.get("skipped")]
    ask = [i for i in todo if i["meta"].get("kind", "carry") == "carry" and not i["meta"].get("conditional")
           and not i["meta"].get("quantity")]            # 수량이 적힌 것("비닐봉지 2장")은 사진으로 넘기지 않고 아이가 세어 본다
    rest = [i for i in todo if i not in ask]
    ban = [f["name"] for f in v["plus"]["forbidden"]]
    try:
        from . import vision
        r = await vision.photo_check_plus(
            [{"name": i["meta"].get("base") or i["name"], "condition": i["meta"].get("condition"),
              "not_accepted": i["meta"].get("not_accepted")} for i in ask],
            ban, image.content_type or "image/jpeg", data)
    except Exception as e:
        log.error("photo-check plus failed: %s", type(e).__name__)   # 오류 종류만 남긴다(사진·목록·응답 글은 기록하지 않음)
        raise HTTPException(502, "사진 확인을 못 했어요. 하나씩 확인해 주세요")
    service.flag_forbidden(eid, r["forbidden_seen"])
    return {"seen": [ask[i]["id"] for i in r["seen"]],
            "not_seen": [ask[i]["id"] for i in r["not_seen"]] + [i["id"] for i in rest],
            "forbidden_seen": r["forbidden_seen"], "people_or_names": r["people_or_names"], "mode": "ai"}


@router.post("/events/{eid}/kid-report")
def kid_report(eid: int):
    return _need(service.kid_report(eid))


@router.post("/events/{eid}/stickers")
def sticker_give(eid: int, body: dict):
    r = service.give_sticker(eid, str(body.get("sticker")), str(body.get("message") or ""), str(body.get("giver") or "엄마"))
    if r is None:
        raise HTTPException(400, "줄 수 없는 스티커예요")
    return r


@router.get("/events/{eid}/return")
def return_get(eid: int):
    return _need(service.return_view(eid))


@router.post("/events/{eid}/items/{iid}/skip")
def item_skip(eid: int, iid: int, body: dict):
    if not isinstance(body.get("skipped", True), bool):
        raise HTTPException(400, "skipped 는 true/false 로 보내 주세요")
    return _need(service.set_skipped(eid, iid, body.get("skipped", True)))


@router.post("/events/{eid}/return")
def return_set(eid: int, body: dict):
    if not isinstance(body.get("item_id"), int) or not isinstance(body.get("returned", True), bool):
        raise HTTPException(400, "item_id 는 숫자, returned 는 true/false 로 보내 주세요")
    return _need(service.set_returned(eid, body["item_id"], body.get("returned", True)))


@router.post("/events/{eid}/return/report")
def return_report(eid: int):
    return _need(service.return_report(eid))


@router.get("/events/{eid}/tones")
def tones(eid: int):
    return _need(service.tone_previews(eid))
