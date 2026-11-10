#!/usr/bin/env python3
"""背单词网页用的词形变化表：从 OpenRussian 词形表里取出教材生词的变位、变格，写进 tools/data/paradigms.json。

    python3 tools/paradigms.py <OpenRussian 目录>

<OpenRussian 目录> 里要有 nouns.csv、verbs.csv、adjectives.csv
（https://github.com/Badestrand/russian-dictionary，CC BY-SA 4.0）。
只在词表变动后重跑；tools/words.py 读 paradigms.json，构建时不需要下载原表。

按带重音的原形匹配（同形异义词靠重音区分），词性按生词表的词类栏：动词 impf./pf.，名词 m/f/n/pl.，形容词 adj.，代词 pron. 到形容词表里找（мой、како́й、э́тот 等）。
"""
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import book  # noqa: E402
import exercises  # noqa: E402
import words  # noqa: E402

ROOT = book.ROOT
OUT = ROOT / "tools" / "data" / "paradigms.json"
ACUTE = "́"
VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"

CASES = ["nom", "gen", "dat", "acc", "inst", "prep"]


NO_IMP = {"хоте́ть", "мочь", "ви́деть", "слы́шать", "уме́ть", "люби́ть", "нра́виться", "зави́сеть", "сто́ить"}   # 命令式不用或几乎不用


def acc(s):
    """OpenRussian 的 челове'к → челове́к；单音节词不标重音（和教材一致）；去掉 -ою/-ею 这类书面变体。"""
    out = []
    parts = s.split(",")
    if len(parts) > 1:
        parts = [x for x in parts if not x.strip().replace("'", "").endswith(("ою", "ею"))] or parts
    for part in parts:
        w = part.strip().replace("'", ACUTE)
        if sum(c in VOWELS for c in w) <= 1:
            w = w.replace(ACUTE, "")
        out.append(w)
    return ", ".join(x for x in out if x)


def key(s):
    return s.replace("'", ACUTE).replace(ACUTE, "").replace("ё", "е").lower()


def stressed(s):
    """规范化的带重音形式，用来比较：ё 本身算重音。"""
    s = s.replace("'", ACUTE).lower()
    if "ё" in s:
        s = s.replace(ACUTE, "")
    return s


def load(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows.setdefault(key(r["bare"]), []).append(r)
    return rows


def pick(cands, word):
    """同一个不带重音的原形有几条时，取重音和生词表一致的那条。"""
    if not cands:
        return None
    want = stressed(word)
    for r in cands:
        if stressed(r["accented"]) == want:
            return r
    return cands[0] if len(cands) == 1 or sum(c in VOWELS for c in word) <= 1 else None


def verb(r):
    pres = [acc(r[f"presfut_{p}"]) for p in ("sg1", "sg2", "sg3", "pl1", "pl2", "pl3")]
    past = [acc(r[f"past_{g}"]) for g in ("m", "f", "n", "pl")]
    imp = [acc(r["imperative_sg"]), acc(r["imperative_pl"])]
    out = {"t": "v", "asp": r["aspect"][:4]}
    if r["bare"] == "быть":
        out["fut"] = ["бу́ду", "бу́дешь", "бу́дет", "бу́дем", "бу́дете", "бу́дут"]
    if any(pres) and len(set(pres)) > 1:
        out["pres"] = pres
    if any(past):
        out["past"] = past
    if any(imp) and acc(r["accented"]) not in NO_IMP:
        out["imp"] = imp
    return out if len(out) > 2 else None


def noun(r):
    if r["indeclinable"] == "1":
        return None
    sg = [acc(r[f"sg_{c}"]) for c in CASES]
    pl = [acc(r[f"pl_{c}"]) for c in CASES]
    if r["pl_only"] == "1" or not any(sg):
        sg = []
    if r["sg_only"] == "1" or not any(pl):
        pl = []
    return {"t": "n", "sg": sg, "pl": pl} if sg or pl else None


def adjective(r):
    cols = {g: [acc(r[f"decl_{g}_{c}"]) for c in CASES] for g in ("m", "n", "f", "pl")}
    if not any(cols["m"]):
        return None
    out = {"t": "a", **cols}
    short = [acc(r[f"short_{g}"]) for g in ("m", "f", "n", "pl")]
    if any(short):
        out["short"] = short
    if r.get("comparative"):
        out["comp"] = acc(r["comparative"])
    return out


def main(src):
    src = Path(src)
    V, N, A = (load(src / f"{n}.csv") for n in ("verbs", "nouns", "adjectives"))
    global PL
    PL = {}
    for rs in N.values():
        for r in rs:
            PL.setdefault(stressed(r["pl_nom"].split(",")[0].strip()), r)
    out, miss = {}, []
    for code in words.lessons():
        for k, (word, pos, _) in enumerate(exercises.lesson_vocab(code), 1):
            w, p = words.plain(word), words.plain(pos)
            head = re.split(r",\s*-", w)[0].strip()
            if " " in head or not head:
                continue
            kind = p.split()[0].rstrip(",") if p else ""
            if kind in ("impf.", "pf."):
                table, make = V, verb
            elif kind.startswith(("m", "f", "n", "pl.")) and "indecl" not in p and "按形容词" not in p:
                table, make = N, noun
            elif kind.startswith(("adj.", "pron.")) or "按形容词" in p or (kind == "num." and head.endswith(("ый", "ой", "ий"))):
                table, make = A, adjective
            else:
                continue
            r = pick(table.get(key(head), []), head)
            para = make(r) if r else None
            if not para and "按形容词" in p:                 # 形容词式名词：бу́лочная 等在名词表里
                r = pick(N.get(key(head), []), head)
                para = noun(r) if r else None
            if not para and kind.startswith("pl."):         # 只用复数的形式：лю́ди、де́ти 在单数原形的词条里
                r = PL.get(stressed(head))
                para = {"t": "n", "sg": [], "pl": noun(r)["pl"]} if r and noun(r) else None
            if para:
                out[f"{code}-{k:02d}"] = para
            elif kind != "pron.":
                miss.append(f"{code} {head} ({p})")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(OUT, len(out), "词有变化表；没找到", len(miss))
    for m in miss:
        print("  ", m)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
