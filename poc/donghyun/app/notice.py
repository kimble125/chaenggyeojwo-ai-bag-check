"""가정통신문 URL → 제목·본문·첨부 목록.

경기도교육청 학교 홈페이지(goesn.kr 등, /ntt/selectNttInfo.do) 게시판 구조를 우선 지원하고,
그 밖의 페이지는 본문 텍스트를 통째로 뽑습니다.
"""
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (school-notice-helper PoC)"
MAX_TEXT = 20000


def _text(node) -> str:
    # 한글 문서(HWP) 변환 HTML 은 글자가 span 으로 쪼개져 있어 문단(p/td) 단위로 붙인다.
    lines = []
    for p in node.find_all(["p", "li", "h1", "h2", "h3", "h4"]):
        if p.find(["p", "li"]):
            continue
        t = re.sub(r"\s+", " ", p.get_text("", strip=False)).strip()
        if t:
            lines.append(t)
    if not lines:
        lines = [l.strip() for l in node.get_text("\n").splitlines() if l.strip()]
    return "\n".join(lines)


async def fetch_notice(url: str) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as c:
        r = await c.get(url)
        r.raise_for_status()
        html = r.text
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "noscript"]):
        bad.extract()

    title, body, posted = None, None, None
    th = soup.select_one("th.title")
    cont = soup.select_one("tr.cont")
    if th and cont:  # 교육청 게시판
        title = th.get_text(" ", strip=True)
        body = _text(cont)
        m = re.search(r"등록일\s*</t[hd]>\s*<t[hd][^>]*>\s*([\d.\-]+)", html)
        posted = m.group(1) if m else None
    else:
        title = (soup.select_one("h1, h2, title") or soup).get_text(" ", strip=True)[:200]
        main = soup.select_one("article, main, #content, .content, body") or soup
        body = _text(main)

    attachments = [
        {"name": m.group(1), "url": urljoin(url, m.group(2))}
        for m in re.finditer(r"AddUploadedFile\('\d+',\s*'([^']+)',\s*'([^']+)'", html)
    ]
    for a in soup.select("a[href]"):
        if re.search(r"\.(hwp|hwpx|pdf)(\?|$)", a["href"], re.I) or "fileDown" in a["href"]:
            attachments.append({"name": a.get_text(strip=True) or a["href"], "url": urljoin(url, a["href"])})

    if not posted:
        m = re.search(r"(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})", soup.get_text(" "))
        posted = m.group(0) if m else None

    return {
        "title": title,
        "posted": posted,
        "text": (body or "")[:MAX_TEXT],
        "attachments": attachments,
        "url": url,
    }
