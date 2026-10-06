#!/usr/bin/env python3
"""课程总表：四册每课的课题和语法项目，一张横向 A4 的 PDF。

    python3 tools/syllabus.py  →  dist/课程总表.pdf

课题取各课 front matter 的 title、subtitle；语法取 docs/第N册大纲.md 各单元表格的“语法”列
（语音课取“内容”，第四册取“文体与修辞”），大纲里没有的课取本课“## 语法”下的小标题。
"""
import html
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402

ROOT = book.ROOT
COLS = ("语法", "内容", "文体与修辞", "文体与写作")
CN = "一二三四"


def outline(n):
    """大纲表格：{'L1': '……', 'P1': '……'}。"""
    rows, col = {}, None
    for ln in (ROOT / "docs" / f"第{CN[n - 1]}册大纲.md").read_text(encoding="utf-8").splitlines():
        if not ln.startswith("|"):
            col = None
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if cells[0] == "课":
            col = next((cells.index(c) for c in COLS if c in cells), None)
        elif col is not None and re.fullmatch(r"[PL]\d+", cells[0]) and col < len(cells):
            rows[cells[0]] = cells[col]
    return rows


def lesson_grammar(md):
    m = re.search(r"^## 语法\n(.*?)(?=^## )", md, re.S | re.M)
    if not m:
        return ""
    heads = re.findall(r"^### (.+)$", m.group(1), re.M)
    return "；".join(re.sub(r"^[一二三四五六七八九十]+、", "", h) for h in heads)


def plain(s):
    """去掉 Markdown 标记，留文字。"""
    s = re.sub(r"\[(.+?)\]\{[^}]*\}", r"\1", s)
    return s.replace("**", "").replace("`", "")


def ru(s):
    """连续的西里尔文字包进 .ru，汉字和俄语各用各的字体。"""
    s = html.escape(s)
    return re.sub(r"[А-Яа-яЁё́][А-Яа-яЁё́\s,.;:!?«»()\-–—/*]*[А-Яа-яЁё́.!?»)]?",
                  lambda m: f'<span class="ru">{m.group(0)}</span>', s)


def rows(n):
    ol, out, unit = outline(n), [], None
    for code in book.lesson_codes(n):
        md = (ROOT / "lessons" / f"{code}.md").read_text(encoding="utf-8")
        fm = book.front_matter(md)
        is_test = bool(re.search(r"T[012]$", code))
        u = fm.get("unit", "")
        if not is_test and u != unit:
            out.append(("unit", u))
            unit = u
        key = re.sub(r"^B\d-", "", code)
        key = key[0] + str(int(key[1:])) if key[0] in "PL" else key
        title, sub = plain(str(fm.get("title", ""))), plain(str(fm.get("subtitle", "")))
        if is_test:
            label, gram = fm.get("label", ""), f"考查{sub}" if sub else ""
            title = ""
        else:
            label = f"语音 {key[1:]}" if key[0] == "P" else f"第 {int(key[1:])} 课"
            if title.startswith("Повтор"):
                gram = sub
            else:
                gram = plain(ol.get(key, "") or lesson_grammar(md))
        out.append(("row", label, title, sub if not is_test else "", gram))
    return out


CSS = """
@page { size: A4 landscape; margin: 14mm 14mm 16mm;
  @bottom-center { content: counter(page); font: 9pt "PT Sans"; color: #777; } }
body { font: 9.5pt/1.45 "Noto Serif CJK SC", serif; color: #1f1f1f; }
.ru { font-family: "PT Serif", serif; }
h1 { font: 700 22pt "Noto Serif CJK SC"; text-align: center; margin: 40mm 0 4mm; letter-spacing: .1em; }
.lead { text-align: center; color: #666; margin-bottom: 8mm; }
.cover-list { width: 60%; margin: 0 auto; font-size: 11pt; }
.cover-list td { padding: 3pt 8pt; border-bottom: .5pt solid #ddd; }
h2 { font: 700 15pt "Noto Sans CJK SC"; color: #8a2b2b; margin: 0 0 4mm; break-before: page; }
table.syl { width: 100%; border-collapse: collapse; }
table.syl thead { display: table-header-group; }
table.syl th { font: 700 9pt "Noto Sans CJK SC"; text-align: left; color: #555; border-bottom: 1pt solid #8a2b2b; padding: 3pt 5pt; }
table.syl td { padding: 2.5pt 5pt; border-bottom: .4pt solid #e3dbd0; vertical-align: top; }
table.syl tr { break-inside: avoid; }
td.no { width: 9%; white-space: nowrap; color: #555; }
td.ti { width: 40%; }
td.ti .zh { color: #555; }
tr.unit td { font: 700 10pt "Noto Sans CJK SC"; background: #f4ede4; color: #8a2b2b; padding-top: 4pt; }
tr.test td { background: #faf6f0; }
"""


def build():
    parts = [f"<html><head><meta charset='utf-8'><title>课程总表</title><style>{CSS}</style></head><body>",
             "<h1>俄语教程 课程总表</h1><p class='lead'>四册各课课题与语法项目</p><table class='cover-list'>"]
    books = {n: rows(n) for n in range(1, 5)}
    for n, rs in books.items():
        k = sum(1 for r in rs if r[0] == "row")
        parts.append(f"<tr><td>{book.BOOK_NAME[n]}</td><td>{book.COVER_SUB[n] if hasattr(book, 'COVER_SUB') else ''}</td><td>{k} 课（含测试）</td></tr>")
    parts.append("</table>")
    for n, rs in books.items():
        head = "文体与修辞" if n == 4 else "语法项目"
        parts.append(f"<h2>{book.BOOK_NAME[n]}</h2><table class='syl'><thead><tr><th>课</th><th>课题</th><th>{head}</th></tr></thead><tbody>")
        for r in rs:
            if r[0] == "unit":
                parts.append(f"<tr class='unit'><td colspan='3'>{ru(r[1])}</td></tr>")
                continue
            _, label, title, sub, gram = r
            cls = " class='test'" if not title else ""
            ti = (ru(title) + (f"　<span class='zh'>{ru(sub)}</span>" if sub else "")) if title else ""
            parts.append(f"<tr{cls}><td class='no'>{html.escape(label)}</td><td class='ti'>{ti}</td><td>{ru(gram)}</td></tr>")
        parts.append("</tbody></table>")
    parts.append("</body></html>")
    out = ROOT / "build" / "课程总表.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")
    pdf = ROOT / "dist" / "课程总表.pdf"
    subprocess.run([sys.executable, "-m", "weasyprint", str(out), str(pdf)], check=True, cwd=ROOT)
    for n, rs in books.items():
        empty = [r[1] for r in rs if r[0] == "row" and not r[4]]
        print(book.BOOK_NAME[n], sum(1 for r in rs if r[0] == "row"), "行", "缺语法：" + "、".join(empty) if empty else "")
    print(pdf)


if __name__ == "__main__":
    build()
