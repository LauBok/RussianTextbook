#!/usr/bin/env python3
"""生成整册书：python3 tools/book.py 1 → build/第一册.html、build/第一册.pdf、web/index.html

封面、目录（带页码）、语音课与各课（按课号顺序）、书末练习答案、总词汇表。
加 --html 只生成 HTML 和网页目录，不排 PDF；加 --single 用单进程整本排版（慢，作对照）。
默认按课分块、多进程并行排版，再用 PyMuPDF 拼合，补页码、书签和目录链接。
"""
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from html import escape
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import exercises
import check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BOOK_NAME = {1: "第一册", 2: "第二册", 3: "第三册", 4: "第四册"}
LEVEL = {1: "从零起步到 A2", 2: "从 A2 到 B1", 3: "从 B1 到 B2", 4: "从 B2 到 C1"}
COVER_SUB = {1: "从零起步 · 自学用", 2: "A2 → B1 · 自学用", 3: "B1 → B2 · 自学用", 4: "B2 → C1 · 自学用"}
RU_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


def index_name(book):
    """网页目录：第一册 web/index.html，其余 web/B2-index.html 等。"""
    return "index.html" if book == 1 else f"B{book}-index.html"


def lesson_codes(book):
    """按课号顺序列出本册已有的课和测试页（顺序规则见 check.order_key）。"""
    pat = r"[PL]\d+|T[012]" if book == 1 else rf"B{book}-(?:L\d+|T[012])"
    codes = [p.stem for p in (ROOT / "lessons").glob("*.md") if re.fullmatch(pat, p.stem)]
    return sorted(codes, key=lambda c: check.order_key(book, c))


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


def toc_html(codes, fms, pages=None):
    """目录。pages 给出各节起始页码时直接写出页码（并行排版用），否则用 target-counter。"""
    out, unit = ['<nav class="toc"><h2 class="toc-title">目录</h2>'], None
    for code in codes:
        fm = fms[code]
        if fm["unit"] != unit:
            unit = fm["unit"]
            out.append(f'<div class="toc-unit">{escape(unit)}</div>')
        out.append(f'<a class="toc-item"{_toc_target(code, pages)}><span class="toc-no">{escape(lesson_label(fm))}</span>'
                   f'<span class="toc-name"><span lang="ru">{escape(str(fm["title"]))}</span>　{escape(fm["subtitle"])}</span></a>')
    out.append('<div class="toc-unit">附录</div>')
    out.append(f'<a class="toc-item"{_toc_target("answers", pages)}><span class="toc-no"></span><span class="toc-name">练习答案与解析</span></a>')
    out.append(f'<a class="toc-item"{_toc_target("index", pages)}><span class="toc-no"></span><span class="toc-name">总词汇表</span></a>')
    out.append("</nav>")
    return "\n".join(out)


def _toc_target(anchor, pages):
    if pages is None:
        return f' href="#{anchor}"'
    # 分块排版时目标不在同一文档里：先写成外链，拼合后改成页内跳转
    return f' href="{TOC_LINK}{anchor}" data-page="{pages.get(anchor, "000")}"'


TOC_LINK = "https://toc.invalid/#"
PAGE_NO_BASELINE = 814.0        # 单进程排版时页码基线的位置（A4，下边距 22mm）
CHUNK_CSS = """<style>
@page { @bottom-center { content: none; } }
@page :first { @top-left { content: string(running); } }
.toc-item::after { content: leader(".") attr(data-page); }
</style>"""
FRONT_CSS = """<style>
@page { @bottom-center { content: none; } }
.toc-item::after { content: leader(".") attr(data-page); }
</style>"""


def _render_chunk(job):
    """子进程：排一个分块，写出 PDF，返回页数和锚点所在页。"""
    html, base, out, ids = job
    import logging
    import weasyprint
    logging.getLogger("weasyprint").setLevel(logging.ERROR)
    doc = weasyprint.HTML(string=html, base_url=base).render()
    where = {}
    for i, page in enumerate(doc.pages):
        for a in page.anchors:
            if a in ids and a not in where:
                where[a] = i
    doc.write_pdf(out)
    return len(doc.pages), where


def parallel_pdf(head, blocks, front, pdf, html_path, workers):
    """blocks: [(锚点列表, html)]，每块都从新页开始；front(pages) 生成封面加目录。"""
    import pymupdf
    from concurrent.futures import ProcessPoolExecutor
    tmp = pdf.parent / "chunks"
    tmp.mkdir(exist_ok=True)
    base = str(html_path)
    wrap = lambda body, css: f"{head}{css}</head><body class=\"book\">{body}</body></html>"
    jobs = [(wrap(front({}), FRONT_CSS), base, str(tmp / "front0.pdf"), set())]
    jobs += [(wrap(body, CHUNK_CSS), base, str(tmp / f"c{i:02d}.pdf"), set(ids)) for i, (ids, body) in enumerate(blocks)]
    order = sorted(range(len(jobs)), key=lambda k: -len(jobs[k][0]))      # 大块先排
    with ProcessPoolExecutor(workers) as ex:
        futs = {k: ex.submit(_render_chunk, jobs[k]) for k in order}
        res = {k: f.result() for k, f in futs.items()}
    n_front = res[0][0]
    pages, offset, starts = {}, n_front, []
    for k in range(1, len(jobs)):
        n, where = res[k]
        starts.append(offset)
        for a, i in where.items():
            pages[a] = offset + i + 1
        offset += n
    # 目录写入真实页码后重排封面和目录（只有几页）；页数必须不变
    n2, _ = _render_chunk((wrap(front(pages), FRONT_CSS), base, str(tmp / "front.pdf"), set()))
    if n2 != n_front:
        raise RuntimeError(f"目录页数变了：{n_front} → {n2}")
    book = pymupdf.open()
    toc = []
    for k, path in enumerate([tmp / "front.pdf"] + [tmp / f"c{i:02d}.pdf" for i in range(len(blocks))]):
        part = pymupdf.open(path)
        start = len(book)
        toc += [[lvl, title, p + start] for lvl, title, p in part.get_toc(simple=True)]
        book.insert_pdf(part)
        part.close()
    # 页码：与 style.css 的 @bottom-center 一致（PT Sans 9pt，#8c8c8c）
    font = pymupdf.Font(fontfile="/usr/share/fonts/truetype/paratype/PTS55F.ttf")
    for i, page in enumerate(book):
        page.wrap_contents()        # WeasyPrint 的内容流不恢复坐标变换，先包起来再追加文字
        text = str(i + 1)
        w = font.text_length(text, 9)
        tw = pymupdf.TextWriter(page.rect, color=(0x8c / 255,) * 3)
        tw.append(((page.rect.width - w) / 2, PAGE_NO_BASELINE), text, font=font, fontsize=9)
        tw.write_text(page)
    # 目录外链改成页内跳转
    for page in book.pages(0, n_front):
        for link in page.get_links():
            uri = link.get("uri") or ""
            if uri.startswith(TOC_LINK) and uri[len(TOC_LINK):] in pages:
                page.delete_link(link)
                page.insert_link({"kind": pymupdf.LINK_GOTO, "from": link["from"], "page": pages[uri[len(TOC_LINK):]] - 1})
    book.set_toc(toc)
    book.save(pdf, garbage=3, deflate=True)
    return len(book)


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
<body><main><h1>{name}</h1><p class="lead">{LEVEL.get(book, "")} · {sum(1 for c in codes if not re.search(r"T[012]$", c))} 课</p>
{"".join(items)}
</main></body></html>"""
    (ROOT / "web" / index_name(book)).write_text(page, encoding="utf-8")


def main(argv):
    book = int(argv[0]) if argv and argv[0].isdigit() else 1
    html_only = "--html" in argv
    codes = lesson_codes(book)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        done = list(ex.map(lesson_html, codes))
        fms = {code: fm for code, (fm, _) in zip(codes, done)}
        parts = [html for _, html in done]
        keys = list(ex.map(lambda c: answers_html(c, fms[c]), codes))
    index, n_words = vocab_index(codes, fms)
    name = f"俄语教程 {BOOK_NAME[book]}"
    cover = (f'<section class="book-cover"><div class="cover-ru" lang="ru">Ру́сский язы́к</div>'
             f'<h1 class="cover-title">{name}</h1><div class="cover-sub">{COVER_SUB.get(book, "自学用")}</div></section>')
    answers = (f'<section class="answers" id="answers"><div class="running">{name} · 练习答案与解析</div>'
               f'<h1 class="part-title">练习答案与解析</h1>{"".join(keys)}</section>')
    index_sec = (f'<section class="index" id="index"><div class="running">{name} · 总词汇表</div>'
                 f'<h1 class="part-title">总词汇表</h1><p>共 {n_words} 词，按俄语字母顺序排列；右栏是生词所在的课。</p>{index}</section>')
    head = f"""<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8"><title>{name}</title>
<link rel="stylesheet" href="../style.css">"""
    page = f"""{head}</head>
<body class="book">{cover}{toc_html(codes, fms)}{"".join(parts)}{answers}{index_sec}</body></html>"""
    out = ROOT / "build"
    out.mkdir(exist_ok=True)
    html_path = out / f"{BOOK_NAME[book]}.html"
    html_path.write_text(page, encoding="utf-8")
    web_index(book, codes, fms)
    print(html_path)
    print(ROOT / "web" / index_name(book))
    if not html_only:
        pdf = out / f"{BOOK_NAME[book]}.pdf"
        if "--single" in argv:
            subprocess.run([sys.executable, "-m", "weasyprint", str(html_path), str(pdf)], check=True, cwd=ROOT)
        else:
            workers = os.cpu_count() or 4
            # 各课按 HTML 长度大致均分成若干块（每块从新页开始），答案、词汇表各成一块
            n_blocks = workers * 2
            total = sum(len(p) for p in parts)
            blocks, cur, ids, size = [], [], [], 0
            for code, html in zip(codes, parts):
                cur.append(html)
                ids.append(code)
                size += len(html)
                if size >= total / n_blocks:
                    blocks.append((ids, "".join(cur)))
                    cur, ids, size = [], [], 0
            if cur:
                blocks.append((ids, "".join(cur)))
            blocks += [(["answers"], answers), (["index"], index_sec)]
            n = parallel_pdf(head, blocks, lambda pg: cover + toc_html(codes, fms, pg), pdf, html_path, workers)
            print(f"{pdf}（{n} 页）")
        dist = ROOT / "dist"
        dist.mkdir(exist_ok=True)
        shutil.copyfile(pdf, dist / pdf.name)
        print(dist / pdf.name)


if __name__ == "__main__":
    main(sys.argv[1:])
