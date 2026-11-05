#!/usr/bin/env python3
"""试卷册：exams/K01.yaml … K10.yaml 排成一本，每套从新页开始，书末附答案与解析。

    python3 tools/exam.py               →  dist/第一册试卷.pdf
    python3 tools/exam.py K03           →  只排第 3 套（样稿，放 build/）
    python3 tools/exam.py --check       →  查重复题干（与教材练习、练习册、其他各卷）和正确答案的选项分布
    python3 tools/exam.py --balance K03 →  重排选择题选项，使正确答案均匀落在 A B C D（改写 YAML 里的 options 行）

每套考从第 1 课到 range 末课学过的全部内容；格式见 exercises/FORMAT.md，卷级字段 heading、range、total、minutes。
"""
import html
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402
import exercises  # noqa: E402

ROOT = book.ROOT
EXAMS = ROOT / "exams"

CSS = """
@page { size: letter; }
section.exam { break-before: page; }
section.exam > .running, section.answers > .running { font-size: 0; line-height: 0; height: 0; margin: 0; overflow: hidden; }
h1.exam-title { margin-bottom: 2pt; }
.exam-meta { font: 10pt "PT Sans", "CJK Sans"; color: var(--muted); margin: 0 0 8pt; }
.exam-name { font: 10pt "PT Sans", "CJK Sans"; margin: 6pt 0 4pt; }
.exam-name span { display: inline-block; border-bottom: .6pt solid var(--ink); width: 38mm; margin: 0 14pt 0 4pt; }
table.score { border-collapse: collapse; width: 100%; margin: 4pt 0 12pt; font: 9.5pt "PT Sans", "CJK Sans"; table-layout: fixed; }
table.score th, table.score td { border: .6pt solid var(--rule); text-align: center; padding: 3pt 2pt; }
table.score th { background: #f6f1ea; font-weight: 700; }
table.score td { height: 9mm; }
table.score .sub { display: block; font-weight: 400; color: var(--muted); font-size: 8pt; }
h2.key-paper { font: 700 14pt "PT Sans", "CJK Sans"; margin: 18pt 0 4pt; border-bottom: .8pt solid var(--accent); padding-bottom: 2pt; break-after: avoid; }
section.answers h2:not(.key-paper) { font-size: 11pt; }
section.howto { break-before: page; }
.glossary { font-size: 9pt; color: var(--muted); margin: -2pt 0 6pt 8pt; }
.glossary p { margin: 0; }
"""

HOWTO = """
## 得分怎么看

每套满分 150 分。做完先用答案速查表对选择题和语法填空，再对照解析看错题；汉译俄、补全对话和写作按评分要点自己给分。

| 得分 | 说明 | 下一步 |
|---|---|---|
| 120 分以上 | 学过的内容掌握得好 | 继续学下一单元 |
| 90–119 分 | 基本掌握，有薄弱处 | 解析里每道题都注明了课号，回到错题对应的课复习，过几天重做错题 |
| 90 分以下 | 有较多内容没有掌握 | 重学本单元，并复习错题较集中的前面各课，再重做这套卷 |

每套卷都考从第 1 课起学过的全部内容，前面各课的题错得多，说明这些内容学过后忘了，比本单元的错题更需要回头复习。
"""


def papers(only=None):
    out = []
    for p in sorted(EXAMS.glob("K*.yaml"), key=lambda p: int(p.stem[1:])):
        if only and p.stem not in only:
            continue
        out.append((p.stem, yaml.safe_load(p.read_text(encoding="utf-8"))))
    return out


def lesson_span(rng):
    a, b = (int(x[1:]) for x in rng.split("-"))
    return f"第 {a}–{b} 课"


def sum_points(data):
    tot = []
    for ex in data["exercises"]:
        p = ex.get("points") or 0
        tot.append(p * len(ex["items"]))
    return tot


def short_task(task):
    """得分栏表头只写大题名：取“：”前或分值括号前的部分。"""
    t = re.sub(r"（[^（）]*分）$", "", task)
    return re.split(r"[：。]", t)[0]


def paper_html(code, data):
    md = exercises.pdf_exercises(data, f"img/{code}")
    md = md.split("\n", 2)[2] if md.startswith("## ") else md         # 卷名由卷头写
    md = re.sub(r"(?<!\n)\n(\[[^\]]+\]\{\.sp\})", r"\n\n\1", md)         # 对话每个说话人另起一段
    md = exercises.speaker_widths(md)                                # 对话的说话人栏按最长的名字定宽
    pts = sum_points(data)
    if data.get("total") and abs(sum(pts) - data["total"]) > 1e-6:
        print(f"  {code}：各题分值合计 {sum(pts):g}，与 total {data['total']} 不符")
    cols = []          # 得分栏：同一道大题的几篇阅读合成一栏
    for lab, ex, p in zip(exercises.labels(data), data["exercises"], pts):
        if lab:
            cols.append([lab.rstrip("、"), exercises.SUB.sub(r"\1", short_task(ex["task"])), p])
        else:
            cols[-1][2] += p
    heads = "".join(f"<th>{n}<span class='sub'>{html.escape(t)}</span></th>" for n, t, _ in cols)
    full = "".join(f"<td style='height:auto;color:var(--muted)'>{p:g}</td>" for *_, p in cols)
    blanks = "<td></td>" * len(cols)
    meta = f"考试范围：{lesson_span(data['range'])}　　满分：{data['total']} 分　　时间：{data['minutes']} 分钟"
    head = (f"<div class='running'>{html.escape(data['heading'])}</div>"
            f"<h1 class='part-title exam-title'>{html.escape(data['heading'])}</h1>"
            f"<p class='exam-meta'>{meta}</p>"
            f"<p class='exam-name'>姓名<span></span>日期<span></span>用时<span style='width:24mm'></span></p>"
            f"<table class='score'><tr><th>大题</th>{heads}<th>总分</th></tr>"
            f"<tr><th>满分</th>{full}<td style='height:auto'>{data['total']}</td></tr>"
            f"<tr><th>得分</th>{blanks}<td></td></tr></table>")
    return f"<section class='exam'>{head}{book.pandoc(md, code)}</section>"


def key_html(code, data):
    md = f"<h2 class='key-paper'>{html.escape(data['heading'])}</h2>\n\n" + exercises.key_markdown(data)
    md = re.sub(r"^## ", "### ", md, flags=re.M)
    md = re.sub(r"(?<!\n)\n(\[[^\]]+\]\{\.sp\})", r"\n\n\1", md)
    return book.pandoc(exercises.speaker_widths(md), code + "k")


def build(only=None):
    ps = papers(only)
    if not ps:
        sys.exit("exams/ 下没有试卷")
    title = book.BOOK_NAME[1] + "试卷" + (f"（{'、'.join(only)} 样稿）" if only else "")
    body = "".join(paper_html(c, d) for c, d in ps)
    keys = "".join(key_html(c, d) for c, d in ps)
    out = ROOT / "build" / f"{title}.html"
    out.parent.mkdir(exist_ok=True)
    pdf = ROOT / ("build" if only else "dist") / f"{title}.pdf"
    out.write_text(f'<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8"><title>{title}</title>'
                   f'<link rel="stylesheet" href="../style.css"><style>{CSS}</style></head><body class="book">{body}'
                   f'<section class="answers"><div class="running">答案与解析</div><h1 class="part-title">答案与解析</h1>{keys}</section>'
                   f'<section class="howto"><div class="running">得分怎么看</div>{book.pandoc(HOWTO, "howto")}</section>'
                   f'</body></html>', encoding="utf-8")
    subprocess.run([sys.executable, "-m", "weasyprint", str(out), str(pdf)], check=True, cwd=ROOT)
    print(pdf, len(ps), "套")


# ---------- 查重和选项分布 ----------

def norm(s):
    s = re.sub(r"\[([^\[\]]*)\]\{[^}]*\}", r"\1", str(s))
    s = s.replace("́", "").replace("ё", "е").lower()
    return re.sub(r"[^а-яa-z一-鿿_]+", " ", s).strip()


def stems(data):
    for ex in data.get("exercises") or data.get("groups") or []:
        for it in ex.get("items") or []:
            if isinstance(it, dict):
                for k in ("stem", "zh", "cue"):
                    if it.get(k) and len(norm(it[k])) > 12:
                        yield norm(it[k])


def check():
    seen = {}
    for p in list((ROOT / "exercises").glob("*.yaml")) + list((ROOT / "workbook").glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for s in stems(d):
            seen.setdefault(s, p.relative_to(ROOT).as_posix())
    n = 0
    for code, d in papers():
        for s in stems(d):
            if s in seen:
                print(f"{code}：题干与 {seen[s]} 重复：{s}")
                n += 1
            else:
                seen[s] = f"exams/{code}.yaml"
        dist = Counter()
        for ex in d["exercises"]:
            if ex["type"] == "choice":
                for it in ex["items"]:
                    if it["answer"] in it["options"]:
                        dist["ABCD"[it["options"].index(it["answer"])]] += 1
        tot = sum(dist.values()) or 1
        skew = max(dist.values(), default=0) / tot
        print(f"{code}：正确答案分布 " + " ".join(f"{k}{dist[k]}" for k in "ABCD") + ("　← 偏斜" if skew > 0.35 else ""))
    print(f"重复题干 {n} 处")
    return n


def flow(xs):
    """选项写回 YAML 流式列表：含逗号、冒号或以引号、方括号开头的选项加单引号。"""
    out = []
    for x in xs:
        x = str(x)
        if re.search(r"[,:#\[\]{}]|^['\"&*!|>%@`-]", x) or not isinstance(yaml.safe_load(x), str):   # 13.30、да 之类会被读成数字或布尔
            x = "'" + x.replace("'", "''") + "'"
        out.append(x)
    return "[" + ", ".join(out) + "]"


def balance(code):
    """正确答案的位置按每 4 题一组打乱的 A B C D 循环分配，其余选项保持原来的相对顺序。"""
    import random
    rnd = random.Random(code)
    path = EXAMS / f"{code}.yaml"
    lines = path.read_text(encoding="utf-8").split("\n")
    slots = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*(?:- )?)options: (\[.*\])\s*$", ln)
        if not m:
            continue
        opts = yaml.safe_load(m.group(2))
        j = next(j for j in range(i + 1, min(i + 4, len(lines))) if re.match(r"^\s*answer:", lines[j]))
        ans = yaml.safe_load(lines[j].split("answer:", 1)[1].strip())
        if ans not in opts or len(opts) != 4:
            continue
        if not slots:
            slots = [0, 1, 2, 3]
            rnd.shuffle(slots)
        k = slots.pop()
        rest = [o for o in opts if o != ans]
        new = rest[:k] + [ans] + rest[k:]
        lines[i] = m.group(1) + "options: " + flow(new)
    path.write_text("\n".join(lines), encoding="utf-8")
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    print(code, Counter("ABCD"[it["options"].index(it["answer"])] for ex in d["exercises"] if ex["type"] == "choice" for it in ex["items"]))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--balance"]:
        for c in args[1:]:
            balance(c)
        sys.exit(0)
    if args[:1] == ["--check"]:
        sys.exit(1 if check() else 0)
    build(args or None)
