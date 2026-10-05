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
DIGITS = "零一二三四五六七八九"


def zh_num(n):
    """1 → 一，10 → 十，12 → 十二，20 → 二十（练习序号用）。"""
    if n < 10:
        return DIGITS[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else DIGITS[tens]) + "十" + (DIGITS[ones] if ones else "")


class _Num:
    def __getitem__(self, i):      # NUM[0] → 一（练习从 0 开始编号）
        return zh_num(i + 1)


NUM = _Num()


IPA = re.compile(r"\[[^\[\]\u0400-\u04ff\d]+\](?!\{)")


def ipa(s):
    return IPA.sub(lambda m: f"[\\{m.group(0)[:-1]}\\]]{{.ipa}}", s)


def ru(s):
    """俄语 span；其中的 [音标] 改用 IPA 字体。"""
    return f"[{ipa(s)}]{{.ru}}"


def blank(stem):
    return stem.replace("___", "[]{.blank}")


# ---------- 1. PDF 练习节 ----------

def answer_lines(it):
    """开放题留几行：手写俄语约每行 8 词，按 length 上限算，至少 6 行；lines 字段可直接指定。"""
    if it.get("lines"):
        return it["lines"]
    nums = [int(x) for x in re.findall(r"\d+", str(it.get("length", "")))]
    return max(6, -(-max(nums) // 8) + 1) if nums else 6


def scored(data):
    """测试题的 points（每小题分值）写进题目要求：“（每小题 2 分，共 20 分）”。只处理一次。"""
    if data.get("_scored"):
        return data
    for ex in data.get("exercises", []):
        p = ex.get("points")
        if p:
            n = len(ex.get("items") or [])
            ex["task"] = ex["task"].rstrip("。") + (f"（共 {p} 分）" if n == 1 else f"（每小题 {p} 分，共 {p * n} 分）")
    data["_scored"] = True
    return data


def pdf_exercises(data, img_dir):
    data = scored(data)
    out = [f"## {data.get('heading', '练习')}", ""]
    if data.get("intro"):
        out += [data["intro"], ""]
    for n, ex in enumerate(data["exercises"]):
        head = f"[{NUM[n]}、{ex['task']}]{{.task}}"
        long = ex.get("passage") or re.search(r"T[012]$", str(data.get("lesson", "")))   # 测试页的大题可以跨页
        out += ["::: {.exercise .long}" if long else "::: exercise", head, ""]
        if ex.get("passage"):          # 阅读理解、完形填空的文章，放在本题要求之后
            out += ["::: passage", ex["passage"].strip(), ":::", ""]
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
            test = re.search(r"T[012]$", str(data.get("lesson", "")))
            for i, it in enumerate(ex["items"], 1):
                if test:      # 测试页：选项标 A B C D，按最长选项排成一行四个、两个或一个；完形填空没有题干
                    longest = max(_text_em(f"A. {o}", "option") for o in it["options"])
                    cols = 4 if longest <= 9 else 2 if longest <= 20 else 1
                    opts = "".join(f"[{'ABCD'[k]}. {ru(o)}]{{.opt}}" for k, o in enumerate(it["options"]))
                    stem = ru(blank(it["stem"])) if it.get("stem") else ""
                    out.append(f"{i}. {stem}[{opts}]{{.opts .c{cols}}}")
                else:
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
                n_lines = it.get("lines") or (2 if len(it["zh"]) > 25 and re.search(r"T[012]$", str(data.get("lesson", ""))) else 1)
                out += [f"{i}. {it['zh']}"] + ["   []{.line}"] * n_lines
        elif t == "open":
            for it in ex["items"]:
                n_lines = answer_lines(it)
                out += [it["prompt"], ""] + ["[]{.line}"] * n_lines + [""]
        out += [":::", ""]
    return "\n".join(out)


# ---------- 2. 答案与解析 ----------

def why_lines(why):
    """解析按“第 N 题 / 空 / 篇”分行：每道小题的解析单独一段。"""
    parts = [p.strip() for p in re.split(r"(?<=[。；）\]\}])\s*(?=第\s*\d+(?:[–、,，]\d+)*\s*[题空篇])", why.strip()) if p.strip()]
    out = ["[解析]{.why-head}", ""]
    for p in parts:
        out += [f"[{ipa(p)}]{{.why}}", ""]
    return out


def key_markdown(data):
    data = scored(data)
    out = []
    for n, ex in enumerate(data["exercises"]):
        out += [f"## {NUM[n]}、{ex['task'].rstrip('。')}", ""]
        t = ex["type"]
        if ex.get("passage_zh"):       # 测试页文章的参考译文放在答案里
            out += ["文章参考译文：", "", "::: prose-zh", ex["passage_zh"].strip(), ":::", ""]
        for i, it in enumerate(ex["items"], 1):
            if t == "picture_qa":
                out.append(f"{i}. {ru('— ' + it['qword'] + ' э́то? — ' + it['answer'][0])}")
            elif t == "choice":
                k = it["options"].index(it["answer"]) if it["answer"] in it["options"] else -1
                letter = f"{'ABCD'[k]}. " if re.search(r"T[012]$", str(data.get("lesson", ""))) and 0 <= k < 4 else ""
                out.append(f"{i}. {letter}{ru(it['answer'])}")
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
            out += [""] + why_lines(ex["why"])
        out.append("")
    return "\n".join(out)


# ---------- 3. 交互页数据 ----------

def web_json(data, img_dir):
    data = scored(data)
    exs = []
    for ex in data["exercises"]:
        e = {k: v for k, v in ex.items()}
        if ex.get("passage"):
            import subprocess
            e["passage_html"] = subprocess.run(
                ["pandoc", "-f", "markdown", "-t", "html5", "--lua-filter", str(ROOT / "zh-punct.lua")],
                input=ex["passage"], capture_output=True, text=True, check=True, cwd=ROOT).stdout
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
    """单元词汇总表：<!-- UNIT_VOCAB L01-L09 -->、<!-- UNIT_VOCAB B2-L01-B2-L08 --> 展开为按课排列的表格。"""
    prefix = first.rsplit("L", 1)[0]                     # "" 或 "B2-"
    a, b = int(first.rsplit("L", 1)[1]), int(last.rsplit("L", 1)[1])
    rows = []
    for n in range(a, b + 1):
        code = f"{prefix}L{n:02d}"
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


def culture(lesson):
    """彩色配图 img/<课>/*GPT.jpg（AI 生成）或 *PD.jpg（公有领域原作），缩小后内嵌为 <figure class="culture">；没有图时返回空串。"""
    if not lesson:
        return ""
    files = sorted(p for p in (ROOT / "img" / lesson).glob("*") if re.search(r"(GPT|PD)$", p.stem)
                   and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if not files:
        return ""
    import base64, io
    from PIL import Image
    im = Image.open(files[0]).convert("RGB")
    im.thumbnail((1400, 1400))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    data = base64.b64encode(buf.getvalue()).decode()
    return f'<figure class="culture"><img src="data:image/jpeg;base64,{data}" alt=""></figure>\n\n'


SP_FONTS = {
    "dialogue": ("/usr/share/fonts/truetype/paratype/PTF75F.ttf", 0, ":"),        # PT Serif Bold
    "translation": ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", 2, "："),  # Noto Serif CJK SC Bold
}
SP_MIN = {"dialogue": 3.5, "translation": 3.0}
SP_FONTS["option"] = ("/usr/share/fonts/truetype/paratype/PTF55F.ttf", 0, "")    # PT Serif，选择题选项宽度


def _text_em(text, kind):
    """按实际字体量出文字宽度（单位 em）；量不了时按字符数估算。"""
    path, index, _ = SP_FONTS[kind]
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(path, 100, index=index)
        return font.getlength(text) / 100
    except Exception:
        return sum(1.0 if ord(c) > 0x2E80 else 0.62 for c in text)


def speaker_widths(md):
    """对话块、参考译文块按本块最长的说话人名设定说话人栏宽度（CSS 变量 --sp），名字永远一行。"""
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"^:::\s*(\{[^}]*\}|\S+)\s*$", lines[i])
        kind = None
        if m:
            head = m.group(1)
            kind = "dialogue" if ".dialogue" in head else "translation" if re.fullmatch(r"\{?\.?translation\}?|\{\.translation[^}]*\}", head) else None
        if not kind:
            i += 1
            continue
        j = i + 1
        names = []
        while j < len(lines) and not re.match(r"^:::\s*$", lines[j]):
            for n in re.findall(r"\[([^\[\]]+)\]\{\.sp\}", lines[j]):
                names.append(re.sub(r"[\u0301]", "", n))
            # 名字后的空格会让首行比续行多缩进一格
            lines[j] = re.sub(r"(\]\{\.sp\})[ \t]+", r"\1", lines[j])
            j += 1
        if names:
            colon = SP_FONTS[kind][2]
            width = max(_text_em(n + colon, kind) for n in names) + 0.6
            width = max(round(width + 0.05, 1), SP_MIN[kind])
            if kind == "dialogue":
                lines[i] = re.sub(r"\}\s*$", f' style="--sp: {width}em"}}', lines[i])
            else:
                lines[i] = f'::: {{.translation style="--sp: {width}em"}}'
        i = j + 1
    return "\n".join(lines)


def expand(md, lesson=None):
    md = re.sub(r"<!-- UNIT_VOCAB ((?:B\d-)?L\d+)-((?:B\d-)?L\d+) -->", lambda m: unit_vocab(m.group(1), m.group(2)), md)
    md = speaker_widths(md)
    pic = scene(lesson)
    if pic:
        md = re.sub(r"^## 课文[ \t]*\n\n?", lambda m: m.group(0).rstrip("\n") + "\n\n" + pic, md, count=1, flags=re.M)
    fig = culture(lesson)
    if fig:
        # 有“俄罗斯知识”时放在它的第一个小标题之后，浮动图与正文顶端对齐
        if re.search(r"^## 作者与作品简介", md, re.M):
            # 第四册：作家肖像、作品插图放在“作者与作品简介”右侧
            md = re.sub(r"^## 作者与作品简介[ \t]*\n\n?", lambda m: m.group(0).rstrip("\n") + "\n\n" + fig, md, count=1, flags=re.M)
        elif re.search(r"^## 俄罗斯知识", md, re.M):
            md = re.sub(r"^## 俄罗斯知识[ \t]*\n(?:\s*\n)*(### [^\n]*\n)?\n?", lambda m: m.group(0).rstrip("\n") + "\n\n" + fig, md, count=1, flags=re.M)
        else:
            # 第三册起没有“俄罗斯知识”：放在课文（选文）第一段右侧
            md = re.sub(r"^## (?:课文|选文)[ \t]*\n\n?", lambda m: m.group(0).rstrip("\n") + "\n\n" + fig, md, count=1, flags=re.M)
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
