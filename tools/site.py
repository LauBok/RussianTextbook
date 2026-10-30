#!/usr/bin/env python3
"""静态站点：四册每课的朗读音频（在线播放、下载）和 PDF 下载，供 GitHub Pages 发布。

    python3 tools/site.py  →  site/index.html

音频引用 audio/<课号>.mp3、PDF 引用 dist/*.pdf，发布时与 site/index.html 放在同一目录
（见 .github/workflows/pages.yml）。
"""
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402

ROOT = book.ROOT
PDFS = [("第一册", "dist/第一册.pdf"), ("第二册", "dist/第二册.pdf"), ("第三册", "dist/第三册.pdf"),
        ("第四册", "dist/第四册.pdf"), ("课程总表", "dist/课程总表.pdf"), ("语法点分布图", "dist/语法点分布图.pdf")]


def esc(s):
    return html.escape(str(s))


def plain(s):
    return re.sub(r"\[(.+?)\]\{[^}]*\}", r"\1", str(s))


def mb(p):
    return f"{(ROOT / p).stat().st_size / 1e6:.0f} MB"


def book_section(n):
    out, unit = [], None
    rows = 0
    for code in book.lesson_codes(n):
        if re.search(r"T[012]$", code):
            continue
        audio = ROOT / "audio" / f"{code}.mp3"
        if not audio.exists():
            continue
        fm = book.front_matter((ROOT / "lessons" / f"{code}.md").read_text(encoding="utf-8"))
        u = fm.get("unit", "")
        if u != unit:
            if unit is not None:
                out.append("</ul>")
            out.append(f"<h3>{esc(u)}</h3><ul>")
            unit = u
        num = re.search(r"(\d+)$", code).group(1).lstrip("0")
        label = f"语音 {num}" if code.startswith("P") else f"第 {num} 课"
        media = (f'<audio controls preload="none" src="audio/{code}.mp3"></audio>'
                 f'<a class="dl" href="audio/{code}.mp3" download aria-label="下载 {label} 音频">下载</a>')
        rows += 1
        out.append(f'<li><span class="no">{label}</span><span class="ti"><span lang="ru">{esc(plain(fm.get("title", "")))}</span>'
                   f'<span class="sub">{esc(plain(fm.get("subtitle", "")))}</span></span><span class="media">{media}</span></li>')
    out.append("</ul>")
    return rows, "".join(out)


CSS = """
:root { --paper:#fbf8f3; --ink:#1f1f1f; --muted:#6b6b6b; --accent:#8a2b2b; --rule:#e3dbd0; --card:#fff; }
@media (prefers-color-scheme: dark) { :root { --paper:#18181a; --ink:#e9e6e1; --muted:#a29d96; --accent:#e09088; --rule:#3a3633; --card:#222124; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.6 "PT Serif","Noto Serif SC",serif; }
main { max-width:880px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:30px; margin:0 0 4px; } .lead { color:var(--muted); margin:0 0 20px; }
nav { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 24px; position:sticky; top:0; background:var(--paper); padding:8px 0; z-index:1; }
nav a { font:600 14px "PT Sans","Noto Sans SC",sans-serif; color:var(--accent); text-decoration:none; border:1px solid var(--rule); border-radius:999px; padding:4px 12px; }
h2 { font:700 20px "PT Sans","Noto Sans SC",sans-serif; color:var(--accent); margin:36px 0 4px; scroll-margin-top:56px; }
h3 { font:700 14px "PT Sans","Noto Sans SC",sans-serif; color:var(--muted); margin:20px 0 6px; }
.count { color:var(--muted); font-size:14px; margin:0; }
ul { list-style:none; margin:0; padding:0; }
li { display:grid; grid-template-columns:72px 1fr auto; gap:4px 12px; align-items:center; padding:8px 0; border-bottom:1px solid var(--rule); }
.no { color:var(--muted); font-size:14px; } .sub { color:var(--muted); margin-left:10px; font-size:14px; }
.media { display:flex; align-items:center; gap:8px; }
audio { height:32px; width:260px; }
.dl { font:13px "PT Sans",sans-serif; color:var(--accent); }
.pdfs { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:8px; }
.pdfs a { display:block; background:var(--card); border:1px solid var(--rule); border-radius:8px; padding:10px 12px; color:var(--ink); text-decoration:none; }
.pdfs a span { display:block; color:var(--muted); font-size:13px; }
@media (max-width:640px) { li { grid-template-columns:56px 1fr; } .media { grid-column:1 / -1; } audio { width:100%; } .sub { display:block; margin:0; } }
"""


def main():
    secs, total = [], 0
    for n in (1, 2, 3, 4):
        k, body = book_section(n)
        total += k
        secs.append(f'<h2 id="b{n}">{book.BOOK_NAME[n]}</h2><p class="count">{book.COVER_SUB[n]} · {k} 课录音</p>{body}')
    pdfs = "".join(f'<a href="{p}" download>{esc(t)}<span>PDF · {mb(p)}</span></a>' for t, p in PDFS if (ROOT / p).exists())
    nav = "".join(f'<a href="#b{n}">{book.BOOK_NAME[n]}</a>' for n in (1, 2, 3, 4)) + '<a href="#pdf">PDF 下载</a><a href="words/">背单词</a>'
    page = (f'<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>俄语教程 课文朗读</title>'
            f'<style>{CSS}</style></head><body><main><h1>俄语教程</h1>'
            f'<p class="lead">四册课文朗读，共 {total} 课。点播放在线听，或下载 mp3。</p><nav>{nav}</nav>'
            f'{"".join(secs)}<h2 id="pdf">PDF 下载</h2><div class="pdfs">{pdfs}</div></main></body></html>')
    out = ROOT / "site" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(out, total, "课")


if __name__ == "__main__":
    main()
