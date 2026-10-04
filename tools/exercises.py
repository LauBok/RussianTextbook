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


def ru(s):
    return f"[{s}]{{.ru}}"


def blank(stem):
    return stem.replace("___", "[]{.blank}")


# ---------- 1. PDF 练习节 ----------

def pdf_exercises(data, img_dir):
    out = ["## 练习", ""]
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
                out.append(f"{i}. {ru(blank(it['stem']))}")
        elif t == "rewrite":
            e = ex.get("example")
            if e:
                out += [f"例：{ru(e['cue'])} → {ru(e['answer'])}", ""]
            for i, it in enumerate(ex["items"], 1):
                out.append(f"{i}. {ru(it['cue'])}")
        elif t == "fill":
            for i, it in enumerate(ex["items"], 1):
                out.append(f"{i}. {ru(blank(it['stem']) + ' (' + it['hint'] + ')')}")
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
            out += ["", f"[解析：{ex['why']}]{{.why}}", ""]
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
    return {"lesson": data["lesson"], "exercises": exs}


def main(lesson):
    data = yaml.safe_load((ROOT / "exercises" / f"{lesson}.yaml").read_text(encoding="utf-8"))
    img_dir = f"img/{lesson}"
    gen = ROOT / "build" / "gen"
    gen.mkdir(parents=True, exist_ok=True)

    src = (ROOT / "lessons" / f"{lesson}.md").read_text(encoding="utf-8")
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
