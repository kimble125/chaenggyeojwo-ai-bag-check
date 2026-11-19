"""준비물 추천(모델 호출 없음). 알림장 목록이 '등'으로 끝나거나 평소 일정일 때 빈자리를 채운다.

추천은 네 갈래이고 모두 '추천'이라고 표시한다(알림장에 적힌 것과 섞지 않는다).
1. 상황: 일정 제목으로 상황(현장체험학습, 생존수영 …)을 찾아 그 상황의 기본 준비물
2. 날씨·활동: 비·미세먼지·더위·추위·물에 젖는 활동·버스 이동
3. 아이: 보호자가 고른 특성(멀미, 안경 …). 약처럼 보호자가 정할 것은 보호자 화면에만 보인다
4. 꼬리표: 집에서 '항상 챙기는 것'으로 정해 둔 물건(지갑, 교통카드 …)
이미 목록에 있는 것(같은 뜻의 다른 이름 포함)은 추천하지 않는다.
"""
from __future__ import annotations

import json
import os
import re

DATA_PATH = os.path.join(os.path.dirname(__file__), "scenarios.json")
_GRADE_RANK = {"좋음": 0, "보통": 1, "나쁨": 2, "매우나쁨": 3}
_SYNONYMS = [
    {"물", "마실물", "물통", "음료", "생수", "텀블러", "물하나더"},
    {"우산", "우비", "우의", "비옷", "접이식우산", "우산또는우비", "우산또는우의", "우비여벌양말"},
    {"돗자리", "매트", "개인용돗자리"},
    {"물티슈", "휴지", "티슈"},
    {"필기도구", "연필", "필통", "펜", "알림장필통"},
    {"간식", "과자", "간식조금"},
    {"마스크", "kf80마스크", "kf94마스크"},
    {"겉옷", "외투", "점퍼", "바람막이", "따뜻한겉옷", "얇은겉옷"},
    {"여벌옷", "갈아입을옷", "여벌티셔츠"},
    {"수건", "손수건", "타월"},
    {"선크림", "썬크림", "자외선차단제"},
    {"비닐봉지", "비닐봉투", "비닐"},
    {"양말", "여벌양말", "속옷양말"},
    {"운동화", "편한신발"},
    {"체육복", "편한옷", "활동복", "간편한복장"},
    {"장갑", "장갑핫팩"},
    {"물안경", "수경"},
]
LIMITS = {"scenario": 5, "wear": 2, "weather": 4, "personal": 3}
_MEDICINE = re.compile(r"상비약|멀미약|알레르기 약|개인 약|기피제|(?<!치)약$")


def load(path: str | None = None) -> dict:
    with open(path or DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def norm(name: str) -> str:
    name = re.sub(r"[(（].*?[)）]", "", name or "")
    return re.sub(r"[\s·,/\-]+", "", name).lower()


def same(a: str, b: str) -> bool:
    """같은 물건으로 볼 수 있는가(이름이 같거나, 같은 뜻 묶음에 있거나, 한쪽이 다른 쪽을 품음)."""
    x, y = norm(a), norm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    def hit(v: str, g: set) -> bool:
        return v in g or any(len(m) >= 2 and m in v for m in g)
    if any(hit(x, g) and hit(y, g) for g in _SYNONYMS):
        return True
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    return len(short) >= 2 and short in long_ and short not in ("옷", "약")


def match_scenario(event: dict, data: dict) -> dict | None:
    """일정 제목·메모·장소에서 가장 많이 맞는 상황. 없으면 None."""
    hay = " | ".join(str(event.get(k) or "") for k in ("title", "location", "source_title"))   # 칸을 이어 붙여 생기는 가짜 낱말을 막는다
    best, score, fallback = None, 0, None
    for sc in data["scenarios"]:
        hits = sum(len(k) for k in sc.get("match", []) if k in hay)
        if not hits:
            continue
        if sc.get("fallback"):                       # 넓은 이름(현장체험학습)은 더 좁은 상황이 없을 때만
            fallback = fallback or sc
        elif hits > score:
            best, score = sc, hits
    return best or fallback


def flags(event: dict, scenario: dict | None) -> set[str]:
    """날씨와 활동에서 조건 꼬리표를 만든다."""
    out: set[str] = set(scenario.get("tags", []) if scenario else [])
    if event.get("outdoor"):
        out.add("outdoor")
    hay = " ".join(str(event.get(k) or "") for k in ("title", "notes", "location"))
    if re.search(r"버스|전세|차량 ?이동", hay):
        out.add("bus")
    if re.search(r"물놀이|수영|하천|갯벌|계곡|물총", hay):
        out.add("wet_activity")
    w = event.get("weather") or {}
    if w.get("status") == "ok":
        prob = w.get("rain_prob_window") if w.get("rain_prob_window") is not None else w.get("rain_prob")
        if (prob is not None and prob >= 30) or (w.get("rain_mm") or 0) >= 1 or w.get("rain_signal") in ("rain", "maybe"):
            out.add("rain")
        worst = max([_GRADE_RANK.get(g, 0) for g in (w.get("pm10_grade"), w.get("pm25_grade")) if g] or [0])
        if worst >= 2:
            out.add("dust_bad")
        if w.get("t_max") is not None and w["t_max"] >= 28:
            out.add("hot")
        if w.get("t_min") is not None and w["t_min"] <= 5:
            out.add("cold")
    return out


def _basis(item: dict) -> str:
    n = len(item.get("seen_in") or [])
    return f"비슷한 알림장 {n}건에서 봤어요" if n else "챙겼지 제안"


def _rec(item: dict, group: str) -> dict:
    return {
        "name": item["name"], "emoji": item.get("emoji", "🎒"), "kind": item.get("kind", "carry"),
        "why": re.sub(r"\s*\[제안\]\s*$", "", item.get("why", "")), "group": group, "basis": _basis(item),
        "guardian_decides": bool(item.get("guardian_decides")) or bool(_MEDICINE.search(item["name"])),   # 약은 보호자가 정한다
    }


def recommend(event: dict, profile: dict | None = None, forgot: dict | None = None,
              declined: list[str] | None = None, data: dict | None = None,
              exclude: list[str] | None = None) -> dict:
    """일정 하나에 대한 추천.

    event: {title, notes, location, outdoor, weather, items:[{name, source}]}
    profile: {traits:[...], always:[...]}   forgot: {물건 이름: 깜빡한 횟수}
    돌려주는 것: {scenario, flags, recs:[...], watch:[...]}
    """
    data = data or load()
    profile = profile or {}
    have = [i["name"] for i in event.get("items", [])]
    skip = list(have) + list(declined or []) + list(exclude or [])   # exclude: 알림장이 가져오지 말라고 한 것
    scenario = match_scenario(event, data)
    fl = flags(event, scenario)
    recs: list[dict] = []

    def add(item: dict, group: str) -> bool:
        if any(same(item["name"], s) for s in skip):
            return False
        recs.append(_rec(item, group))
        skip.append(item["name"])
        return True

    for name in profile.get("always") or []:               # 꼬리표: 항상 챙기는 것
        if add({"name": name, "emoji": "🏷️", "why": "항상 챙기기로 한 물건이에요", "seen_in": []}, "tag"):
            recs[-1]["basis"] = "우리 집 꼬리표"

    if scenario:
        n = 0
        for it in scenario.get("defaults", []):
            if n < LIMITS["scenario"] and add(it, "scenario"):
                n += 1
        n = 0
        for it in scenario.get("wear", []):
            if n < LIMITS["wear"] and add(it, "scenario"):
                n += 1

    n = 0
    for it in data.get("conditional", []):
        if it["when"] not in fl:
            continue
        if it.get("needs_tag") and it["needs_tag"] not in fl:
            continue
        if it.get("needs_trait") and it["needs_trait"] not in (profile.get("traits") or []):
            continue
        if n < LIMITS["weather"] and add(it, "weather"):
            n += 1

    n = 0
    for p in data.get("personal", []):
        if p["trait"] not in (profile.get("traits") or []):
            continue
        for it in p.get("add", []):
            if it.get("needs_tag") and it["needs_tag"] not in fl:
                continue
            if n < LIMITS["personal"] and add(it, "personal"):
                recs[-1]["why"] = recs[-1]["why"] or p.get("label", "")
                n += 1

    watch = [h for h in have if any(same(h, k) and c >= 1 for k, c in (forgot or {}).items())]
    return {
        "scenario": {"id": scenario["id"], "name": scenario["name"]} if scenario else None,
        "flags": sorted(fl),
        "often_forbidden": [f["name"] for f in (scenario or {}).get("often_forbidden", [])],
        "recs": recs,
        "watch": watch,
    }


def starter_items(scenario_id: str, data: dict | None = None) -> list[dict]:
    """알림장 없는 평소 일정을 만들 때의 기본 준비물(전부 '추천' 출처)."""
    data = data or load()
    sc = next((s for s in data["scenarios"] if s["id"] == scenario_id), None)
    if not sc:
        return []
    return [_rec(it, "scenario") for it in sc.get("defaults", []) + sc.get("wear", [])]
