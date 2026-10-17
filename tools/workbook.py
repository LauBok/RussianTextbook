#!/usr/bin/env python3
"""练习册：按课号顺序排 workbook/*.yaml，全书连续编号，书末附答案。

    python3 tools/workbook.py                     →  dist/第一册练习册.pdf（workbook/L*.yaml）
    python3 tools/workbook.py L11 L20             →  只排第 11–20 课（样稿，放 build/）
    python3 tools/workbook.py --book 2 [L1 L18]   →  dist/第二册练习册.pdf（workbook/B2-L*.yaml）

<课号>-综合.yaml 紧排在该课之后。练习编号构建时按顺序生成；标题写“第 11 课”或“综合：第 11–19 课”。
"""
import html
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402
import exercises  # noqa: E402

ROOT = book.ROOT
WB = ROOT / "workbook"
PREFIX = ""   # 第二册起文件名带 B2- 等前缀
# 练习册按美国 Letter 纸打印（216 × 279 mm），左右页边距 20 mm
TEXT_W = 216 - 40      # 版心宽（mm）
PAGE_H = 792           # 页高（pt）


def lesson_no(code):
    return int(re.search(r"L(\d+)", code).group(1))


def files(lo=1, hi=100):
    out = []
    for p in WB.glob(f"{PREFIX}L*.yaml"):
        m = re.fullmatch(re.escape(PREFIX) + r"L(\d+)(-综合)?", p.stem)
        if m and lo <= int(m.group(1)) <= hi:
            out.append((int(m.group(1)), 1 if m.group(2) else 0, p))
    return [p for *_, p in sorted(out)]


def ru(s):
    """已带 {.ru} 标记的原样保留，否则整段当俄语。"""
    s = str(s)
    if "{.ru}" in s:
        return s
    if re.search(r"[\u4e00-\u9fff]", s):   # 夹中文的提示只给俄语部分加标记
        return re.sub(r"[А-Яа-яЁё\u0301][А-Яа-яЁё\u0301 ,/.-]*[А-Яа-яЁё\u0301]|[А-Яа-яЁё]", lambda m: exercises.ru(m.group(0)), s)
    return exercises.ru(s)


def span(lessons):
    """[L11, L12, L13, L17] → 第 11–13、17 课"""
    ns = sorted({lesson_no(c) for c in lessons})
    parts, i = [], 0
    while i < len(ns):
        j = i
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        parts.append(f"{ns[i]}–{ns[j]}" if j > i else f"{ns[i]}")
        i = j + 1
    return "第 " + "、".join(parts) + " 课"


def note(r):
    bits = []
    if r.get("hint"):
        bits.append(str(r["hint"]))
    if r.get("gloss"):
        bits.append(str(r["gloss"]))
    return f" [{'；'.join(bits)}]{{.wb-hint}}" if bits else ""


def cell_table(cols, rows, show):
    """show(i, j, row) → 单元格 Markdown；用 HTML 表格，避免 Markdown 表格对长文字折行出错。"""
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = []
    for i, r in enumerate(rows, 1):
        tds = "".join(f"<td>{show(i, j, r)}</td>" for j in range(len(cols)))
        body.append(f"<tr><td class='n'>{i}</td>{tds}</tr>")
    return f"<table class='wb-matrix'><thead><tr><th></th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def md_inline(s):
    """单元格里的 [文字]{.类名} 转成 <span>（每格调 pandoc 太慢）。"""
    s = html.escape(str(s), quote=False)
    for _ in range(3):   # 允许一层嵌套
        s = re.sub(r"\[([^\[\]]*)\]\{\.([\w-]+)(?: \.([\w-]+))?\}",
                   lambda m: f'<span class="{m.group(2)} {m.group(3) or ""}">{m.group(1)}</span>', s)
    return s


def plain(s):
    return re.sub(r"\[([^\[\]]*)\]\{[^}]*\}", r"\1", str(s)).replace("\u0301", "")


def common_hint(rows):
    """所有行提示相同时提到题目要求里，只写一次。"""
    hs = {str(r.get("hint", "")) for r in rows}
    return hs.pop() if len(hs) == 1 and "" not in hs else None


def merge_why(why):
    """相同的解析合并：第 1 题：X / 第 2 题：X → 第 1–2 题：X。"""
    items = re.findall(r"第\s*(\d+)\s*[题行][：:]\s*(.+)", why)
    if not items:
        return why
    groups = []
    for n, text in items:
        key = re.sub(r"\[[^\]]*\]\{\.ru\}", "…", text).strip()
        if groups and groups[-1][2] == key:
            groups[-1][1] = n
        else:
            groups.append([n, n, key, text])
    out = []
    for a, b, key, text in groups:
        if a == b:
            out.append(f"第 {a} 题：{text.strip()}")
        else:
            out.append(f"第 {a}–{b} 题：{key.replace('…', '……')}" if "…" in key else f"第 {a}–{b} 题：{text.strip()}")
    return "\n".join(out)


PREP = re.compile(r"^(во|в|на|обо|об|о)\s+(.+)$")


def split_prep(cell):
    """[в шко́ле]{.ru} → ('в', 'шко́ле')；没有前置词 → ('', 原文)。"""
    t = plain_ru(cell)
    m = PREP.match(t)
    return (m.group(1), m.group(2)) if m else ("", t)


def paren(r, given):
    """括号里写原形；新词加释义和性；hint 里除性和前置词以外的提示保留。"""
    base = re.sub(r"^(во|в|на|обо|об|о)\s*\+\s*", "", plain_ru(r["cells"][min(given)]))   # 前置词已印在题面
    bits, extra = [], []
    toks = [x.strip() for x in str(r.get("hint", "")).split("；") if x.strip()]
    gender = next((x for x in toks if x in ("m", "f", "n")), "")
    for x in toks:
        if x in ("m", "f", "n") or x.startswith("前置词"):
            continue
        extra.append(md_inline(x))
    if r.get("new"):
        if r.get("gloss"):
            bits.append(html.escape(str(r["gloss"])))
        if gender:
            bits.append(gender)
    inner = f"<span class='ru'>{base}</span>" + (" " + "，".join(bits) if bits else "") + ("；" + "；".join(extra) if extra else "")
    return f"<span class='wb-paren'>（{inner}）</span>"


def matrix_md(g, answers):
    cols, rows = g["cols"], g["rows"]
    given = set(g.get("given") or [0])
    todo = [j for j in range(len(cols)) if j not in given]
    shared = common_hint(rows)

    def word(r):
        bits = [] if shared else ([str(r["hint"])] if r.get("hint") else [])
        if r.get("gloss"):
            bits.append(str(r["gloss"]))
        tail = f"<span class='wb-hint'>{md_inline('；'.join(bits))}</span>" if bits else ""
        return md_inline(ru(r["cells"][min(given)])) + tail

    one = len(todo) == 1
    preps = [split_prep(r["cells"][todo[0]]) for r in rows] if one else []
    # 原形本身带前置词（改错、改写题）时不把前置词印在题面，免得泄露答案；“в + наш + дом”这类组合照常拆
    if one and any(PREP.match(plain_ru(r["cells"][min(given)])) for r in rows):
        preps = [("", plain_ru(r["cells"][todo[0]])) for r in rows]
    if answers:   # 紧凑答案：只写要填的部分
        if one:
            items = "".join(f"<span class='wb-ans'>{i}. <span class='ru'>{rest}</span></span>"
                            for i, (_, rest) in enumerate(preps, 1))
            return f"<div class='wb-anslist'>{items}</div>"
        items = "".join(f"<li>{md_inline(', '.join(plain_ru(r['cells'][j]) for j in todo))}</li>" for r in rows)
        return f"<ol class='wb-anscols'>{items}</ol>"
    if one:   # 一对一：“前置词 ＿＿（原形 释义，性）”，三栏或两栏
        # 手写比印刷宽：答题线按每字母约 3 mm 留，最短 24 mm；再按整格宽度选三栏、两栏或一栏
        gaps = [min(70, max(24, len(plain(rest)) * 3.0)) for _, rest in preps]
        widths = [(6 if prep else 0) + gap + len(re.sub(r'<[^>]+>', '', paren(r, given)).replace('\u0301', '')) * 1.9 + 6
                  for (prep, _), gap, r in zip(preps, gaps, rows)]
        ncol = 3 if max(widths) <= 56 else 2 if max(widths) <= 85 else 1
        gap = max(gaps)   # 同一题答题线一样长
        cells = []
        for i, (r, (prep, rest)) in enumerate(zip(rows, preps), 1):
            cells.append(f"<span class='n'>{i}.</span> " + (f"<span class='ru'>{prep}</span> " if prep else "")
                         + f"<span class='gap' style='width:{gap:.0f}mm'></span>{paren(r, given)}")
        trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in cells[k:k + ncol])
                      + "<td></td>" * (ncol - len(cells[k:k + ncol])) + "</tr>" for k in range(0, len(cells), ncol))
        return f"<table class='wb-grid c{ncol}'>{trs}</table>"
    # 版心 TEXT_W mm：序号 6 mm；原形列按最长原形定宽，释义另起一行；答题列按最长答案的手写长度（每字母约 1.9 mm，一行约 12 个词）定宽，
    # 一行放不下就把形式分成几张表（每张都重复原形列），各列等宽
    letters = lambda t: len(re.findall(r"[^\W\d_]", plain(t)))
    natural = max(20, max(letters(r["cells"][min(given)]) for r in rows) * 2.1 + 5)
    need = max(18, max(letters(r["cells"][j]) for r in rows for j in todo) * 1.9 + 3)
    # 原形是长句时，答题列按手写长度留够以后，剩下的宽度都给句子列（至少 42 mm，最多占版心六成）
    word_w = natural if natural <= 42 else min(natural, max(42, min(0.6 * (TEXT_W - 6), TEXT_W - 6 - need * len(todo))))
    avail = TEXT_W - 6 - word_w
    per = max(1, int(avail // need))
    nt = -(-len(todo) // per)
    chunks = [todo[k * len(todo) // nt:(k + 1) * len(todo) // nt] for k in range(nt)]
    # 答题列有富余时让给原形列，释义尽量一行写完（8pt：汉字约 2.9 mm，其他约 1.6 mm）
    def hint_w(r):
        t = plain(re.sub(r"<[^>]+>", "", word(r).split("wb-hint'>", 1)[-1])) if "wb-hint" in word(r) else ""
        return sum(2.9 if ord(c) > 0x2e80 else 1.6 for c in t) + 3
    want = min(60, max([word_w] + [hint_w(r) for r in rows]))
    word_w = max(word_w, min(want, TEXT_W - 6 - need * max(len(ch) for ch in chunks)))
    avail = TEXT_W - 6 - word_w
    tables = []
    for ch in chunks:
        pct = lambda mm: f"{mm / TEXT_W * 100:.2f}%"
        colgroup = (f"<colgroup><col style='width:{pct(6)}'/><col style='width:{pct(word_w)}'/>"
                    + f"<col style='width:{pct(avail / len(ch))}'/>" * len(ch) + "</colgroup>")
        head = "".join(f"<th>{html.escape(cols[j])}</th>" for j in [min(given)] + ch)
        body = "".join(f"<tr><td class='n'>{i}</td><td class='w'>{word(r)}</td>" + "<td class='a'></td>" * len(ch) + "</tr>"
                       for i, r in enumerate(rows, 1))
        tables.append(f"<table class='wb-matrix'>{colgroup}<thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>")
    return "".join(tables)


def plain_ru(s):
    """答案列表里多个形式合成一个 .ru span。"""
    return re.sub(r"^\[(.*)\]\{\.ru\}$", r"\1", str(s))


def exercise_md(k, g, answers=False):
    """一道大题：k 为本节内的大题序号（一、二、三……）。"""
    t = g["type"]
    task = g["task"]
    if t == "matrix" and not answers and len(g["cols"]) - len(g.get("given") or [0]) > 1:
        sh = common_hint(g["rows"])
        if sh:
            task = task.rstrip("。") + f"（{sh}）。"
    out = ["::: {.exercise .wb}", f"[{exercises.zh_num(k)}、{task}]{{.task}}", ""]
    if t == "matrix":
        html_block = matrix_md(g, answers)
        if answers and "wb-anscols" in html_block:
            html_block = html_block.replace("<li>", "<li><span class='ru'>", ).replace("</li>", "</span></li>")
        out += [html_block, ""]
    elif t == "classify":
        if answers:
            for b in g["bins"]:
                ws = [ru(it["text"]) for it in g["items"] if it["answer"] == b]
                out.append(f"- {ru(b)}：" + "，".join(ws))
            out.append("")
        else:
            words = "".join(f"<span class='wb-item'>{k}. {md_inline(ru(it['text']) + note(it))}</span>"
                            for k, it in enumerate(g["items"], 1))
            per = max(1, -(-len(g["items"]) // len(g["bins"])))
            out += [f"<div class='wb-items'>{words}</div>", ""]
            out += ["<table class='wb-bins'><tr>" + "".join(f"<th>{md_inline(ru(b))}</th>" for b in g["bins"]) + "</tr><tr>"
                    + f"<td style='height:{6 + per * 6}mm'></td>" * len(g["bins"]) + "</tr></table>", ""]
    elif t == "fill" and not answers:   # 句中填空：空线按手写长度留，短句排两栏
        items = g["items"]
        gap = min(45, max(26, max(len(plain(it.get("accept", [""])[0])) for it in items) * 3.0))
        cells = []
        for i, it in enumerate(items, 1):
            stem = md_inline(ru(str(it["stem"]))).replace("___", f"<span class='gap' style='width:{gap:.0f}mm'></span>")
            bits = ([md_inline(ru(it["hint"]))] if it.get("hint") else []) + ([html.escape(str(it["gloss"]))] if it.get("new") and it.get("gloss") else [])
            hint = f"<span class='wb-paren'>（{' '.join(bits)}）</span>" if bits else ""
            cells.append(f"<span class='n'>{i}.</span> {stem}{hint}")
        longest = max(len(plain(it["stem"])) + len(plain(it.get("hint", ""))) for it in items) * 2.0 + gap
        ncol = 2 if longest <= 84 else 1
        trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in cells[k:k + ncol])
                      + "<td></td>" * (ncol - len(cells[k:k + ncol])) + "</tr>" for k in range(0, len(cells), ncol))
        out += [f"<table class='wb-grid c{ncol}'>{trs}</table>", ""]
    elif t in ("fill", "choice"):
        for i, it in enumerate(g["items"], 1):
            stem = exercises.blank(str(it["stem"]))
            if answers:
                a = it.get("accept", [it.get("answer")])[0]
                out.append(f"{i}. {ru(a)}")
            elif t == "fill":
                out.append(f"{i}. {ru(stem)}" + (f"（{ru(it['hint'])}）" if it.get("hint") else ""))
            else:
                out.append(f"{i}. {ru(stem)}　（{ru(' / '.join(it['options']))}）")
        out.append("")
    if answers and g.get("why"):
        why = re.sub(r"第\s*(\d+(?:[–、,，]\d+)*)\s*行", r"第 \1 题", str(g["why"]))   # 矩阵按行解析，统一写“题”
        out += exercises.why_lines(why)
    out += [":::", ""]
    return "\n".join(out)


CSS = """
.wb { break-inside: auto; margin-top: 6pt; }
@page { size: letter; }
section.wb-page { break-before: page; }
section.wb-page > .running { font-size: 0; line-height: 0; height: 0; margin: 0; overflow: hidden; }
h1.wb-title .wb-lesson { font: 400 10pt "PT Sans", "CJK Sans"; color: var(--muted); margin-left: 10pt; }
section.t1 table.wb-grid td { padding-top: 5pt; } section.t1 table.wb-matrix td { height: 7.5mm; }
section.t2 table.wb-grid td { padding-top: 2pt; } section.t2 table.wb-matrix td { height: 6.5mm; } section.t2 .wb { margin-top: 2pt; }
h2.wb-sec { font: 700 14pt "PT Sans", "CJK Sans"; color: var(--ink); margin: 18pt 0 2pt; border-bottom: .8pt solid var(--accent); padding-bottom: 2pt; break-after: avoid; }
h2.wb-sec .wb-no { font-size: 14pt; }
h2.wb-sec .wb-lesson { font-weight: 400; margin-left: 8pt; }
.wb-no { font: 700 11pt "PT Sans", "CJK Sans"; color: var(--accent); margin-right: 8pt; }
.wb-lesson { font: 9pt "PT Sans", "CJK Sans"; color: var(--muted); }
.wb-hint { font: 8pt "PT Sans", "CJK Sans"; color: var(--muted); margin-left: 4pt; }
table.wb-matrix { width: 100%; border-collapse: collapse; margin: 4pt 0 6pt; font-size: 10pt; table-layout: fixed; }
table.wb-matrix td.a, table.wb-matrix thead th:nth-child(n+3) { border-left: .5pt solid var(--rule); }
table.wb-matrix td.a:nth-child(even), table.wb-matrix thead th:nth-child(n+3):nth-child(even) { background: #f7f3ee; }
table.wb-matrix td { height: 9mm; }
table.wb-matrix th { font: 700 8.5pt "PT Sans", "CJK Sans"; color: var(--muted); text-align: left; border-bottom: .8pt solid var(--accent); padding: 2pt 4pt; }
table.wb-matrix td { border-bottom: .4pt solid var(--rule); padding: 3pt 4pt; vertical-align: bottom; }
table.wb-grid { width: 100%; border-collapse: collapse; margin: 2pt 0 6pt; font-size: 10pt; table-layout: fixed; }
table.wb-grid tr { break-inside: avoid; }
table.wb-grid td { padding: 9pt 4pt 2pt 0; vertical-align: bottom; }
table.wb-grid .n { color: var(--muted); font-size: 8pt; }
table.wb-grid .gap { display: inline-block; border-bottom: .5pt solid var(--ink); height: 1em; vertical-align: baseline; }
.wb-paren { font-size: 9pt; color: #444; }
.wb-anslist { line-height: 1.7; margin: 2pt 0 4pt; }
.wb-ans { display: inline-block; margin-right: 10pt; white-space: nowrap; }
ol.wb-anscols { columns: 2; column-gap: 8mm; margin: 2pt 0 4pt; padding-left: 16pt; }
table.wb-matrix td.n { color: var(--muted); font-size: 8pt; }
table.wb-matrix td.w .wb-hint { display: block; margin-left: 0; line-height: 1.2; }
table.wb-matrix tr { break-inside: avoid; }
.wb-blank { display: inline-block; width: 100%; min-width: 22mm; }
.wb-items { line-height: 2; margin: 4pt 0; break-after: avoid; }
.wb-item { display: inline-block; margin-right: 12pt; white-space: nowrap; }
table.wb-bins { width: 100%; border-collapse: collapse; margin: 4pt 0 6pt; break-inside: avoid; }
table.wb-bins th { border: .6pt solid var(--rule); padding: 3pt; background: #f6f1ea; }
table.wb-bins td { border: .6pt solid var(--rule); }
"""


def main(argv):
    global PREFIX
    bk = 1
    if argv[:1] == ["--book"]:
        bk, argv = int(argv[1]), argv[2:]
    PREFIX = "" if bk == 1 else f"B{bk}-"
    lo, hi = (int(argv[0][1:]), int(argv[1][1:])) if len(argv) >= 2 else (1, 100)
    body, keys, n, names = [], [], 0, []
    for p in files(lo, hi):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        groups = d.get("groups") or []
        if not groups:
            continue
        combined = p.stem.endswith("-综合")
        code = re.match(re.escape(PREFIX) + r"L\d+", p.stem).group(0)
        lessons = d.get("lessons") or [code]
        # 一节一个知识点：练习 N + 标题；大题一、二、三；小题 1、2、3
        n += 1
        topic = re.sub(r"^(第\s*\d+\s*课|综合练习)\s*", "", str(d.get("heading", ""))).strip()
        if combined:
            topic = "综合：" + topic
        name = f"练习 {n}　{topic}"
        sec = [f"<div class='running'>{html.escape(name)}</div>"
               f"<h1 class='part-title wb-title'>{html.escape(name)}<span class='wb-lesson'>{span(lessons)}</span></h1>"]
        keys.append(f"<h2 class='wb-sec'><span class='wb-no'>练习 {n}</span>{html.escape(topic)}"
                    f"<span class='wb-lesson'>{span(lessons)}</span></h2>")
        md = []
        for k, g in enumerate(groups, 1):
            g.setdefault("lessons", lessons)
            md.append(exercise_md(k, g))
            keys.append(exercise_md(k, g, answers=True))
        body.append((sec[0], book.pandoc(chr(10).join(md), f'wb{n}')))
        names.append((name, groups))
    title = book.BOOK_NAME[bk] + "练习册" + (f"（第 {lo}–{hi} 课样稿）" if argv else "")
    out = ROOT / "build" / f"{title}.html"
    out.parent.mkdir(exist_ok=True)
    pdf = ROOT / ("build" if argv else "dist") / f"{title}.pdf"   # 分段样稿放 build/，整本才进 dist/
    tight = {}   # 节号 → 收紧级别：只溢出几行的节逐级压缩行距重排
    for _ in range(3):
        secs = "".join(f"<section class='wb-page t{tight.get(k, 0)}'>{h}{b}</section>" for k, (h, b) in enumerate(body))
        out.write_text(f'<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8"><title>{title}</title>'
                       f'<link rel="stylesheet" href="../style.css"><style>{CSS}</style></head><body class="book">{secs}'
                       f'<section class="answers"><div class="running">答案与解析</div><h1 class="part-title">答案与解析</h1>'
                       f'{book.pandoc(chr(10).join(keys), "wbk")}</section></body></html>', encoding="utf-8")
        subprocess.run([sys.executable, "-m", "weasyprint", str(out), str(pdf)], check=True, cwd=ROOT)
        spill = [k for k, empty in fill_report(pdf, names, quiet=True) if empty > 0.8 and tight.get(k, 0) < 2]
        if not spill:
            break
        for k in spill:
            tight[k] = tight.get(k, 0) + 1
    print(pdf, n, "节练习")
    fill_report(pdf, names)


def fill_report(pdf, names, quiet=False):
    """每节最后一页空了多少：空白超过四分之一页时提示补几道小题（按最后一道大题的行高估算）。"""
    import pymupdf
    d = pymupdf.open(pdf)
    starts = []
    for i, page in enumerate(d):
        first = page.get_text().strip().split("\n")[0] if page.get_text().strip() else ""
        for k, (name, _) in enumerate(names):
            if first.replace(" ", "").startswith(name.replace("　", "").replace(" ", "")) and k not in [s[1] for s in starts]:
                starts.append((i, k))
    ans = next((i for i, pg in enumerate(d) if pg.get_text().lstrip().startswith("答案与解析")), len(d))
    starts.append((ans, None))
    usable = PAGE_H - 60 - 55
    res = []
    for (a, k), (b, _) in zip(starts, starts[1:]):
        last = d[b - 1]
        bottom = max([bl[3] for bl in last.get_text("blocks") if 60 < bl[1] < PAGE_H - 52], default=60)
        empty = (PAGE_H - 55) - bottom
        res.append((k, empty / usable))
        if empty > usable / 4 and not quiet:
            print(f"  {names[k][0]}：{b - a} 页，最后一页空 {empty / usable:.0%}")
    return res


if __name__ == "__main__":
    main(sys.argv[1:])
