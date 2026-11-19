#!/usr/bin/env python3
"""가방쏙 예시 판을 '서버 없이 열리는 정적 페이지'로 묶는다(파이썬 표준 라이브러리만).

    python3 build_site.py            # <저장소>/docs/demo 에 만든다
    python3 build_site.py /tmp/out   # 다른 곳에 만든다

만드는 것
- index.html      : 프로토타입 틀(web_demo/shell.html). 엄마 화면과 아이 화면을 나란히 띄운다
- app/            : app/static 의 화면 파일 사본. 주소만 정적 페이지에 맞게 바꾸고 shim.js 를 끼운다
- pysrc.json      : 브라우저 안(Pyodide)에서 돌릴 계산 코드 묶음. 서버 판과 같은 파일이다
- boot.py         : 브라우저 안 시작 코드

화면과 계산 코드를 고쳤으면 이 파일을 다시 돌린다. docs/demo 안의 파일은 직접 고치지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
STATIC = os.path.join(HERE, "app", "static")
WEB = os.path.join(HERE, "web_demo")

# 브라우저 안에서 쓰는 계산 코드(모델 호출·FastAPI 가 필요한 파일은 넣지 않는다)
PY_FILES = [
    "demo_server.py", "app/db.py", "app/reminders.py", "app/weather.py",
    "app/chaeng/__init__.py", "app/chaeng/guard.py", "app/chaeng/recommend.py", "app/chaeng/service.py",
    "app/chaeng/simple_extract.py", "app/chaeng/tone.py", "app/chaeng/scenarios.json",
]
PAGES = {"index.html": "parent.html", "kid.html": "kid.html"}
TEXT_EXT = (".html", ".js", ".css")


def rewrite(text: str, is_page: bool) -> str:
    """서버 주소(/static/…, /kid?e=…, /)를 같은 폴더 기준 주소로 바꾼다."""
    text = text.replace("/static/", "")
    text = text.replace("/kid?e=", "kid.html?e=")
    text = text.replace('href="/"', 'href="parent.html"')
    if is_page:
        assert '<meta charset="utf-8">' in text
        text = text.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<script src="shim.js"></script>', 1)
    return text


def build(out: str) -> dict:
    app_out = os.path.join(out, "app")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(app_out)
    copied = []
    for root, _dirs, names in os.walk(STATIC):
        for name in sorted(names):
            if name.startswith("."):
                continue
            src = os.path.join(root, name)
            rel = os.path.relpath(src, STATIC)
            if rel in PAGES:
                rel = PAGES[rel]
            dst = os.path.join(app_out, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if name.endswith(TEXT_EXT):
                with open(src, encoding="utf-8") as f:
                    body = rewrite(f.read(), is_page=os.path.relpath(src, STATIC) in PAGES)
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(body)
            else:
                shutil.copyfile(src, dst)
            copied.append(rel)
    shutil.copyfile(os.path.join(WEB, "shim.js"), os.path.join(app_out, "shim.js"))
    shutil.copyfile(os.path.join(WEB, "shell.html"), os.path.join(out, "index.html"))
    shutil.copyfile(os.path.join(WEB, "boot.py"), os.path.join(out, "boot.py"))
    bundle = {}
    for rel in PY_FILES:
        with open(os.path.join(HERE, rel), encoding="utf-8") as f:
            bundle[rel] = f.read()
    with open(os.path.join(out, "pysrc.json"), "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False)
    left = []                                     # 서버 주소가 남았는지 본다(남으면 정적 페이지에서 깨진다)
    for rel in copied:
        if rel.endswith(TEXT_EXT):
            with open(os.path.join(app_out, rel), encoding="utf-8") as f:
                body = f.read()
            for bad in ('"/static', "'/static", 'href="/"', '"/kid', "`/kid"):
                if bad in body:
                    left.append(f"{rel}: {bad}")
    return {"out": out, "pages": sorted(PAGES.values()), "files": len(copied) + 4, "py": len(bundle), "left": left}


if __name__ == "__main__":
    target = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(REPO, "docs", "demo")
    info = build(target)
    print(f"만든 곳: {info['out']} · 파일 {info['files']}개 · 계산 코드 {info['py']}개")
    if info["left"]:
        print("서버 주소가 남은 곳:", *info["left"], sep="\n  ")
        sys.exit(1)
