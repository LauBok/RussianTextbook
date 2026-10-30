#!/usr/bin/env python3
"""背单词网页：words/ 下的页面 + 第一册各课生词 words.json → site/words/

    python3 tools/words.py

每个词条 id 为“课号-序号”（序号是生词表里的行号，从 1 起），重新生成时不变，读者的复习进度不会错位。
例句取本课课文里第一个含这个词的句子，汉译取参考译文里同一位置的句子（对不上就不放汉译）。
发音文件 audio/words/<id>.mp3 由 `python tools/tts.py --words` 生成，存在才写进词条。
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402
import exercises  # noqa: E402

ROOT = book.ROOT
ACUTE = "́"


def plain(s):
    """去掉 Markdown 标记：[x]{.ru} → x，[[...]]{.tr} 去掉。"""
    s = re.sub(r"\[\[[^\]]*\]\]\{\.tr\}", "", s)
    s = re.sub(r"\[([^\[\]]*)\]\{[^}]*\}", r"\1", s)
    return re.sub(r"\s+", " ", s.replace("**", "")).strip()


def bare(s):
    return s.replace(ACUTE, "").replace("ё", "е").lower()


def section(md, title):
    m = re.search(rf"^## {title}\s*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1) if m else ""


def paragraphs(sec):
    out = []
    for p in re.split(r"\n\s*\n", sec):
        p = "\n".join(ln for ln in p.splitlines() if not ln.startswith(":::")).strip()
        if p:
            out.append(plain(re.sub(r"^\[[^\]]*\]\{\.sp\}\s*", "", p)))
    return out


def sentences(text, zh=False):
    pat = r"(?<=[。！？])" if zh else r"(?<=[.!?…])\s+(?=[—«А-ЯЁA-Z])"
    return [s.strip() for s in re.split(pat, text) if s.strip()]


def example(word, ru_pars, zh_pars):
    """课文中第一个含这个词（按词干匹配）的句子及其汉译。"""
    head = bare(word.split()[0].strip("?!.,"))
    stem = head if len(head) < 5 else head[:-2]
    for i, par in enumerate(ru_pars):
        sents = sentences(par)
        for j, s in enumerate(sents):
            toks = re.findall(r"[а-яё́-]+", s.lower())
            if any(bare(t) == head or (len(head) >= 5 and bare(t).startswith(stem)) for t in toks):
                zh = ""
                if len(zh_pars) == len(ru_pars):
                    zs = sentences(zh_pars[i], zh=True)
                    zh = zs[j] if len(zs) == len(sents) else (zh_pars[i] if len(sents) == 1 else "")
                return s, zh
    return "", ""


def lessons():
    codes = [p.stem for p in (ROOT / "lessons").glob("L*.md") if re.fullmatch(r"L\d+", p.stem)]
    return sorted(codes, key=lambda c: int(c[1:]))


def main():
    out, units = [], []
    for code in lessons():
        md = (ROOT / "lessons" / f"{code}.md").read_text(encoding="utf-8")
        rows = exercises.lesson_vocab(code)
        if not rows:
            continue
        fm = book.front_matter(md)
        unit = str(fm.get("unit", ""))
        if not units or units[-1]["unit"] != unit:
            units.append({"unit": unit, "lessons": []})
        units[-1]["lessons"].append({"code": code, "title": plain(str(fm.get("title", ""))),
                                     "subtitle": plain(str(fm.get("subtitle", "")))})
        ru_pars, zh_pars = paragraphs(section(md, "课文")), paragraphs(section(md, "参考译文"))
        for k, (word, pos, gloss) in enumerate(rows, 1):
            w = plain(word)
            ex_ru, ex_zh = example(re.split(r",\s*-", w)[0], ru_pars, zh_pars)
            item = {"id": f"{code}-{k:02d}", "lesson": code, "word": w, "pos": plain(pos), "gloss": plain(gloss)}
            if ex_ru:
                item["ex"] = ex_ru
                if ex_zh:
                    item["exZh"] = ex_zh
            if (ROOT / "audio" / "words" / f"{item['id']}.mp3").exists():
                item["audio"] = f"audio/words/{item['id']}.mp3"
            out.append(item)
    dest = ROOT / "site" / "words" / "words.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "words").iterdir():
        shutil.copy(f, dest.parent / f.name)
    dest.write_text(json.dumps({"units": units, "words": out}, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(dest, f"{len(out)} 词，{sum(len(u['lessons']) for u in units)} 课，发音 {sum('audio' in w for w in out)} 个")


if __name__ == "__main__":
    main()
