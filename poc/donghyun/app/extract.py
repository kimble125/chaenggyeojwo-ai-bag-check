"""가정통신문(텍스트/사진) → 캘린더에 넣을 일정 + 준비물 (Claude 구조화 출력)."""
import base64
import os
from datetime import date
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
client = anthropic.AsyncAnthropic()


class AiItem(BaseModel):
    name: str = Field(description="추천 준비물 (짧게)")
    reason: str = Field(description="추천 이유 한 줄")


class ExtractedEvent(BaseModel):
    title: str = Field(description="캘린더 제목. 예: '5학년 환경체험학교(하천 탐사)'")
    kind: Literal["event", "deadline", "etc"] = Field(
        description="event=행사·수업·체험 당일, deadline=회신·신청·제출 마감, etc=기타 안내")
    date: str = Field(description="YYYY-MM-DD")
    start_time: str | None = Field(None, description="HH:MM (24시간). 없으면 null")
    end_time: str | None = Field(None, description="HH:MM. 없으면 null")
    location: str | None = Field(None, description="장소 (주소가 있으면 함께)")
    lat: float | None = Field(None, description="장소의 대략적인 위도. 확실히 알 때만, 모르면 null")
    lon: float | None = Field(None, description="장소의 대략적인 경도. 확실히 알 때만, 모르면 null")
    outdoor: bool = Field(description="야외 활동이 포함되면 true")
    target: str | None = Field(None, description="대상. 예: '5학년 1·2반'")
    items: list[str] = Field(description="통신문에 적힌 준비물을 하나씩 (원문 표현 유지, 괄호 설명은 짧게 포함)")
    ai_items: list[AiItem] = Field(description="통신문에는 없지만 활동 성격상 챙기면 좋을 것 0~3개. 날씨(우산·마스크)는 제외")
    notes: str = Field(description="부모가 알아야 할 핵심 메모 1~3줄 (집결 시간·장소, 비용, 우천 시 대체 등)")


class Extraction(BaseModel):
    summary: str = Field(description="통신문 한 줄 요약")
    events: list[ExtractedEvent]


SYSTEM = """당신은 초등학생 학부모를 돕는 비서입니다. 학교 가정통신문에서 캘린더에 넣을 일정과 준비물을 뽑습니다.

규칙
- 행사 당일은 kind=event, 참가 신청서·동의서 회신 기한은 별도 kind=deadline 일정으로 만든다 (준비물은 '회신서' 등).
- 연도가 없으면 게시일(없으면 오늘) 기준으로 가장 자연스러운 연도를 고른다.
- 시간표가 있으면 첫 집결 시각을 start_time, 마지막 시각을 end_time 으로 한다.
- 준비물은 통신문에 적힌 것만 items 에 넣는다. 지어내지 않는다. '등'으로 끝나면 그대로 둔다.
- ai_items 는 활동 성격상 꼭 도움이 되는 것만 (예: 하천 탐사 → 여벌 양말). 우산·마스크는 날씨 모듈이 따로 판단하니 넣지 않는다.
- 가져오면 안 되는 것(금지)과 조건을 적은 문장("유리병은 가져오지 않습니다", "장난감 불가")은 notes 에 원문 그대로 옮긴다. 뒤 단계가 그 문장에서 금지 목록을 만든다.
- 일정이 없는 단순 안내문이면 events 를 빈 배열로 둔다."""


async def extract(text: str = "", title: str | None = None, posted: str | None = None,
                  images: list[tuple[str, bytes]] | None = None) -> dict:
    content: list[dict] = []
    for media_type, data in images or []:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()}})
    head = f"오늘: {date.today().isoformat()}\n"
    if posted:
        head += f"게시일: {posted}\n"
    if title:
        head += f"제목: {title}\n"
    body = f"{head}\n<가정통신문>\n{text}\n</가정통신문>" if text else head + "\n(첨부 사진의 가정통신문을 읽어 주세요)"
    content.append({"type": "text", "text": body})

    resp = await client.messages.parse(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": content}],
        output_format=Extraction,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"추출 실패 (stop_reason={resp.stop_reason})")
    out = resp.parsed_output.model_dump()
    out["usage"] = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens, "model": MODEL}
    return out


class PhotoCheck(BaseModel):
    seen: list[int] = Field(description="사진에서 분명히 보이는 준비물 번호")
    not_seen: list[int] = Field(description="사진에서 안 보이거나 확실하지 않은 준비물 번호")


async def photo_check(items: list[str], media_type: str, data: bytes) -> dict:
    """아이가 펼쳐 놓은 준비물 사진에서 무엇이 보이는지 확인."""
    listing = "\n".join(f"{i}. {n}" for i, n in enumerate(items))
    resp = await client.messages.parse(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        system="아이가 학교 준비물을 바닥에 펼쳐 놓고 찍은 사진을 봅니다. 각 준비물이 사진에 보이는지 판단합니다. "
               "애매하면 not_seen 으로 둡니다 (아이가 직접 한 번 더 확인하게 됩니다). 모든 번호는 둘 중 한 곳에만 넣습니다.",
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": f"준비물 목록:\n{listing}"},
        ]}],
        output_format=PhotoCheck,
    )
    if resp.parsed_output is None:
        raise RuntimeError(f"사진 확인 실패 (stop_reason={resp.stop_reason})")
    seen = {i for i in resp.parsed_output.seen if 0 <= i < len(items)}
    return {"seen": sorted(seen), "not_seen": [i for i in range(len(items)) if i not in seen]}
