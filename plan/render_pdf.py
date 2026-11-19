#!/usr/bin/env python3
"""가방쏙 2쪽 기획안을 브라우저 없이 PDF 로 만든다(Pillow 로 쪽을 그려 묶는다).

    python3 plan/render_pdf.py            # plan/gabangssok_plan.pdf

- 원고는 build_plan.py 의 ROWS 를 그대로 쓴다(먼저 build_plan.py 를 돌려 그림을 만들어 둔다).
- 글자 크기를 큰 것부터 줄여 가며 2쪽에 들어가는 가장 큰 크기를 고른다.
- 글자가 그림으로 들어가므로 PDF 안의 글은 복사되지 않는다. 글이 필요한 사람은 .docx 나 proposal.md 를 본다.
  (브라우저가 되면 gabangssok_plan.html 을 A4 로 인쇄한 PDF 가 더 낫다.)
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_plan as bp  # noqa: E402

DPI = 220
MM = DPI / 25.4
PT = DPI / 72
W, H = round(210 * MM), round(297 * MM)
MX, MY = 14 * MM, 11 * MM
LABEL_W = 24 * MM
PAD_X, PAD_Y = 1.7 * MM, 1.25 * MM
VIOLET, INK, SOFT, LINE, LABEL_BG = (106, 72, 240), (22, 24, 42), (98, 97, 109), (154, 151, 168), (239, 234, 255)


def fnt(pt, bold=False):
    return ImageFont.truetype(bp.FONT, max(8, round(pt * PT)), index=6 if bold else 0)


def tokens(text):
    """(낱말, 굵게) 목록. 빈칸에서 줄을 바꾼다."""
    out = []
    for seg, bold in bp.parts(text):
        for i, word in enumerate(seg.split(" ")):
            if i:
                out.append((" ", bold))
            if word:
                out.append((word, bold))
    return out


def layout_lines(draw, text, size, width, bold_all=False):
    """줄마다 [(글, 굵게)] 를 돌려준다."""
    reg, bold = fnt(size), fnt(size, True)
    lines, cur, cur_w = [], [], 0.0
    for word, b in tokens(text):
        f = bold if (b or bold_all) else reg
        w = draw.textlength(word, font=f)
        if word == " ":
            if cur:
                cur.append((word, b)); cur_w += w
            continue
        if cur and cur_w + w > width:
            while cur and cur[-1][0] == " ":
                cur.pop()
            lines.append(cur); cur, cur_w = [], 0.0
        if w > width:                                  # 한 낱말이 줄보다 길면 글자 단위로 자른다
            piece = ""
            for ch in word:
                if draw.textlength(piece + ch, font=f) > width and piece:
                    lines.append([(piece, b)]); piece = ""
                piece += ch
            cur, cur_w = [(piece, b)], draw.textlength(piece, font=f)
        else:
            cur.append((word, b)); cur_w += w
    if cur:
        lines.append(cur)
    return lines


class Doc:
    def __init__(self, size):
        self.size = size
        self.lh = size * PT * 1.36
        self.pages = []
        self.new_page()

    def new_page(self):
        self.im = Image.new("RGB", (W, H), "white")
        self.d = ImageDraw.Draw(self.im)
        self.pages.append(self.im)
        self.y = MY

    def bottom(self):
        return H - MY

    def draw_line(self, x, y, line, size, color=INK, bold_all=False):
        reg, bold = fnt(size), fnt(size, True)
        for word, b in line:
            f = bold if (b or bold_all) else reg
            self.d.text((x, y), word, font=f, fill=color)
            x += self.d.textlength(word, font=f)


def render(size):
    doc = Doc(size)
    d = doc.d
    # 머리: 마스코트, 제목, 한 줄 소개, 대회 이름
    mh = 12 * MM
    mascot = Image.open(bp.MASCOT).convert("RGBA")
    mascot = mascot.resize((round(mascot.width * mh / mascot.height), round(mh)), Image.LANCZOS)
    doc.im.paste(mascot, (round(MX), round(doc.y)), mascot)
    tx = MX + mascot.width + 3 * MM
    ft = fnt(18, True)
    d.text((tx, doc.y + 1.6 * MM), bp.TITLE, font=ft, fill=VIOLET)
    tw = d.textlength(bp.TITLE, font=ft)
    d.text((tx + tw + 4 * MM, doc.y + 4.3 * MM), bp.TAGLINE, font=fnt(11, True), fill=INK)
    fm = fnt(8.5)
    d.text((W - MX - d.textlength(bp.META, font=fm), doc.y + 0.4 * MM), bp.META, font=fm, fill=SOFT)
    doc.y += mh + 1.8 * MM

    cx = MX + LABEL_W
    cw = W - MX - cx - PAD_X * 2
    lw = max(1, round(0.25 * MM))

    def close_segment(y0, y1, label, first):
        """표의 한 줄(또는 쪽에 걸친 조각)의 테두리와 왼쪽 칸을 그린다."""
        dd = doc.d
        dd.rectangle([MX, y0, cx, y1], fill=LABEL_BG, outline=LINE, width=lw)
        dd.rectangle([cx, y0, W - MX, y1], outline=LINE, width=lw)
        lab = label if first else label.split(". ")[0] + ". (이어짐)"
        for k, ln in enumerate(layout_lines(dd, lab, size, LABEL_W - PAD_X * 2, bold_all=True)):
            doc.draw_line(MX + PAD_X, y0 + PAD_Y + k * doc.lh, ln, size, bold_all=True)

    pending = []                                      # 테두리는 내용을 다 놓은 뒤에 그린다(왼쪽 칸 바탕이 글을 덮지 않게 먼저 그리려면 두 번 돈다)
    for label, items in bp.ROWS:
        y0, first = doc.y, True
        doc.y += PAD_Y
        for it in items:
            kind = it[0]
            if kind == "img":
                img = Image.open(os.path.join(bp.IMG, it[1])).convert("RGB")
                iw = it[2] * MM
                ih = img.height * iw / img.width
                need = ih + 1.6 * MM
                block = ("img", img.resize((round(iw), round(ih)), Image.LANCZOS))
            else:
                indent = {"b": 3.2 * MM, "n": 3.6 * MM}.get(kind, 0)
                text = it[1]
                lines = layout_lines(doc.d, text, size, cw - indent, bold_all=(kind == "h"))
                need = len(lines) * doc.lh + (0.8 * MM if kind == "h" else 0)
                block = (kind, lines, indent)
            if doc.y + need + PAD_Y > doc.bottom():
                pending.append((len(doc.pages) - 1, y0, doc.y, label, first))
                doc.new_page()
                y0, first = doc.y, False
                doc.y += PAD_Y
            if block[0] == "img":
                doc.im.paste(block[1], (round(cx + (W - MX - cx - block[1].width) / 2), round(doc.y + 0.8 * MM)))
            else:
                kind, lines, indent = block
                if kind == "h":
                    doc.y += 0.8 * MM if doc.y > y0 + PAD_Y + 1 else 0
                x = cx + PAD_X
                if kind == "b":
                    doc.d.text((x, doc.y), "•", font=fnt(size), fill=INK)
                for k, ln in enumerate(lines):
                    hang = 0 if (kind == "n" and k == 0) else indent
                    doc.draw_line(x + hang, doc.y + k * doc.lh, ln, size, color=VIOLET if kind == "h" else INK, bold_all=(kind == "h"))
                need = len(lines) * doc.lh
            doc.y += need
        doc.y += PAD_Y
        pending.append((len(doc.pages) - 1, y0, doc.y, label, first))
    # 테두리와 왼쪽 칸(글 위에 덮이지 않게, 왼쪽 칸은 글이 없는 자리다)
    for page_i, y0, y1, label, first in pending:
        doc.im, doc.d = doc.pages[page_i], ImageDraw.Draw(doc.pages[page_i])
        close_segment(y0, y1, label, first)
    doc.im, doc.d = doc.pages[-1], ImageDraw.Draw(doc.pages[-1])
    # 꼬리: PoC 주소와 출처
    doc.y += 1.2 * MM
    fs = max(7.5, size - 2)
    flh = fs * PT * 1.36
    for line in bp.FOOT:
        lines = layout_lines(doc.d, line, fs, W - MX * 2)
        if doc.y + len(lines) * flh > doc.bottom():
            doc.new_page()
        for k, ln in enumerate(lines):
            doc.draw_line(MX, doc.y + k * flh, ln, fs, color=(70, 70, 82))
        doc.y += len(lines) * flh + 0.9 * MM
    return doc


if __name__ == "__main__":
    out = os.path.join(bp.HERE, "gabangssok_plan.pdf")
    chosen = None
    for size in (10.6, 10.4, 10.2, 10.0, 9.8, 9.6, 9.4, 9.2, 9.0, 8.8):
        doc = render(size)
        if len(doc.pages) <= 2:
            chosen = (size, doc)
            break
    if not chosen:
        print("2쪽에 넣지 못했다. 원고를 줄여야 한다."); sys.exit(1)
    size, doc = chosen
    used = (doc.y - MY) / (H - 2 * MY)
    doc.pages[0].save(out, "PDF", resolution=DPI, save_all=True, append_images=doc.pages[1:], quality=93)
    for i, pg in enumerate(doc.pages, 1):
        pg.resize((W // 2, H // 2), Image.LANCZOS).save(os.path.join(bp.IMG, f"preview_p{i}.png"), optimize=True)
    print(f"만듦: {out} · {len(doc.pages)}쪽 · 본문 {size}pt · 마지막 쪽 {used:.0%} 참")
