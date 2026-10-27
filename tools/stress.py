#!/usr/bin/env python3
"""重音位置核对：把全书（第一至四册）标了重音的词形和离线重音词典比对，列出位置不一致的词。

    python3 tools/stress.py                 # 核对第一至四册，结果写进 docs/重音核对.md
    python3 tools/stress.py B3-L03 L05      # 只核对这几课，结果打印到终端
    python3 tools/stress.py grammar         # 核对语法书 grammar/*.md，结果打印到终端
    python3 tools/stress.py build <openrussian 目录> <zalizniak 目录>   # 重新生成词典

词典 tools/data/stress.tsv.gz 由两份开放数据合成，每行“词形（去重音、ё→е）<TAB>重音位置,…”：
  - OpenRussian 词形表（https://github.com/Badestrand/russian-dictionary，CC BY-SA 4.0）：名词、形容词、动词的全部变化形式；
  - 扎利兹尼亚克《俄语语法词典》第六版（https://github.com/gramdict/zalizniak-2010，CC BY-NC 4.0）：约 11 万词条的原形。
重音位置是去掉重音符后重读元音的下标；同一词形有几种重音（同形异义词、两读）时都记下，课文用其中任何一种都不报。
只报告，不自动改。词典缺词、同形异义的不算错，由审校逐条判断。
"""
import csv
import gzip
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tools" / "data" / "stress.tsv.gz"
VOWELS = set("аеёиоуыэюя")
ACUTE = "́"


def key(w):
    return check.nfc(w).replace(ACUTE, "").replace("̀", "").lower().replace("ё", "е")


def positions(w):
    """带重音的词形 → 重读元音下标集合（重音符或 ё）；看不出重音时返回空集。"""
    w = check.nfc(w).replace("̀", "").lower()
    out, idx = set(), 0
    for ch in w:
        if ch == ACUTE:
            if idx and w.replace(ACUTE, "")[idx - 1] in VOWELS:
                out.add(idx - 1)
        else:
            idx += 1
    if not out:
        bare = w.replace(ACUTE, "")
        out = {i for i, ch in enumerate(bare) if ch == "ё"}
    return out


def syllables(w):
    return sum(1 for ch in key(w) if ch in VOWELS)


# ---------- 生成词典 ----------

def build(openrussian, zalizniak):
    table = defaultdict(set)

    def add(form):
        form = form.strip().strip("*").replace("'", ACUTE)
        if not form or " " in form or syllables(form) < 2:
            return
        for part in form.split("-"):
            if syllables(part) >= 2 and positions(part):
                table[key(part)] |= positions(part)

    for name in ("nouns", "adjectives", "verbs", "others"):
        with open(Path(openrussian) / f"{name}.csv", encoding="utf-8") as f:
            rows = csv.reader(f, delimiter="\t")
            head = next(rows)
            skip = {head.index(c) for c in ("bare", "translations_en", "translations_de", "gender", "partner",
                                             "animate", "indeclinable", "sg_only", "pl_only", "aspect") if c in head}
            for row in rows:
                for i, cell in enumerate(row):
                    if i in skip:
                        continue
                    for form in re.split(r"[,;/]", cell):
                        add(form)
    for p in Path(zalizniak).rglob("*.txt"):
        for ln in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\d*/?([а-яёА-ЯЁ́̀-]+)", ln)
            if m:
                add(m.group(1))
    DATA.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(DATA, "wt", encoding="utf-8") as f:
        for k in sorted(table):
            f.write(f"{k}\t{','.join(map(str, sorted(table[k])))}\n")
    print(f"{DATA}：{len(table)} 个词形")


def load():
    table = {}
    with gzip.open(DATA, "rt", encoding="utf-8") as f:
        for ln in f:
            k, v = ln.rstrip("\n").split("\t")
            table[k] = {int(x) for x in v.split(",")}
    return table


# ---------- 核对 ----------

def stressed_words(text):
    """文本里带重音符的多音节词（连字符词逐段）。"""
    for w, morpheme in check.tokens(text):
        if morpheme:
            continue
        for part in w.split("-"):
            if ACUTE in part and syllables(part) >= 2:
                yield part


def mark(w, pos):
    bare = key(w)
    return "".join(ch + (ACUTE if i in pos else "") for i, ch in enumerate(bare))


def sources(wanted):
    if wanted == {"grammar"}:      # 语法书各章
        for path in sorted((ROOT / "grammar").glob("*.md")):
            for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                yield path.stem, f"grammar/{path.name}:{i}", ln
        return
    for (book, lid), path in check.lesson_files():
        if book > 4 or (wanted and (book, lid) not in wanted):
            continue
        stem = path.stem
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            yield stem, f"lessons/{stem}.md:{i}", ln
        ex = ROOT / "exercises" / f"{stem}.yaml"
        if ex.exists():
            for i, ln in enumerate(ex.read_text(encoding="utf-8").splitlines(), 1):
                yield stem, f"exercises/{stem}.yaml:{i}", ln


def run(wanted):
    table = load()
    found = defaultdict(list)          # (key, 我们的位置) → 出处
    checked = missing = 0
    for stem, where, ln in sources(wanted):
        for w in stressed_words(ln):
            k = key(w)
            pos = positions(w)
            if k not in table:
                missing += 1
                continue
            checked += 1
            if not pos & table[k] and where not in found[(k, tuple(sorted(pos)))]:
                found[(k, tuple(sorted(pos)))].append(where)
    rows = []
    for (k, pos), places in sorted(found.items(), key=lambda x: x[1][0]):
        dict_forms = " / ".join(mark(k, {p}) for p in sorted(table[k]))
        rows.append((mark(k, set(pos)), dict_forms, places))
    return rows, checked, missing


def report(rows, checked, missing):
    out = ["# 重音核对", "",
           "由 `python3 tools/stress.py` 生成：把第一至四册课文、生词表、练习里标了重音的多音节词形，"
           "和离线重音词典（OpenRussian 词形表 + 扎利兹尼亚克《俄语语法词典》原形）比对，"
           "列出重音位置与词典任何一种读法都不一致的词形。只报告，不自动改；词典缺词、同形异义、词典本身有误的不算错。", "",
           f"比对词次 {checked}，词典未收词次 {missing}，不一致词形 {len(rows)} 个。", "",
           "| 书中写法 | 词典 | 出处 | 审校结论 |", "|---|---|---|---|"]
    for ours, theirs, places in rows:
        loc = "、".join(places[:4]) + (f" 等 {len(places)} 处" if len(places) > 4 else "")
        out.append(f"| {ours} | {theirs} | {loc} |  |")
    return "\n".join(out) + "\n"


def main(argv):
    if argv[:1] == ["build"]:
        return build(argv[1], argv[2])
    wanted = {"grammar"} if argv and all(a.rstrip("/") == "grammar" for a in argv) else {check.canon(Path(a).stem) for a in argv}
    rows, checked, missing = run(wanted)
    if wanted:
        for ours, theirs, places in rows:
            print(f"{ours}\t词典：{theirs}\t{'、'.join(places)}")
        print(f"比对 {checked}，未收 {missing}，不一致 {len(rows)}")
    else:
        (ROOT / "docs" / "重音核对.md").write_text(report(rows, checked, missing), encoding="utf-8")
        print(f"docs/重音核对.md：比对 {checked}，未收 {missing}，不一致 {len(rows)}")


if __name__ == "__main__":
    main(sys.argv[1:])
