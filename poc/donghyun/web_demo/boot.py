"""브라우저 안(Pyodide)에서 예시 서버의 계산 코드를 그대로 쓰기 위한 시작 코드.

서버 판과 같은 파일(demo_server.py, app/…)을 읽어 들이고, HTTP 대신 dispatch() 로 주소표를 부른다.
저장은 이 탭의 메모리 안 SQLite 뿐이다. 새로 고치면 처음 상태로 돌아간다.
바깥(JS)이 WEATHER_ONLINE 을 먼저 넣어 준다.
"""
import json
import os
import sys
import urllib.parse

os.environ["DB_PATH"] = "/data/demo.db"
sys.path.insert(0, "/chaeng")

import demo_server as d  # noqa: E402


def _offline(url, params):
    raise OSError("날씨 서버에 닿지 않아요")


if globals().get("WEATHER_ONLINE"):
    from pyodide.http import open_url          # 브라우저의 동기 요청(Open-Meteo 는 키가 없고 다른 사이트에서 불러도 된다)

    def _get_json(url, params):
        return json.loads(open_url(url + "?" + urllib.parse.urlencode(params)).read())

    d._get_json = _get_json
else:
    d._get_json = _offline


def _example_weather_if_none():
    """날씨를 못 가져왔으면 첫 야외 일정에 '시연용 가정' 날씨를 붙인다(화면에 가정이라고 나온다)."""
    for ev in d.db.list_events():
        if ev["kind"] != "deadline" and ev["outdoor"] and not ev.get("weather"):
            d.refresh_weather(ev, force=True, simulate="rain")
            return


def start(reset=False):
    d.boot(reset=bool(reset))
    _example_weather_if_none()
    return len(d.db.list_events())


def call(method, path, query_json, body_json, fields_json, n_files):
    code, out = d.dispatch(
        method, path, json.loads(query_json or "{}"), json.loads(body_json) if body_json else None,
        json.loads(fields_json or "{}"), [("image", "image/jpeg", b"")] * int(n_files or 0))
    return json.dumps([code, out], ensure_ascii=False, default=str)
