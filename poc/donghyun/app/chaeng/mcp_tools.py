"""가방쏙의 규칙 기능을 MCP 도구로 연다. AI 비서(Claude 등)는 말을 하고, 판단(금지·조건·개수)은 이 규칙 코드가 한다.

도구 3개(모두 모델 호출 없음):
- read_notice      가정통신문 글 → 일정, 준비물(조건·수량·입는 것), 가져오지 않는 것(통신문 문장과 함께). 저장하지 않는다
- packing_plan     저장된 일정의 챙길 것, 보호자가 정할 것, 금지, 추천(근거), 남은 것
- calendar_entry   바깥 캘린더에 넣을 제목·메모(말투 3가지)·알림 시각, 구글 캘린더 주소, 캘린더 파일(.ics)

쓰는 길 두 가지:
- 본체(FastAPI): register(mcp) 가 동현님의 캘린더 MCP 서버(app/calendar_mcp.py)에 이 도구들을 더한다
- 예시 서버(demo_server.py): handle_rpc() 가 /mcp/ 에서 같은 도구를 JSON-RPC 로 답한다(표준 라이브러리만)
"""
from __future__ import annotations

import json

from . import calendar_out, guard, service, simple_extract

SERVER = {"name": "gabangssok", "version": "0.1.0"}
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("가방쏙: 초등학생 가정통신문의 준비물을 정리한다. 금지·조건·개수는 이 도구가 준 값을 그대로 쓰고 지어내지 않는다. "
                "약과 '필요한 학생만' 준비물은 보호자가 정한다.")


def _item(name: str, meta: dict) -> dict:
    out = {"name": meta.get("base") or name, "written_as": name, "kind": meta.get("kind", "carry")}
    for k in ("condition", "quantity", "not_accepted", "evidence"):
        if meta.get(k):
            out[k] = meta[k]
    if meta.get("guardian") or meta.get("conditional") == "needed":
        out["parent_decides"] = True
    if meta.get("conditional") == "rain":
        out["only_if_rain"] = True
    return out


def read_notice(text: str, title: str = "") -> dict:
    """가정통신문 글을 규칙으로 읽는다(저장하지 않음). 일정, 준비물(조건·수량·입는 것), 가져오지 않는 것과 그 근거 문장을 준다."""
    ex = simple_extract.extract(text or "", title or None)
    events = []
    for ev in ex["events"]:
        an = guard.analyze(text or "", ev["items"])
        events.append({
            "title": ev["title"], "kind": ev["kind"], "date": ev["date"], "start_time": ev["start_time"], "end_time": ev["end_time"],
            "location": ev["location"],
            "items": [_item(n, an["items"][n]) for n in ev["items"]],
        })
    an = guard.analyze(text or "", [])
    return {"summary": ex["summary"], "events": events, "forbidden": an["forbidden"], "not_needed": an["not_needed"],
            "list_ends_with_etc": an["list_open"],
            "note": "규칙으로 읽은 결과다. 날짜와 준비물을 보호자가 확인해야 한다. 'list_ends_with_etc' 가 참이면 통신문 목록이 '등'으로 끝나 빠진 것이 있을 수 있다."}


def packing_plan(event_id: int) -> dict:
    """저장된 일정 하나의 챙길 것, 보호자가 정할 것(약 등), 가져오지 않는 것, 추천과 근거, 아직 남은 것을 준다."""
    v = service.view(int(event_id))
    if not v:
        raise ValueError("그 번호의 일정이 없어요")
    p, s = v["plus"], v["plus"]["summary"]

    def row(i):
        return _item(i["name"], i["meta"]) | {"id": i["id"], "packed": bool(i["checked"]), "from": i["source"]}

    live = [i for i in v["items"] if not i["blocked"] and not i["skipped"]]
    return {
        "event": {"id": v["id"], "title": v["title"], "date": v["date"], "start_time": v["start_time"], "location": v["location"]},
        "to_pack": [row(i) for i in live if not i["optional"]],
        "optional": [row(i) for i in live if i["optional"] and not i["guardian"]],
        "parent_decides": [row(i) for i in live if i["guardian"]] + [{"name": r["name"], "why": r["why"]} for r in p["guardian_recs"]],
        "left_out_this_time": [i["name"] for i in v["items"] if i["skipped"]],
        "forbidden": [{"name": f["name"], "evidence": f["evidence"]} for f in p["forbidden"]],
        "recommendations": [{"name": r["name"], "why": r["why"], "basis": r["basis"]} for r in p["recs"]],
        "summary": {"count": s["counted"], "packed": s["packed"], "left": s["left"], "all_packed": s["can_finish"],
                    "list_ends_with_etc": s["list_open"]},
        "weather": v.get("weather"),
    }


def calendar_entry(event_id: int, tone: str = "basic") -> dict:
    """바깥 캘린더에 넣을 한 건: 제목·메모(tone=basic|cute|neat), 시작/끝, 알림 시각(전날 저녁·당일 아침), 구글 캘린더 주소, 캘린더 파일(.ics) 글."""
    v = service.view(int(event_id))
    if not v:
        raise ValueError("그 번호의 일정이 없어요")
    return calendar_out.bundle(v, tone)


TOOLS = [
    {"fn": read_notice, "name": "read_notice", "description": read_notice.__doc__,
     "inputSchema": {"type": "object", "required": ["text"], "properties": {
         "text": {"type": "string", "description": "가정통신문·알림장 글 전체"},
         "title": {"type": "string", "description": "글 제목(없어도 됨)"}}}},
    {"fn": packing_plan, "name": "packing_plan", "description": packing_plan.__doc__,
     "inputSchema": {"type": "object", "required": ["event_id"], "properties": {
         "event_id": {"type": "integer", "description": "일정 번호(list_events 로 찾는다)"}}}},
    {"fn": calendar_entry, "name": "calendar_entry", "description": calendar_entry.__doc__,
     "inputSchema": {"type": "object", "required": ["event_id"], "properties": {
         "event_id": {"type": "integer"},
         "tone": {"type": "string", "enum": ["basic", "cute", "neat"], "description": "보통 / 귀엽게 / 또박또박"}}}},
]


def register(mcp) -> list[str]:
    """FastMCP 서버에 도구를 더한다(본체). 이름이 겹치면 건너뛴다."""
    done = []
    for t in TOOLS:
        mcp.tool(name=t["name"], description=t["description"])(t["fn"])
        done.append(t["name"])
    return done


# ---------- 예시 서버용: MCP(JSON-RPC 2.0, Streamable HTTP 의 JSON 응답) 최소 구현 ----------
def _extra_tools() -> list[dict]:
    """예시 서버에는 캘린더 MCP 가 없으니 일정 찾기 하나를 같이 연다."""
    from .. import db

    def list_events(start: str | None = None, end: str | None = None) -> list[dict]:
        """기간(YYYY-MM-DD, 포함) 안의 일정 번호·제목·날짜."""
        return [{"id": e["id"], "title": e["title"], "date": e["date"], "kind": e["kind"]} for e in db.list_events(start, end)]

    return [{"fn": list_events, "name": "list_events", "description": list_events.__doc__,
             "inputSchema": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}}}]


def handle_rpc(msg: dict, tools: list[dict] | None = None) -> dict | None:
    """요청 하나에 답 하나. 알림(id 없음)에는 None."""
    tools = (tools if tools is not None else _extra_tools()) + TOOLS
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0], "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in tools]})
    if method == "tools/call":
        tool = next((t for t in tools if t["name"] == params.get("name")), None)
        if not tool:
            return err(-32602, f"없는 도구예요: {params.get('name')}")
        try:
            out = tool["fn"](**(params.get("arguments") or {}))
        except (ValueError, KeyError, TypeError) as e:
            return ok({"content": [{"type": "text", "text": f"도구를 부르지 못했어요: {e}"}], "isError": True})
        res = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}], "isError": False}
        if isinstance(out, dict):
            res["structuredContent"] = out
        return ok(res)
    return err(-32601, f"없는 메서드예요: {method}")
