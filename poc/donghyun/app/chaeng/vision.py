"""펼친 준비물 사진 확인 + 가져오면 안 되는 것 찾기. extract.py 의 photo_check 와 같은 방식(Claude 구조화 출력).

- 모델은 본 것만 답한다. 애매하면 not_seen(아이가 직접 한 번 더 본다). '없다'고 단정하지 않는다.
- 조건에 안 맞는 물건(예: 플라스틱 물통 자리에 유리병)은 seen 에 넣지 않고 forbidden_seen 으로 알린다.
- 사진은 메모리에서만 쓰고 저장하지 않는다. 사진은 Anthropic API 로 전송된다(화면에 알린다).
"""
from __future__ import annotations

import base64
import os

import anthropic
from pydantic import BaseModel, Field

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
client = anthropic.AsyncAnthropic()

SYSTEM = (
    "아이가 학교 준비물을 바닥에 펼쳐 놓고 찍은 사진을 봅니다. 번호가 붙은 준비물마다 사진에 분명히 보이는지만 판단합니다. "
    "애매하거나 가려져 있으면 not_seen 으로 둡니다(아이가 직접 한 번 더 확인합니다). "
    "준비물에 조건이 있으면 조건에 맞는 물건일 때만 seen 입니다. '안 되는 것'으로 적힌 물건이 대신 놓여 있으면 그 준비물은 not_seen 이고, "
    "그 물건은 금지 목록 번호로 forbidden_seen 에 넣습니다. 금지 목록의 물건이 사진에 분명히 보이면 forbidden_seen 에 넣습니다. "
    "모든 준비물 번호는 seen 과 not_seen 가운데 한 곳에만 넣습니다. 사람 얼굴이나 이름표·이름 글자가 보이면 people_or_names 를 true 로 합니다."
)


class PhotoCheckPlus(BaseModel):
    seen: list[int] = Field(description="사진에서 분명히 보이고 조건에도 맞는 준비물 번호")
    not_seen: list[int] = Field(description="안 보이거나 확실하지 않은 준비물 번호")
    forbidden_seen: list[int] = Field(description="사진에서 분명히 보이는 금지 목록 번호. 없으면 빈 배열")
    people_or_names: bool = Field(description="사람 얼굴, 이름표, 이름 글자가 보이면 true")


async def photo_check_plus(items: list[dict], forbidden: list[str], media_type: str, data: bytes) -> dict:
    """items: [{name, condition, not_accepted}] → {seen:[번호], not_seen:[번호], forbidden_seen:[이름], people_or_names}"""
    lines = []
    for i, it in enumerate(items):
        extra = []
        if it.get("condition"):
            extra.append(f"조건: {it['condition']}")
        if it.get("not_accepted"):
            extra.append(f"안 되는 것: {', '.join(it['not_accepted'])}")
        lines.append(f"{i}. {it['name']}" + (f" ({' / '.join(extra)})" if extra else ""))
    ban = "\n".join(f"{i}. {n}" for i, n in enumerate(forbidden)) or "(없음)"
    resp = await client.messages.parse(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        system=SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": "준비물 목록:\n" + "\n".join(lines) + "\n\n금지 목록(가져오면 안 되는 것):\n" + ban},
        ]}],
        output_format=PhotoCheckPlus,
    )
    if resp.parsed_output is None:
        raise RuntimeError(f"사진 확인 실패 (stop_reason={resp.stop_reason})")
    out = resp.parsed_output
    seen = {i for i in out.seen if 0 <= i < len(items)}
    return {
        "seen": sorted(seen),
        "not_seen": [i for i in range(len(items)) if i not in seen],
        "forbidden_seen": [forbidden[i] for i in dict.fromkeys(out.forbidden_seen) if 0 <= i < len(forbidden)],
        "people_or_names": bool(out.people_or_names),
    }
