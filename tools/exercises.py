#!/usr/bin/env python3
"""由 exercises/<课>.yaml 生成三样东西：
   1. PDF 课文中的练习节（Markdown，替换课文里的 <!-- EXERCISES --> 标记）
   2. 书末答案附录中本课的答案与解析（Markdown）
   3. 交互页使用的练习数据（JSON）
用法：python3 tools/exercises.py L01
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NUM = "一二三四五六七八九十"


IPA = re.compile(r"\[[^\[\]\u0400-\u04ff]+\]")


def ipa(s):
    return IPA.sub(lambda m: f"[\\{m.group(0)[:-1]}\\]]{{.ipa}}", s)


def ru(s):
    """俄语 span；其中的 [音标] 改用 IPA 字体。"""
    return f"[{ipa(s)}]{{.ru}}"


def blank(stem):
    return stem.replace("___", "[]{.blank}")


# ---------- 1. PDF 练习节 ----------

def pdf_exercises(data, img_dir):
    out = [f"## {data.get('heading', '练习')}", ""]
    if data.get("intro"):
        out += [data["intro"], ""]
    for n, ex in enumerate(data["exercises"]):
        head = f"[{NUM[n]}、{ex['task']}]{{.task}}"
        out += ["::: exercise", head, ""]
        t = ex["type"]
        if t == "picture_qa":
            k = ex.get("example")
            if k:
                it = ex["items"][k - 1]
                out += [f"例：{k}　{ru('— ' + it['qword'] + ' э́то?')}　{ru('— ' + it['answer'][0])}", ""]
            out += ["::: pictures"]
            for i, it in enumerate(ex["items"], 1):
                out += [f"![{i}](../{img_dir}/{it['image']})", ""]
            out += [":::"]
        elif t == "choice":
            for i, it in enumerate(ex["items"], 1):
                opts = " / ".join(it["options"])
                out.append(f"{i}. {ru(blank(it['stem']))}　（{ru(opts)}）")
        elif t == "rewrite":
            e = ex.get("example")
            if e:
                out += [f"例：{ru(e['cue'])} → {ru(e['answer'])}", ""]
            for i, it in enumerate(ex["items"], 1):
                out.append(f"{i}. {ru(it['cue'])}")
        elif t == "fill":
            for i, it in enumerate(ex["items"], 1):
                hint = f" ({it['hint']})" if it.get("hint") else ""
                out.append(f"{i}. {ru(blank(it['stem']) + hint)}")
        elif t == "translate":
            for i, it in enumerate(ex["items"], 1):
                out += [f"{i}. {it['zh']}", "   []{.line}"]
        elif t == "open":
            for it in ex["items"]:
                out += [it["prompt"], ""] + ["[]{.line}"] * 6 + [""]
        out += [":::", ""]
    return "\n".join(out)


# ---------- 2. 答案与解析 ----------

def key_markdown(data):
    out = []
    for n, ex in enumerate(data["exercises"]):
        out += [f"## {NUM[n]}、{ex['task'].rstrip('。')}", ""]
        t = ex["type"]
        for i, it in enumerate(ex["items"], 1):
            if t == "picture_qa":
                out.append(f"{i}. {ru('— ' + it['qword'] + ' э́то? — ' + it['answer'][0])}")
            elif t == "choice":
                out.append(f"{i}. {ru(it['answer'])}")
            elif t in ("rewrite", "fill"):
                out.append(f"{i}. {ru(it['accept'][0])}")
            elif t == "open":
                out += ["参考范文：", "", "::: {.prose lang=\"ru\"}", it["model"].strip(), ":::", "",
                        f"[要点：{it['notes']}]{{.why}}", ""]
            elif t == "translate":
                alt = it["accept"][1:]
                line = f"{i}. {ru(it['accept'][0])}"
                if alt:
                    line += "　也可：" + "；".join(ru(a) for a in alt)
                out.append(line)
        if ex.get("why"):
            out += ["", f"[解析：{ipa(ex['why'])}]{{.why}}", ""]
    return "\n".join(out)


# ---------- 3. 交互页数据 ----------

def web_json(data, img_dir):
    exs = []
    for ex in data["exercises"]:
        e = {k: v for k, v in ex.items()}
        if ex["type"] == "picture_qa":
            for it in e["items"]:
                svg = (ROOT / img_dir / it["image"]).read_text(encoding="utf-8")
                it["svg"] = svg
        exs.append(e)
    return {"lesson": data["lesson"], "grammar": data.get("grammar", ""),
            "heading": data.get("heading", "练习"), "intro": data.get("intro", ""), "exercises": exs}


# ---------- 4. 课文中的自动内容 ----------

VOCAB_ROW = re.compile(r"^\|\s*(\[.+?\]\{\.ru\}(?:\s*\[\[.+?\]\]\{\.tr\})?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")


def lesson_vocab(code):
    """取出某课生词表的各行：(词, 词性, 释义)。"""
    path = ROOT / "lessons" / f"{code}.md"
    if not path.exists():
        return []
    md = path.read_text(encoding="utf-8")
    m = re.search(r"^::: vocab\s*\n(.*?)^:::\s*$", md, re.S | re.M)
    if not m:
        return []
    return [r.groups() for r in (VOCAB_ROW.match(ln) for ln in m.group(1).splitlines()) if r]


def unit_vocab(first, last):
    """单元词汇总表：<!-- UNIT_VOCAB L01-L09 --> 展开为按课排列的表格。"""
    a, b = int(first[1:]), int(last[1:])
    rows = []
    for n in range(a, b + 1):
        code = f"L{n:02d}"
        for word, pos, gloss in lesson_vocab(code):
            rows.append(f"| {n} | {word} | {pos} | {gloss} |")
    head = ["::: {.vocab .unit-vocab}", "| 课 | 词 | 词性 | 释义 |", "|---|---|---|---|"]
    return "\n".join(head + rows + [":::"])


CHARACTERS = ROOT / "img" / "characters.svg"


def character_symbols():
    """img/characters.svg 里的人物：id → <symbol>…</symbol>。"""
    if not CHARACTERS.exists():
        return {}
    text = CHARACTERS.read_text(encoding="utf-8")
    return {m.group(1): m.group(0) for m in re.finditer(r'<symbol\b[^>]*\bid="([^"]+)"[^>]*>.*?</symbol>', text, re.S)}


def with_characters(svg):
    """插图里的 <use href="#人物"> 引用人物库，把用到的 <symbol> 内嵌进 <defs>，让每处人物画法一致。"""
    ids = list(dict.fromkeys(re.findall(r'<use\b[^>]*\bhref="#([^"]+)"', svg)))
    if not ids:
        return svg
    lib = character_symbols()
    # 人物用 currentColor，跟随 .scene 的 color：网页深色模式下才能变成浅色（<use> 里的元素不受页面 CSS 影响）
    defs = "".join(lib[i] for i in ids if i in lib).replace('"#2b2b2b"', '"currentColor"')
    return re.sub(r"(<svg\b[^>]*>)", lambda m: m.group(1) + f"<defs>{defs}</defs>", svg, count=1)


def scene(lesson):
    """课文缩略图 img/<课>/scene.svg，内嵌为 <div class="scene">；没有图时返回空串。"""
    path = ROOT / "img" / lesson / "scene.svg"
    if not lesson or not path.exists():
        return ""
    svg = with_characters(re.sub(r"<\?xml[^>]*\?>\s*", "", path.read_text(encoding="utf-8")).strip())
    return f'<div class="scene" aria-hidden="true">{svg}</div>\n\n'


def expand(md, lesson=None):
    md = re.sub(r"<!-- UNIT_VOCAB (L\d+)-(L\d+) -->", lambda m: unit_vocab(m.group(1), m.group(2)), md)
    pic = scene(lesson)
    if pic:
        md = re.sub(r"^## 课文[ \t]*\n\n?", lambda m: m.group(0).rstrip("\n") + "\n\n" + pic, md, count=1, flags=re.M)
    return md


def main(lesson):
    data = yaml.safe_load((ROOT / "exercises" / f"{lesson}.yaml").read_text(encoding="utf-8"))
    img_dir = f"img/{lesson}"
    gen = ROOT / "build" / "gen"
    gen.mkdir(parents=True, exist_ok=True)

    src = expand((ROOT / "lessons" / f"{lesson}.md").read_text(encoding="utf-8"), lesson)
    assert "<!-- EXERCISES -->" in src, f"{lesson}.md 缺少 <!-- EXERCISES --> 标记"
    (gen / f"{lesson}.md").write_text(src.replace("<!-- EXERCISES -->", pdf_exercises(data, img_dir)), encoding="utf-8")

    front = src.split("\n---\n", 1)[0] + "\n---\n"
    front = re.sub(r"^unit: .*$", "unit: 练习答案", front, flags=re.M)
    front = re.sub(r"^subtitle: .*$", "subtitle: 练习答案与解析", front, flags=re.M)
    (gen / f"{lesson}-答案.md").write_text(front + "\n" + key_markdown(data), encoding="utf-8")

    (gen / f"{lesson}.json").write_text(json.dumps(web_json(data, img_dir), ensure_ascii=False, indent=1), encoding="utf-8")
    print(gen / f"{lesson}.md", gen / f"{lesson}-答案.md", gen / f"{lesson}.json", sep="\n")


if __name__ == "__main__":
    main(sys.argv[1])
