"""SQLite 저장소. 캘린더 MCP 서버와 웹 API 가 같은 DB 를 씁니다."""
import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'event',          -- event | deadline | etc
  date TEXT NOT NULL,                          -- YYYY-MM-DD
  start_time TEXT, end_time TEXT,              -- HH:MM
  location TEXT, lat REAL, lon REAL,
  outdoor INTEGER NOT NULL DEFAULT 0,
  target TEXT, notes TEXT,
  source_title TEXT, source_url TEXT,
  weather_json TEXT, weather_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'notice',       -- notice | ai | weather | user
  reason TEXT,
  checked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                          -- eve | morning | test
  fire_at TEXT NOT NULL,                       -- YYYY-MM-DD HH:MM (KST)
  message TEXT,
  delivered_at TEXT,
  UNIQUE(event_id, kind)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with tx() as con:
        con.executescript(SCHEMA)
        con.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES('home', ?)",
            (json.dumps({"name": "성남시 분당구", "lat": 37.3827, "lon": 127.1189}, ensure_ascii=False),),
        )


def get_setting(key: str, default=None):
    with tx() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value):
    with tx() as con:
        con.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def event_dict(con, row) -> dict:
    ev = dict(row)
    ev["outdoor"] = bool(ev["outdoor"])
    ev["weather"] = json.loads(ev.pop("weather_json") or "null")
    ev["items"] = [
        dict(r) | {"checked": bool(r["checked"])}
        for r in con.execute("SELECT * FROM items WHERE event_id=? ORDER BY id", (ev["id"],))
    ]
    return ev


def list_events(start: str | None = None, end: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM events WHERE 1=1", []
    if start:
        q += " AND date >= ?"; args.append(start)
    if end:
        q += " AND date <= ?"; args.append(end)
    q += " ORDER BY date, COALESCE(start_time,'99:99'), id"
    with tx() as con:
        return [event_dict(con, r) for r in con.execute(q, args).fetchall()]


def get_event(event_id: int) -> dict | None:
    with tx() as con:
        row = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return event_dict(con, row) if row else None


EVENT_FIELDS = ["title", "kind", "date", "start_time", "end_time", "location", "lat", "lon",
                "outdoor", "target", "notes", "source_title", "source_url"]


def insert_event(data: dict, items: list[dict]) -> int:
    vals = {k: data.get(k) for k in EVENT_FIELDS}
    vals["outdoor"] = 1 if vals.get("outdoor") else 0
    vals["kind"] = vals.get("kind") or "event"
    with tx() as con:
        cur = con.execute(
            f"INSERT INTO events({','.join(vals)}) VALUES({','.join('?' * len(vals))})",
            list(vals.values()),
        )
        eid = cur.lastrowid
        for it in items:
            con.execute(
                "INSERT INTO items(event_id,name,source,reason) VALUES(?,?,?,?)",
                (eid, it["name"], it.get("source", "notice"), it.get("reason")),
            )
    return eid


def update_event(event_id: int, data: dict):
    vals = {k: data[k] for k in EVENT_FIELDS if k in data}
    if "outdoor" in vals:
        vals["outdoor"] = 1 if vals["outdoor"] else 0
    if not vals:
        return
    with tx() as con:
        con.execute(
            f"UPDATE events SET {','.join(f'{k}=?' for k in vals)} WHERE id=?",
            [*vals.values(), event_id],
        )


def delete_event(event_id: int) -> bool:
    with tx() as con:
        return con.execute("DELETE FROM events WHERE id=?", (event_id,)).rowcount > 0


def add_item(event_id: int, name: str, source="user", reason=None) -> int:
    with tx() as con:
        return con.execute(
            "INSERT INTO items(event_id,name,source,reason) VALUES(?,?,?,?)",
            (event_id, name, source, reason),
        ).lastrowid


def set_item_checked(item_id: int, checked: bool):
    with tx() as con:
        con.execute("UPDATE items SET checked=? WHERE id=?", (1 if checked else 0, item_id))


def delete_item(item_id: int):
    with tx() as con:
        con.execute("DELETE FROM items WHERE id=?", (item_id,))


def replace_weather(event_id: int, weather: dict | None, items: list[dict], fetched_at: str):
    """날씨 준비물은 매번 다시 계산. 같은 이름이면 체크 상태를 유지."""
    with tx() as con:
        prev = {r["name"]: r["id"] for r in con.execute(
            "SELECT id, name FROM items WHERE event_id=? AND source='weather'", (event_id,))}
        keep = set()
        for it in items:
            if it["name"] in prev:        # 같은 이름은 같은 줄을 고쳐 쓴다(번호와 체크 유지)
                con.execute("UPDATE items SET reason=? WHERE id=?", (it["reason"], prev[it["name"]]))
                keep.add(prev[it["name"]])
            else:
                con.execute(
                    "INSERT INTO items(event_id,name,source,reason,checked) VALUES(?,?, 'weather', ?, 0)",
                    (event_id, it["name"], it["reason"]),
                )
        for name, iid in prev.items():
            if iid not in keep:
                con.execute("DELETE FROM items WHERE id=?", (iid,))
        con.execute(
            "UPDATE events SET weather_json=?, weather_at=? WHERE id=?",
            (json.dumps(weather, ensure_ascii=False) if weather else None, fetched_at, event_id),
        )
