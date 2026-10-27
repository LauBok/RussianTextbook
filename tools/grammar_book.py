#!/usr/bin/env python3
"""《俄语语法》：grammar/*.md → dist/俄语语法.pdf

    python3 tools/grammar_book.py                         →  dist/俄语语法.pdf
    python3 tools/grammar_book.py --out dist/俄语语法-样章.pdf

源文件按文件名排序（编号-章号-章名.md），front matter 写 part（编号）、part_title（编名）、chapter（章号，全书连续）、title（章名）。
标记约定见 docs/语法书编写规范.md：
- 编号分层：章在编内编号（front matter 的 chapter），节写成 编.章.节。节标题 `## §2.2.1 标题`，构建时加 id s2-2-1；
  正文里的 §2.2.1 自动链接到该节；大纲里有、还没写的节先不加链接，大纲里没有的节报错。
- 俄语词索引 `[кни́га]{.ru .ix}`，另立词头写 `{.ru .ix key="кни́га"}`；术语索引 `[第二格]{.term}`。
- 变格变位表 `::: paradigm`，例句 `::: ex`，常见错误 `::: err`，教程课号 `::: course`。
先排一遍取得各锚点所在页码，再把页码写进目录和索引排第二遍（正文页码不变）。
"""
import argparse
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402

ROOT = book.ROOT
SRC = ROOT / "grammar"
PAGE = "letter"   # 与练习册一致，按 Letter 纸打印
CN = "零一二三四五六七八九十"
OUTLINE_FILE = ROOT / "docs" / "语法书大纲.md"
OUTLINE = {n for n in re.findall(r"^\|\s*§(\d+\.\d+\.\d+)", OUTLINE_FILE.read_text(encoding="utf-8"), re.M)} if OUTLINE_FILE.exists() else set()


def cn_num(n):
    if n <= 10:
        return CN[n]
    if n < 20:
        return "十" + (CN[n - 10] if n > 10 else "")
    return CN[n // 10] + "十" + (CN[n % 10] if n % 10 else "")


SEC_HEAD = re.compile(r"^## §(\d+\.\d+\.\d+)\s+(.+?)\s*$", re.M)
SPAN = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\{([^{}]*)\}")
SEC_REF = re.compile(r"(?<![\[#])§(\d+\.\d+\.\d+)")


def sid(k):
    """节号 2.2.1 → 锚点 s2-2-1"""
    return "s" + k.replace(".", "-")


def plain(s):
    return re.sub(r"\[([^\[\]]*)\]\{[^}]*\}", r"\1", s)


def chapters(src=SRC):
    out = []
    for p in sorted(Path(src).glob("*.md")):
        md = p.read_text(encoding="utf-8")
        fm = book.front_matter(md)
        body = md.split("\n---\n", 1)[1] if md.startswith("---") else md
        out.append((p, fm, body))
    return out


class Builder:
    def __init__(self):
        self.ix = defaultdict(list)     # 俄语词索引：词头 → 锚点
        self.terms = defaultdict(list)  # 术语索引
        self.secs = {}                  # 节号 → (标题, 章号)
        self.n = 0
        self.pending = set()

    def anchor(self, kind):
        self.n += 1
        return f"{kind}{self.n}"

    def collect_sections(self, chs):
        for p, fm, body in chs:
            for m in SEC_HEAD.finditer(body):
                k = m.group(1)
                if k in self.secs:
                    sys.exit(f"{p.name}：§{k} 重复")
                self.secs[k] = (m.group(2), fm.get("chapter"))

    def prep(self, p, body):
        def head(m):
            return f"## [§{m.group(1)}]{{.sec-no}} {m.group(2)} {{#{sid(m.group(1))}}}"
        body = SEC_HEAD.sub(head, body)

        def span(m):
            text, attrs = m.group(1), m.group(2)
            cls = re.findall(r"\.([\w-]+)", attrs)
            if "ix" in cls:
                key = re.search(r'key="([^"]+)"', attrs)
                a = self.anchor("ix")
                self.ix[key.group(1) if key else plain(text)].append(a)
                return f"[{text}]{{#{a} {attrs}}}"
            if "term" in cls:
                a = self.anchor("tm")
                self.terms[plain(text)].append(a)
                return f"[{text}]{{#{a} {attrs}}}"
            return m.group(0)
        body = SPAN.sub(span, body)

        def ref(m):
            k = m.group(1)
            if k not in self.secs:
                if k in OUTLINE:          # 大纲里有、还没写的节：先不加链接
                    self.pending.add(k)
                    return f"[§{k}]{{.xref-pending}}"
                missing.append(f"{p.name}：§{k}")
            return f"[§{k}](#{sid(k)}){{.xref}}"
        missing = []
        lines = []
        for ln in body.split("\n"):
            lines.append(ln if ln.startswith("## ") else SEC_REF.sub(ref, ln))
        self.missing = getattr(self, "missing", []) + missing
        return "\n".join(lines)


def pandoc(md):
    """同 book.pandoc，但不加 id 前缀：节和索引锚点全书统一引用。"""
    import subprocess
    out = subprocess.run(["pandoc", "-f", "markdown", "-t", "html5", "--lua-filter", str(ROOT / "zh-punct.lua")],
                         input=md, capture_output=True, text=True, check=True, cwd=ROOT).stdout
    # 被例句块隔开后接着编号的列表（2. 3. ……）：WeasyPrint 不认 start 属性，改用计数器
    return re.sub(r'<ol start="(\d+)"', lambda m: f'<ol style="counter-reset: list-item {int(m.group(1)) - 1}"', out)


def inline(s):
    s = html.escape(str(s), quote=False)
    return re.sub(r"\[([^\[\]]*)\]\{\.ru\}", r"<span class='ru'>\1</span>", s)


def index_html(title, entries, pages, cls):
    rows = []
    for key in sorted(entries, key=book.sort_key):
        nums = []
        for a in entries[key]:
            n = pages.get(a)
            if n is not None and (not nums or nums[-1][0] != n):
                nums.append((n, a))
        links = ", ".join(f"<a href='#{a}'>{n}</a>" for n, a in nums) or "<span>000</span>"
        word = f"<span class='ru'>{html.escape(key)}</span>" if cls == "ix" else html.escape(key)
        rows.append(f"<p class='ix-row'><span class='ix-key'>{word}</span> <span class='ix-pg'>{links}</span></p>")
    return (f"<section class='g-index' id='{cls}-index'><div class='running'>{title}</div>"
            f"<h1 class='g-index-title'>{title}</h1><div class='ix-cols'>{''.join(rows)}</div></section>")


def toc_html(chs, pages):
    out, part = ["<section class='g-toc'><h1 class='g-toc-title'>目　录</h1>"], None
    for p, fm, body in chs:
        if fm.get("part") != part:
            part = fm.get("part")
            out.append(f"<div class='toc-part'>第{cn_num(part)}编　{html.escape(fm.get('part_title', ''))}</div>")
        cid = f"ch{fm['part']}-{fm['chapter']}"
        out.append(f"<a class='toc-chap' href='#{cid}'><span>第 {fm['chapter']} 章　{html.escape(fm['title'])}</span>"
                   f"<span class='pg'>{pages.get(cid, '000')}</span></a>")
        for m in SEC_HEAD.finditer(body):
            sid_ = sid(m.group(1))
            out.append(f"<a class='toc-sec' href='#{sid_}'><span>§{m.group(1)}　{html.escape(plain(m.group(2)))}</span>"
                       f"<span class='pg'>{pages.get(sid_, '000')}</span></a>")
    for t, a in (("俄语词索引", "ix-index"), ("术语索引", "tm-index")):
        out.append(f"<a class='toc-chap' href='#{a}'><span>{t}</span><span class='pg'>{pages.get(a, '000')}</span></a>")
    out.append("</section>")
    return "".join(out)


CSS = f"""
@page {{ size: {PAGE}; }}
.g-cover {{ height: 220mm; display: flex; flex-direction: column; justify-content: center; text-align: center; break-after: page; }}
.g-toc, .g-index {{ break-before: page; }}
.g-toc-title, .g-index-title {{ font: 700 20pt "PT Sans", "CJK Sans"; color: var(--accent); margin: 0 0 12pt; bookmark-level: 1; }}
.toc-part {{ font: 700 11pt "PT Sans", "CJK Sans"; margin: 10pt 0 3pt; color: var(--accent); }}
.toc-chap, .toc-sec {{ display: flex; color: inherit; text-decoration: none; line-height: 1.55; }}
.toc-chap {{ font: 700 10pt "PT Sans", "CJK Sans"; margin-top: 3pt; }}
.toc-sec {{ font-size: 9.5pt; padding-left: 8mm; }}
.toc-chap span:first-child, .toc-sec span:first-child {{ flex: 1; }}
.toc-chap .pg, .toc-sec .pg {{ color: var(--muted); }}
.g-part {{ break-before: page; page-break-after: always; padding-top: 70mm; text-align: center;
  font: 700 26pt "PT Sans", "CJK Sans"; color: var(--accent); bookmark-level: 1; }}
.g-chapter {{ break-before: page; }}
.g-chap-title {{ font: 700 20pt "PT Sans", "CJK Sans"; border-bottom: 2px solid var(--accent); padding-bottom: 6pt; margin: 0 0 12pt; bookmark-level: 2; }}
.g-chap-title .chap-no {{ color: var(--accent); }}
.g-chapter h2 {{ font: 700 13pt "PT Sans", "CJK Sans"; margin: 16pt 0 6pt; bookmark-level: 3; break-after: avoid; }}
.g-chapter h3 {{ font: 700 11pt "PT Sans", "CJK Sans"; margin: 10pt 0 4pt; bookmark-level: none; break-after: avoid; }}
.g-chapter h4 {{ font: 700 10.5pt "CJK Sans"; margin: 8pt 0 3pt; bookmark-level: none; break-after: avoid; }}
.sec-no {{ color: var(--accent); margin-right: 6pt; }}
a.xref {{ color: var(--accent); text-decoration: none; }}
.xref-pending {{ color: var(--accent); }}
.paradigm table {{ width: auto; min-width: 60%; border: .6pt solid var(--rule); margin: 4pt 0 10pt; }}
.paradigm th, .paradigm td {{ border: .5pt solid var(--rule); padding: 2.5pt 8pt; }}
.paradigm th {{ background: var(--tint); border-bottom: 1pt solid var(--ink); }}
.paradigm td:first-child {{ font: 9pt "PT Sans", "CJK Sans"; color: var(--muted); }}
.paradigm .ru {{ font-size: 11pt; }}
.err {{ margin: 3pt 0 8pt 12pt; padding: 3pt 8pt; border-left: 2pt solid #c9a2a2; }}
.err p {{ margin: 0 0 2pt; }}
.course {{ margin: 6pt 0 10pt; font: 9pt "PT Sans", "CJK Sans"; color: var(--muted); border-top: .5pt solid var(--rule); padding-top: 3pt; }}
.term {{ font-weight: 700; }}
.ix-cols {{ columns: 2; column-gap: 8mm; font-size: 9pt; line-height: 1.35; }}
.ix-row {{ margin: 0; break-inside: avoid; }}
.ix-pg {{ color: var(--muted); margin-left: 4pt; }}
.g-chapter > .running, .g-index > .running {{ font-size: 0; line-height: 0; height: 0; margin: 0; overflow: hidden; }}
.ix-pg a {{ color: inherit; text-decoration: none; }}
"""


def render(head, parts):
    from weasyprint import HTML
    doc = HTML(string=head + "".join(parts) + "</body></html>", base_url=str(ROOT / "build") + "/").render()
    pages = {}
    for i, pg in enumerate(doc.pages, 1):
        for a in pg.anchors:
            pages.setdefault(a, i)
    return doc, pages


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "俄语语法.pdf"))
    ap.add_argument("--src", default=str(SRC), help="章节目录（默认 grammar/）")
    a = ap.parse_args(argv)
    chs = chapters(a.src)
    if not chs:
        sys.exit("grammar/ 下没有章节文件")
    b = Builder()
    b.collect_sections(chs)
    body, part = [], None
    for p, fm, md in chs:
        if fm.get("part") != part:
            part = fm.get("part")
            body.append(f"<h1 class='g-part' id='part{part}'>第{cn_num(part)}编　{html.escape(fm.get('part_title', ''))}</h1>")
        title = inline(fm["title"])
        body.append(f"<section class='g-chapter'><div class='running'>第{cn_num(fm['part'])}编　第 {fm['chapter']} 章　{html.escape(plain(fm['title']))}</div>"
                    f"<h1 class='g-chap-title' id='ch{fm['part']}-{fm['chapter']}'><span class='chap-no'>第 {fm['chapter']} 章　</span>{title}</h1>"
                    f"{pandoc(b.prep(p, md))}</section>")
    if b.missing:
        sys.exit("§ 引用指向大纲里不存在的节：" + "、".join(b.missing))
    if b.pending:
        print(f"提示：{len(b.pending)} 个 § 引用指向尚未编写的节，暂不加链接：" + "、".join(f"§{k}" for k in sorted(b.pending, key=lambda x: tuple(map(int, x.split("."))))))
    title = "俄语语法"
    head = (f'<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8"><title>{title}</title>'
            f'<link rel="stylesheet" href="../style.css"><style>{CSS}</style></head><body class="book grammar">')
    cover = (f"<section class='g-cover'><div class='cover-ru'>Грамма́тика ру́сского языка́</div>"
             f"<div class='cover-title'>{title}</div><div class='cover-sub'>《俄语教程》配套语法</div></section>")
    pages = {}
    for _ in range(2):
        parts = [cover, toc_html(chs, pages), *body,
                 index_html("俄语词索引", b.ix, pages, "ix"), index_html("术语索引", b.terms, pages, "tm")]
        doc, pages = render(head, parts)
    out = Path(a.out)
    out.parent.mkdir(exist_ok=True)
    (ROOT / "build" / (out.stem + ".html")).write_text(head + "".join(parts) + "</body></html>", encoding="utf-8")
    doc.write_pdf(out)
    print(out, f"{len(doc.pages)} 页，{len(chs)} 章，{len(b.secs)} 节，俄语词索引 {len(b.ix)} 条，术语索引 {len(b.terms)} 条")


if __name__ == "__main__":
    main(sys.argv[1:])
