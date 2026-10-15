#!/usr/bin/env python3
"""第一册练习册：按课号顺序排 workbook/*.yaml，全书连续编号，书末附答案。

    python3 tools/workbook.py              →  dist/第一册练习册.pdf
    python3 tools/workbook.py L11 L20      →  只排第 11–20 课（样稿）

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


def lesson_no(code):
    return int(re.match(r"L(\d+)", code).group(1))


def files(lo=1, hi=100):
    out = []
    for p in WB.glob("L*.yaml"):
        m = re.fullmatch(r"L(\d+)(-综合)?", p.stem)
        if m and lo <= int(m.group(1)) <= hi:
            out.append((int(m.group(1)), 1 if m.group(2) else 0, p))
    return [p for *_, p in sorted(out)]


def ru(s):
    """已带 {.ru} 标记的原样保留，否则整段当俄语。"""
    s = str(s)
    return s if "{.ru}" in s else exercises.ru(s)


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


def label(g, combined):
    return ("综合：" if combined else "") + span(g.get("lessons") or [])


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


def exercise_md(n, g, combined, answers=False):
    t = g["type"]
    head = f"[练习 {n}]{{.wb-no}}[{label(g, combined)}]{{.wb-lesson}}"
    out = ["::: {.exercise .wb}", head, "", f"[{g['task']}]{{.task}}", ""]
    if t == "matrix":
        given = set(g.get("given") or [])

        def show(i, j, r):
            if j in given or answers:
                return md_inline(ru(r["cells"][j]) + (note(r) if j == 0 else ""))
            return "<span class='wb-blank'></span>"
        out += [cell_table(g["cols"], g["rows"], show), ""]
    elif t == "classify":
        if answers:
            for b in g["bins"]:
                ws = [ru(it["text"]) for it in g["items"] if it["answer"] == b]
                out.append(f"- {ru(b)}：" + "，".join(ws))
            out.append("")
        else:
            words = "".join(f"<span class='wb-item'>{k}. {md_inline(ru(it['text']) + note(it))}</span>"
                            for k, it in enumerate(g["items"], 1))
            out += [f"<div class='wb-items'>{words}</div>", ""]
            out += ["<table class='wb-bins'><tr>" + "".join(f"<th>{md_inline(ru(b))}</th>" for b in g["bins"]) + "</tr><tr>"
                    + "<td></td>" * len(g["bins"]) + "</tr></table>", ""]
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
.wb { break-inside: auto; margin-top: 10pt; }
.wb-no { font: 700 11pt "PT Sans", "CJK Sans"; color: var(--accent); margin-right: 8pt; }
.wb-lesson { font: 9pt "PT Sans", "CJK Sans"; color: var(--muted); }
.wb-hint { font: 8pt "PT Sans", "CJK Sans"; color: var(--muted); margin-left: 4pt; }
table.wb-matrix { width: 100%; border-collapse: collapse; margin: 4pt 0 6pt; font-size: 10pt; }
table.wb-matrix th { font: 700 8.5pt "PT Sans", "CJK Sans"; color: var(--muted); text-align: left; border-bottom: .8pt solid var(--accent); padding: 2pt 4pt; }
table.wb-matrix td { border-bottom: .4pt solid var(--rule); padding: 5pt 4pt; vertical-align: bottom; }
table.wb-matrix td.n { width: 5mm; color: var(--muted); font-size: 8pt; }
table.wb-matrix tr { break-inside: avoid; }
.wb-blank { display: inline-block; width: 100%; min-width: 22mm; }
.wb-items { line-height: 2; margin: 4pt 0; break-after: avoid; }
.wb-item { display: inline-block; margin-right: 12pt; white-space: nowrap; }
table.wb-bins { width: 100%; border-collapse: collapse; margin: 4pt 0 6pt; break-inside: avoid; }
table.wb-bins th { border: .6pt solid var(--rule); padding: 3pt; background: #f6f1ea; }
table.wb-bins td { border: .6pt solid var(--rule); height: 32mm; }
"""


def main(argv):
    lo, hi = (int(argv[0][1:]), int(argv[1][1:])) if len(argv) >= 2 else (1, 100)
    body, keys, n = [], [], 0
    for p in files(lo, hi):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        combined = p.stem.endswith("-综合")
        for g in d.get("groups") or []:
            n += 1
            g.setdefault("lessons", d.get("lessons") or [re.match(r"L\d+", p.stem).group(0)])
            body.append(exercise_md(n, g, combined))
            keys.append(exercise_md(n, g, combined, answers=True))
    title = "第一册练习册" + (f"（第 {lo}–{hi} 课样稿）" if argv else "")
    html_doc = (f'<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8"><title>{title}</title>'
                f'<link rel="stylesheet" href="../style.css"><style>{CSS}</style></head><body class="book">'
                f'<section class="lesson"><div class="running">俄语教程 · {title}</div><h1 class="part-title">{title}</h1>'
                f'{book.pandoc(chr(10).join(body), "wb")}</section>'
                f'<section class="answers"><div class="running">{title} · 答案与解析</div><h1 class="part-title">答案与解析</h1>'
                f'{book.pandoc(chr(10).join(keys), "wbk")}</section></body></html>')
    out = ROOT / "build" / f"{title}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    pdf = ROOT / "dist" / f"{title}.pdf"
    subprocess.run([sys.executable, "-m", "weasyprint", str(out), str(pdf)], check=True, cwd=ROOT)
    print(pdf, n, "个练习")


if __name__ == "__main__":
    main(sys.argv[1:])
