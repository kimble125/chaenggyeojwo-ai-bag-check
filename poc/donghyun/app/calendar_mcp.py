"""앱 자체 캘린더를 MCP 서버로 노출.

- 웹 앱의 '캘린더에 넣기'는 이 MCP 서버의 add_event 를 MCP 클라이언트로 호출합니다.
- 같은 엔드포인트(/mcp/)를 Claude Desktop·Claude Code 등 외부 AI 에 연결하면
  "내일 준비물 뭐야?" 같은 질문도 이 캘린더로 답할 수 있습니다.
"""
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import db
from .reminders import schedule_for_event

mcp = FastMCP(
    "school-calendar",
    instructions="학부모용 학교 일정 캘린더. 일정마다 준비물 체크리스트가 있다.",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def add_event(
    title: str,
    date: str,
    kind: str = "event",
    start_time: str | None = None,
    end_time: str | None = None,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    outdoor: bool = False,
    target: str | None = None,
    notes: str | None = None,
    items: list[str] | None = None,
    ai_items: list[dict] | None = None,
    source_title: str | None = None,
    source_url: str | None = None,
) -> dict:
    """캘린더에 일정을 추가한다. date=YYYY-MM-DD, time=HH:MM, kind=event|deadline|etc.
    items=통신문 준비물 이름 목록, ai_items=[{name, reason}] AI 추천 준비물."""
    rows = [{"name": n, "source": "notice"} for n in (items or [])]
    rows += [{"name": a["name"], "source": "ai", "reason": a.get("reason")} for a in (ai_items or [])]
    eid = db.insert_event(dict(
        title=title, kind=kind, date=date, start_time=start_time, end_time=end_time,
        location=location, lat=lat, lon=lon, outdoor=outdoor, target=target, notes=notes,
        source_title=source_title, source_url=source_url), rows)
    schedule_for_event(eid)
    return {"id": eid, "title": title, "date": date}


@mcp.tool()
def list_events(start: str | None = None, end: str | None = None) -> list[dict]:
    """기간(YYYY-MM-DD, 포함) 안의 일정과 준비물 체크리스트를 돌려준다."""
    return db.list_events(start, end)


@mcp.tool()
def get_checklist(date: str) -> dict:
    """특정 날짜에 챙겨야 할 준비물(날씨 추천 포함)과 체크 여부."""
    evs = db.list_events(date, date)
    return {
        "date": date,
        "events": [{"title": e["title"], "kind": e["kind"], "weather": e["weather"],
                    "items": [{"name": i["name"], "source": i["source"], "reason": i["reason"],
                               "checked": i["checked"]} for i in e["items"]]} for e in evs],
    }


@mcp.tool()
def check_item(item_id: int, checked: bool = True) -> dict:
    """준비물을 챙겼다고(또는 안 챙겼다고) 표시한다."""
    db.set_item_checked(item_id, checked)
    return {"ok": True}


@mcp.tool()
def delete_event(event_id: int) -> dict:
    """일정을 삭제한다."""
    return {"deleted": db.delete_event(event_id)}
