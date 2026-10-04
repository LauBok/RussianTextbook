#!/usr/bin/env python3
"""生成交互课页：python3 tools/web.py L01 → web/L01.html
课文、生词、译文取自 lessons/<课>.md，练习取自 exercises/<课>.yaml。"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import exercises  # noqa: E402

import yaml

ROOT = Path(__file__).resolve().parent.parent


def block(md, cls):
    m = re.search(r"^:::\s*\{?\.?" + cls + r"[^\n]*\n(.*?)^:::\s*$", md, re.S | re.M)
    return m.group(1) if m else ""


def lines(body):
    out = []
    for ln in body.splitlines():
        m = re.match(r"\[(.+?)\]\{\.sp\}\s*(.+)$", ln.strip())
        if m:
            out.append({"sp": m.group(1), "text": m.group(2)})
    return out


def strip_md(s):
    s = re.sub(r"\[\[(.+?)\]\]\{\.tr\}", r"[\1]", s)
    s = re.sub(r"\[(.+?)\]\{\.[a-z]+\}", r"\1", s)
    return s.strip()


def vocab(md):
    rows = []
    for ln in block(md, "vocab").splitlines():
        if not ln.startswith("| [") :
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        word_cell = cells[0]
        m = re.match(r"\[(.+?)\]\{\.ru\}\s*(?:\[\[(.+?)\]\]\{\.tr\})?", word_cell)
        rows.append({"word": m.group(1), "tr": m.group(2) or "",
                     "pos": strip_md(cells[1]), "gloss": strip_md(cells[2])})
    return rows


def main(lesson):
    md = exercises.expand((ROOT / "lessons" / f"{lesson}.md").read_text(encoding="utf-8"), lesson)
    front = yaml.safe_load(md.split("\n---\n", 1)[0].lstrip("-\n"))
    ex = yaml.safe_load((ROOT / "exercises" / f"{lesson}.yaml").read_text(encoding="utf-8"))
    data = {
        "book": front["book"], "unit": front["unit"], "lesson": front["lesson"],
        "title": front["title"], "subtitle": front["subtitle"],
        "label": front.get("label", ""),
        "grammar": ex.get("grammar", ""),
        "exercises": exercises.web_json(ex, f"img/{lesson}")["exercises"],
    }
    heading = ex.get("heading", "练习")
    intro = f'<p class="ex-intro">{ex["intro"]}</p>' if ex.get("intro") else ""
    root = ('<div id="ex-root">' + intro + '<div class="score" id="score"></div>'
            '<div id="exercises"></div></div>')
    body_md = md.replace("<!-- EXERCISES -->", f"## {heading}\n\n" + root)
    html = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "html5", "--lua-filter", str(ROOT / "zh-punct.lua")],
        input=body_md, capture_output=True, text=True, check=True, cwd=ROOT).stdout
    tpl = (ROOT / "web" / "template.html").read_text(encoding="utf-8")
    page = tpl.replace("/*LESSON_DATA*/null", json.dumps(data, ensure_ascii=False))
    i = html.index(f'<h2 id="{heading}">')
    j = html.find('<h2 id="参考译文">')
    if j < 0:
        j = len(html)
    ex_html = html[i:j].split("</h2>", 1)[1]
    page = page.replace("<!--TEXT_HTML-->", html[:i] + html[j:])
    page = page.replace(">练习</button>", f">{heading}</button>", 1)
    page = page.replace("<!--EX_HTML-->", ex_html)
    page = page.replace("{{TITLE}}", f"俄语教程 第{front['lesson']}课")
    out = ROOT / "web" / f"{lesson}.html"
    out.write_text(page, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main(sys.argv[1])
