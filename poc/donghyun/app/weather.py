"""Open-Meteo(키 불필요)로 일정 당일 날씨·미세먼지를 보고 준비물을 추천.

- 강수: 일 최대 강수확률 / 강수량
- 미세먼지: 행사 시간대(없으면 08~18시) PM10·PM2.5 최댓값, 환경부 등급 기준
"""
from datetime import date as Date, datetime, timedelta

import httpx

FORECAST = "https://api.open-meteo.com/v1/forecast"
METNO = "https://api.met.no/weatherapi/locationforecast/2.0/complete"   # 폴백 (약 9일)
UA = {"User-Agent": "school-notice-helper-poc/0.1"}
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
FORECAST_DAYS = 16   # 날씨 예보 범위
AIR_DAYS = 5         # 미세먼지 예보 범위

# 환경부 통합 예보 등급 (㎍/㎥)
PM10_GRADES = [(30, "좋음"), (80, "보통"), (150, "나쁨"), (10**9, "매우나쁨")]
PM25_GRADES = [(15, "좋음"), (35, "보통"), (75, "나쁨"), (10**9, "매우나쁨")]
GRADE_RANK = {"좋음": 0, "보통": 1, "나쁨": 2, "매우나쁨": 3}

WMO = {0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "안개",
       51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비", 61: "약한 비", 63: "비", 65: "강한 비",
       66: "어는 비", 67: "어는 비", 71: "약한 눈", 73: "눈", 75: "강한 눈", 77: "싸락눈",
       80: "소나기", 81: "소나기", 82: "강한 소나기", 85: "눈 소나기", 86: "눈 소나기",
       95: "뇌우", 96: "뇌우(우박)", 99: "뇌우(우박)"}


def grade(v, table):
    if v is None:
        return None
    for limit, name in table:
        if v <= limit:
            return name


def _hours(start_time: str | None, end_time: str | None) -> tuple[int, int]:
    s = int(start_time[:2]) if start_time else 8
    e = int(end_time[:2]) if end_time else max(s + 1, 18)
    return s, max(e, s)


async def fetch_outlook(lat: float, lon: float, day: str, start_time=None, end_time=None) -> dict | None:
    d = Date.fromisoformat(day)
    ahead = (d - Date.today()).days
    if ahead < 0:
        return {"status": "past"}
    if ahead >= FORECAST_DAYS:
        return {"status": "too_far", "days_ahead": ahead, "available_from": FORECAST_DAYS - 1}

    out = {"status": "ok", "date": day, "lat": lat, "lon": lon}
    s, e = _hours(start_time, end_time)
    async with httpx.AsyncClient(timeout=10, headers=UA) as c:
        try:
            out.update(await _open_meteo(c, lat, lon, day, s, e))
        except httpx.HTTPError:
            if ahead > 9:
                return {"status": "too_far", "days_ahead": ahead, "available_from": 9}
            out.update(await _metno(c, lat, lon, day, s, e))

        if ahead < AIR_DAYS:
            r = await c.get(AIR, params={
                "latitude": lat, "longitude": lon, "timezone": "Asia/Seoul",
                "start_date": day, "end_date": day, "hourly": "pm10,pm2_5",
            })
            if r.status_code == 200:
                h = r.json()["hourly"]
                win = [i for i, t in enumerate(h["time"]) if s <= int(t[11:13]) <= e]
                pm10 = [h["pm10"][i] for i in win if h["pm10"][i] is not None]
                pm25 = [h["pm2_5"][i] for i in win if h["pm2_5"][i] is not None]
                out["pm10"] = round(max(pm10)) if pm10 else None
                out["pm25"] = round(max(pm25)) if pm25 else None
        else:
            out["air_note"] = f"미세먼지 예보는 {AIR_DAYS}일 전부터 확인돼요"
    out["pm10_grade"] = grade(out.get("pm10"), PM10_GRADES)
    out["pm25_grade"] = grade(out.get("pm25"), PM25_GRADES)
    out["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return out


async def _open_meteo(c, lat, lon, day, s, e) -> dict:
    r = await c.get(FORECAST, timeout=5, params={
        "latitude": lat, "longitude": lon, "timezone": "Asia/Seoul",
        "start_date": day, "end_date": day,
        "daily": "weather_code,precipitation_probability_max,precipitation_sum,temperature_2m_max,temperature_2m_min",
        "hourly": "precipitation_probability",
    })
    r.raise_for_status()
    j = r.json()
    dd = j["daily"]
    hp = [p for t, p in zip(j["hourly"]["time"], j["hourly"]["precipitation_probability"])
          if p is not None and s <= int(t[11:13]) <= e]
    return {
        "provider": "Open-Meteo",
        "weather": WMO.get(dd["weather_code"][0], "-"),
        "rain_prob": dd["precipitation_probability_max"][0],
        "rain_prob_window": max(hp) if hp else None,
        "rain_mm": dd["precipitation_sum"][0],
        "t_max": dd["temperature_2m_max"][0],
        "t_min": dd["temperature_2m_min"][0],
    }


METNO_KO = [("thunder", "뇌우"), ("sleet", "진눈깨비"), ("heavysnow", "강한 눈"), ("snow", "눈"),
            ("heavyrain", "강한 비"), ("lightrain", "약한 비"), ("rain", "비"), ("fog", "안개"),
            ("cloudy", "흐림"), ("partlycloudy", "구름 조금"), ("fair", "대체로 맑음"), ("clearsky", "맑음")]


def _ko(sym: str | None) -> str:
    for k, v in METNO_KO:
        if sym and k in sym:
            return v
    return "-"


async def _metno(c, lat, lon, day, s, e) -> dict:
    """MET Norway: 시각별 강수량·기호로 확률 대신 '비 신호'를 만든다."""
    r = await c.get(METNO, params={"lat": round(lat, 4), "lon": round(lon, 4)})
    r.raise_for_status()
    temps, mm, win_mm, syms, win_syms = [], 0.0, 0.0, [], []
    for t in r.json()["properties"]["timeseries"]:
        kst = datetime.fromisoformat(t["time"].replace("Z", "+00:00")) + timedelta(hours=9)
        if kst.date().isoformat() != day:
            continue
        d = t["data"]
        temps.append(d["instant"]["details"]["air_temperature"])
        nxt = d.get("next_1_hours") or d.get("next_6_hours") or {}
        amt = (nxt.get("details") or {}).get("precipitation_amount") or 0
        sym = (nxt.get("summary") or {}).get("symbol_code")
        hrs = 1 if "next_1_hours" in d else 6
        mm += amt
        syms.append(sym)
        if kst.hour <= e and kst.hour + hrs > s:
            win_mm += amt; win_syms.append(sym)
    wet = [x for x in win_syms if x and any(k in x for k in ("rain", "sleet", "snow", "thunder"))]
    main = max(set(win_syms or syms), key=(win_syms or syms).count) if (win_syms or syms) else None
    return {
        "provider": "MET Norway",
        "weather": _ko(wet[0] if wet else main),
        "rain_prob": None, "rain_prob_window": None,
        "rain_mm": round(mm, 1), "rain_mm_window": round(win_mm, 1),
        "rain_signal": "rain" if win_mm >= 0.5 or len(wet) >= 2 else ("maybe" if wet or win_mm > 0 else "none"),
        "t_max": max(temps) if temps else None,
        "t_min": min(temps) if temps else None,
    }


def recommend(o: dict | None, outdoor: bool) -> list[dict]:
    """날씨 → 준비물. [{name, reason}]"""
    if not o or o.get("status") != "ok":
        return []
    items = []
    prob = o.get("rain_prob_window") if o.get("rain_prob_window") is not None else o.get("rain_prob")
    mm = o.get("rain_mm") or 0
    snow = "눈" in (o.get("weather") or "")
    if prob is not None:
        level = "rain" if prob >= 60 or mm >= 1 else "maybe" if prob >= 30 else "none"
        why = f"{o['weather']} · 강수확률 {prob}% · 예상 {mm}mm"
    else:  # 확률이 없는 예보(MET Norway)
        level = o.get("rain_signal", "none")
        why = f"{o['weather']} · 활동 시간 강수 {o.get('rain_mm_window', mm)}mm 예보"
    if level == "rain":
        items.append({"name": "우산", "reason": why})
        if outdoor:
            items.append({"name": "우비·여벌 양말", "reason": "야외 활동인데 비 예보가 있어요"})
    elif level == "maybe":
        items.append({"name": "접이식 우산", "reason": why + " — 혹시 모르니 가방에"})
    if snow and not any(i["name"] == "우산" for i in items):
        items.append({"name": "우산", "reason": f"{o['weather']} 예보"})

    g = max([x for x in (o.get("pm10_grade"), o.get("pm25_grade")) if x] or ["좋음"], key=GRADE_RANK.get)
    if GRADE_RANK[g] >= 2:
        mask = "KF94 마스크" if g == "매우나쁨" else "KF80 마스크"
        items.append({"name": mask, "reason": f"미세먼지 {g} (PM10 {o.get('pm10')}, PM2.5 {o.get('pm25')}㎍/㎥)"})

    tmin, tmax = o.get("t_min"), o.get("t_max")
    if tmin is not None and tmin <= 0 and outdoor:
        items.append({"name": "장갑·핫팩", "reason": f"최저 {tmin}°C — 야외 활동이라 추워요"})
    elif tmin is not None and tmin <= 5:
        items.append({"name": "따뜻한 겉옷", "reason": f"최저 {tmin}°C"})
    if tmax is not None and tmax >= 30 and outdoor:
        items.append({"name": "모자·여분 물", "reason": f"최고 {tmax}°C — 더위 대비"})
    return items
