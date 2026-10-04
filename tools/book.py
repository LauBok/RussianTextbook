#!/usr/bin/env python3
"""生成整册书：python3 tools/book.py 1 → build/第一册.html、build/第一册.pdf、web/index.html

封面、目录（带页码）、语音课与各课（按课号顺序）、书末练习答案、总词汇表。
加 --html 只生成 HTML 和网页目录，不排 PDF（排版整册要几分钟）。
"""
import re
import subprocess
import sys
import unicodedata
from html import escape
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import exercises  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BOOK_NAME = {1: "第一册", 2: "第二册", 3: "第三册", 4: "第四册"}
RU_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


def lesson_codes(book):
    """按课号顺序列出本册已有的课。"""
    def key(code):
        m = re.search(r"([PL])(\d+)$", code)
        return (m.group(1) == "L", int(m.group(2)))
    pat = r"[PL]\d+" if book == 1 else rf"B{book}-L\d+"
    codes = [p.stem for p in (ROOT / "lessons").glob("*.md") if re.fullmatch(pat, p.stem)]
    return sorted(codes, key=key)


def front_matter(md):
    return yaml.safe_load(md.split("\n---\n", 1)[0].lstrip("-\n")) or {}


def pandoc(md, prefix):
    return subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "html5", "--lua-filter", str(ROOT / "zh-punct.lua"),
         f"--id-prefix={prefix}-"],
        input=md, capture_output=True, text=True, check=True, cwd=ROOT).stdout


def lesson_label(fm):
    return fm.get("label") or f"第 {fm['lesson']} 课"


def lesson_html(code):
    md = exercises.expand((ROOT / "lessons" / f"{code}.md").read_text(encoding="utf-8"), code)
    fm = front_matter(md)
    ex_path = ROOT / "exercises" / f"{code}.yaml"
    if ex_path.exists():
        data = yaml.safe_load(ex_path.read_text(encoding="utf-8"))
        md = md.replace("<!-- EXERCISES -->", exercises.pdf_exercises(data, f"img/{code}"))
    body = pandoc(md.split("\n---\n", 1)[1] if md.startswith("---") else md, code)
    head = (f'<header class="lesson-head"><div class="running">{escape(fm["book"])} · {escape(fm["unit"])}</div>'
            f'<div class="lesson-no">{escape(lesson_label(fm))}</div>'
            f'<h1 lang="ru">{escape(str(fm["title"]))}</h1><div class="subtitle">{escape(fm["subtitle"])}</div></header>')
    return fm, f'<section class="lesson" id="{code}">{head}{body}</section>'


def answers_html(code, fm):
    ex_path = ROOT / "exercises" / f"{code}.yaml"
    if not ex_path.exists():
        return ""
    data = yaml.safe_load(ex_path.read_text(encoding="utf-8"))
    body = pandoc(exercises.key_markdown(data), f"{code}-key")
    title = f'{escape(lesson_label(fm))}　<span lang="ru">{escape(str(fm["title"]))}</span>'
    return f'<section class="key-lesson" id="{code}-key"><h2 class="key-title">{title}</h2>{body}</section>'


def sort_key(word):
    w = unicodedata.normalize("NFC", word).replace("́", "").lower()
    return [RU_ALPHABET.index(c) if c in RU_ALPHABET else 99 for c in w if c.isalpha()]


def vocab_index(codes, fms):
    rows = []
    for code in codes:
        if code.startswith("P"):
            continue
        for word, pos, gloss in exercises.lesson_vocab(code):
            plain = re.sub(r"\[\[.+?\]\]\{\.tr\}", "", word)
            plain = re.sub(r"\[([^\[\]]*)\]\{[^}]*\}", r"\1", plain)
            rows.append((sort_key(plain), word, pos, gloss, fms[code]["lesson"]))
    rows.sort(key=lambda r: r[0])
    md = ["::: {.vocab .book-index}", "| 词 | 词性 | 释义 | 课 |", "|---|---|---|---|"]
    md += [f"| {w} | {p} | {g} | {n} |" for _, w, p, g, n in rows]
    md.append(":::")
    return pandoc("\n".join(md), "index"), len(rows)


def toc_html(codes, fms):
    out, unit = ['<nav class="toc"><h2 class="toc-title">目录</h2>'], None
    for code in codes:
        fm = fms[code]
        if fm["unit"] != unit:
            unit = fm["unit"]
            out.append(f'<div class="toc-unit">{escape(unit)}</div>')
        out.append(f'<a class="toc-item" href="#{code}"><span class="toc-no">{escape(lesson_label(fm))}</span>'
                   f'<span class="toc-name"><span lang="ru">{escape(str(fm["title"]))}</span>　{escape(fm["subtitle"])}</span></a>')
    out.append('<div class="toc-unit">附录</div>')
    out.append('<a class="toc-item" href="#answers"><span class="toc-no"></span><span class="toc-name">练习答案与解析</span></a>')
    out.append('<a class="toc-item" href="#index"><span class="toc-no"></span><span class="toc-name">总词汇表</span></a>')
    out.append("</nav>")
    return "\n".join(out)


def web_index(book, codes, fms):
    items, unit = [], None
    for code in codes:
        fm = fms[code]
        if fm["unit"] != unit:
            if unit is not None:
                items.append("</ul>")
            unit = fm["unit"]
            items.append(f"<h2>{escape(unit)}</h2><ul>")
        items.append(f'<li><a href="{code}.html"><span class="no">{escape(lesson_label(fm))}</span>'
                     f'<span lang="ru">{escape(str(fm["title"]))}</span> <span class="sub">{escape(fm["subtitle"])}</span></a></li>')
    items.append("</ul>")
    name = f"俄语教程 {BOOK_NAME[book]}"
    page = f"""<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>
:root {{ --paper: #fbf8f3; --ink: #1f1f1f; --muted: #6b6b6b; --accent: #8a2b2b; --rule: #e3dbd0; }}
@media (prefers-color-scheme: dark) {{ :root {{ --paper: #18181a; --ink: #e9e6e1; --muted: #a29d96; --accent: #e09088; --rule: #3a3633; }} }}
body {{ margin: 0; background: var(--paper); color: var(--ink); font: 16px/1.6 "PT Serif", "Noto Serif SC", serif; }}
main {{ max-width: 720px; margin: 0 auto; padding: 32px 16px 64px; }}
h1 {{ font-size: 30px; margin: 0 0 4px; }} .lead {{ color: var(--muted); margin: 0 0 24px; }}
h2 {{ font: 700 15px "PT Sans", "Noto Sans SC", sans-serif; color: var(--accent); margin: 28px 0 8px; }}
ul {{ list-style: none; margin: 0; padding: 0; }}
li a {{ display: flex; gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--rule); color: inherit; text-decoration: none; }}
li a:hover {{ color: var(--accent); }}
.no {{ flex: 0 0 76px; color: var(--muted); font-size: 14px; }} .sub {{ color: var(--muted); }}
</style></head>
<body><main><h1>{name}</h1><p class="lead">从零起步到 A2 · {len(codes)} 课</p>
{"".join(items)}
</main></body></html>"""
    (ROOT / "web" / "index.html").write_text(page, encoding="utf-8")


def main(argv):
    book = int(argv[0]) if argv and argv[0].isdigit() else 1
    html_only = "--html" in argv
    codes = lesson_codes(book)
    fms, parts, keys = {}, [], []
    for code in codes:
        fm, html = lesson_html(code)
        fms[code] = fm
        parts.append(html)
        keys.append(answers_html(code, fm))
        print(code, file=sys.stderr)
    index, n_words = vocab_index(codes, fms)
    name = f"俄语教程 {BOOK_NAME[book]}"
    cover = (f'<section class="book-cover"><div class="cover-ru" lang="ru">Ру́сский язы́к</div>'
             f'<h1 class="cover-title">{name}</h1><div class="cover-sub">从零起步 · 自学用</div></section>')
    answers = (f'<section class="answers" id="answers"><div class="running">{name} · 练习答案与解析</div>'
               f'<h1 class="part-title">练习答案与解析</h1>{"".join(keys)}</section>')
    index_sec = (f'<section class="index" id="index"><div class="running">{name} · 总词汇表</div>'
                 f'<h1 class="part-title">总词汇表</h1><p>共 {n_words} 词，按俄语字母顺序排列；右栏是生词所在的课。</p>{index}</section>')
    page = f"""<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8"><title>{name}</title>
<link rel="stylesheet" href="../style.css"></head>
<body class="book">{cover}{toc_html(codes, fms)}{"".join(parts)}{answers}{index_sec}</body></html>"""
    out = ROOT / "build"
    out.mkdir(exist_ok=True)
    html_path = out / f"{BOOK_NAME[book]}.html"
    html_path.write_text(page, encoding="utf-8")
    web_index(book, codes, fms)
    print(html_path)
    print(ROOT / "web" / "index.html")
    if not html_only:
        pdf = out / f"{BOOK_NAME[book]}.pdf"
        subprocess.run([sys.executable, "-m", "weasyprint", str(html_path), str(pdf)], check=True, cwd=ROOT)
        print(pdf)


if __name__ == "__main__":
    main(sys.argv[1:])
