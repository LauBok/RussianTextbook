#!/usr/bin/env python3
"""语法点分布图：第一至三册每个语法点在哪些课讲过。首页三册汇总，之后一册一页点阵（A3 横向）。

    python3 tools/grammap.py  →  dist/语法点分布图.pdf

分类在 docs/语法点分类.json（[组名, [[id, 名称], …]]），各课标注在 docs/语法点标注.json
（{课号: [id, …]}）。实心点为新授课，空心点为复习课。
"""
import html
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402

ROOT = book.ROOT
ACCENT, MUTED, RULE, BAND = "#8a2b2b", "#6b6b6b", "#e3dbd0", "#f4ede4"
W, H, M = 420, 297, 12          # A3 横向，毫米
LABEL, COUNT, TOP, ROW = 78, 12, 24, 3.2


def esc(s):
    return html.escape(str(s))


def page(books, tax, tags):
    """books 只有一册时按单元分色带；多册（汇总页）时按册分色带，右侧分册计数。"""
    summary = len(books) > 1
    codes = [c for n in books for c in book.lesson_codes(n) if not re.search(r"T[012]$", c)]
    fms = {c: book.front_matter((ROOT / "lessons" / f"{c}.md").read_text(encoding="utf-8")) for c in codes}
    bk = {c: (1 if re.match(r"[PL]", c) else int(c[1])) for c in codes}
    count_w = 24 if summary else COUNT
    gw = W - 2 * M - LABEL - count_w
    cw = gw / len(codes)
    x0 = M + LABEL
    rows = []
    for g, items in tax:
        rows.append(("group", g))
        rows += [("item", i, name) for i, name in items]
    height = TOP + ROW * len(rows) + 6
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W - 2 * M}mm" height="{height}mm" '
         f'viewBox="{M} 0 {W - 2 * M} {height}" font-family="Noto Sans CJK SC, PT Sans, sans-serif">']

    # 单元色带与单元名
    spans, cur = [], None
    for i, c in enumerate(codes):
        u = book.BOOK_NAME[bk[c]] if summary else fms[c].get("unit", "")
        if not spans or spans[-1][0] != u:
            spans.append([u, i, i])
        spans[-1][2] = i
    for k, (u, a, b) in enumerate(spans):
        xa, xb = x0 + a * cw, x0 + (b + 1) * cw
        if k % 2 == 0:
            s.append(f'<rect x="{xa}" y="{TOP - 9}" width="{xb - xa}" height="{height - TOP + 9}" fill="{BAND}"/>')
        name = re.sub(r"^第(.+?)单元\s*", r"\1 ", u) if (xb - xa) < 30 else u
        name = re.sub(r"^语音入门.*", "语音", name)
        s.append(f'<text x="{(xa + xb) / 2}" y="{TOP - 11}" font-size="2.3" fill="{MUTED}" text-anchor="middle">{esc(name)}</text>')

    # 课号刻度
    for i, c in enumerate(codes):
        num = re.search(r"(\d+)$", c).group(1).lstrip("0")
        label = ("P" + num) if c.startswith("P") else num
        step = 10 if summary else 5
        if summary:
            show = c == "P1" or (c[0] != "P" and int(num) % step == 0 and int(num) < 100)
        else:
            show = c in ("P1", "P8") or (c[0] != "P" and (int(num) % step == 0 or int(num) == 1))
        if show:
            s.append(f'<text x="{x0 + (i + .5) * cw}" y="{TOP - 3}" font-size="2" fill="{MUTED}" text-anchor="middle">{label}</text>')

    y = TOP
    for r in rows:
        if r[0] == "group":
            y += .6
            s.append(f'<line x1="{M}" x2="{W - M}" y1="{y}" y2="{y}" stroke="{ACCENT}" stroke-width=".25"/>')
            s.append(f'<text x="{M}" y="{y + 2.6}" font-size="2.5" font-weight="700" fill="{ACCENT}">{esc(r[1])}</text>')
            y += ROW - .6
            continue
        _, gid, name = r
        cy = y + ROW / 2
        s.append(f'<line x1="{x0}" x2="{x0 + gw}" y1="{cy}" y2="{cy}" stroke="{RULE}" stroke-width=".15"/>')
        s.append(f'<text x="{M + 3}" y="{cy + .8}" font-size="2.3" fill="#1f1f1f">{esc(name)}</text>')
        hits = {n: 0 for n in books}
        for i, c in enumerate(codes):
            if gid not in tags.get(c, []):
                continue
            hits[bk[c]] += 1
            cx = x0 + (i + .5) * cw
            rad = min(cw, ROW) * .36
            title = f"{book.lesson_label(fms[c]) if hasattr(book, 'lesson_label') else c}"
            if str(fms[c].get("title", "")).startswith("Повтор"):
                s.append(f'<circle cx="{cx}" cy="{cy}" r="{rad * .85}" fill="#fff" stroke="{ACCENT}" stroke-width=".3"><title>{esc(title)}</title></circle>')
            else:
                s.append(f'<circle cx="{cx}" cy="{cy}" r="{rad}" fill="{ACCENT}"><title>{esc(title)}</title></circle>')
        for j, n in enumerate(reversed(books)):
            s.append(f'<text x="{W - M - j * 7}" y="{cy + .8}" font-size="2.2" fill="{MUTED}" text-anchor="end">{hits[n]}</text>')
        y += ROW
    if summary:
        for j, n in enumerate(reversed(books)):
            s.append(f'<text x="{W - M - j * 7}" y="{TOP - 3}" font-size="2" fill="{MUTED}" text-anchor="end">{"一二三四"[n - 1]}册</text>')
        s.append(f'<text x="{W - M - 7}" y="{TOP - 7}" font-size="2" fill="{MUTED}" text-anchor="middle">课数</text>')
    else:
        s.append(f'<text x="{W - M}" y="{TOP - 3}" font-size="2" fill="{MUTED}" text-anchor="end">课数</text>')
    s.append("</svg>")
    return "".join(s)


CSS = f"""
@page {{ size: A3 landscape; margin: {M}mm; }}
body {{ margin: 0; font-family: "Noto Sans CJK SC", sans-serif; color: #1f1f1f; }}
section {{ break-after: page; }}
section:last-child {{ break-after: auto; }}
h1 {{ font: 700 15pt "Noto Serif CJK SC", serif; margin: 0 0 1mm; }}
.key {{ font-size: 8pt; color: {MUTED}; margin: 0 0 2mm; }}
.dot {{ display: inline-block; width: 2.4mm; height: 2.4mm; border-radius: 50%; background: {ACCENT}; vertical-align: -.2mm; }}
.dot.o {{ background: #fff; border: .3mm solid {ACCENT}; width: 1.8mm; height: 1.8mm; }}
"""


def main():
    tax = json.loads((ROOT / "docs" / "语法点分类.json").read_text(encoding="utf-8"))
    tags = json.loads((ROOT / "docs" / "语法点标注.json").read_text(encoding="utf-8"))
    parts = [f"<html><head><meta charset='utf-8'><title>语法点分布图</title><style>{CSS}</style></head><body>"]
    key = "<span class='dot'></span> 新授课讲解　<span class='dot o'></span> 复习课总结　"
    parts.append(f"<section><h1>第一至三册 语法点分布汇总</h1><p class='key'>{key}横轴为三册全部课，色带为分册；右侧为各册讲到该语法点的课数</p>"
                 f"{page((1, 2, 3), tax, tags)}</section>")
    for n in (1, 2, 3):
        parts.append(f"<section><h1>{book.BOOK_NAME[n]} 语法点分布</h1>"
                     f"<p class='key'>{key}横轴为课号，色带为单元；右侧为讲到该语法点的课数</p>"
                     f"{page((n,), tax, tags)}</section>")
    parts.append("</body></html>")
    out = ROOT / "build" / "语法点分布图.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")
    pdf = ROOT / "dist" / "语法点分布图.pdf"
    subprocess.run([sys.executable, "-m", "weasyprint", str(out), str(pdf)], check=True, cwd=ROOT)
    print(pdf)


if __name__ == "__main__":
    main()
