#!/usr/bin/env python3
"""第一册词汇整理。

    python3 tools/vocab.py consolidate [--apply]   每个生词只在它第一次用到的课里列出
    python3 tools/vocab.py fill [--apply]          check.py 报“漏列”的词：从 git 历史里找回原来的生词行，
                                                   补进第一次用到它的课
不加 --apply 只报告。

规则：
- 只处理第一册 L 课（语音课的示例词视为已学，L 课里再列的按普通生词处理）。
- 词条按 (去重音小写词形, 词性首标记) 归组；同组在多课列出时，只保留到“第一次用到”的那课。
- 第一次用到的课早于列出的课：把行移到第一次用到的课。
- 句型（带 …）、词形列表（带逗号）、同形词、受语法进度限制的词（SKIP）不移动。
- 专有名词不自动改。
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check as C  # noqa: E402


# 受语法进度限制的词：提前出现是课文问题，应改课文，不把词挪前（带重音小写词形）
SKIP = {"в", "о", "у", "с", "к", "по", "до", "ли", "бы", "чем", "лу́чше", "ху́же", "бо́льше", "ме́ньше",
        "краси́вее", "вкусне́е", "не́ было", "быть", "мочь", "кого́", "мной", "ско́лько с меня́?", "стать",
        "пятьдеся́т", "се́мьдесят", "сто́ить", "две", "кото́рый, -ая, -ое, -ые"}


def pos_head(cell):
    return re.split(r"[\s,(]", C.strip_markup(cell).strip())[0]


def lesson_order():
    files = [(c, p) for c, p in C.lesson_files()
             if c[0] == 1 and c[1].startswith("L") and int(c[1][1:]) % 10 != 0]
    return files


def used_tokens(les):
    """本课课文、例句、练习里用到的词（norm）。"""
    out = set()
    for i, sec, segs, rest in les.ru_lines():
        if not C.is_vocab_section(sec):
            continue
        for seg in segs:
            for w, m in C.tokens(seg):
                if not m:
                    out.add(C.norm(w))
    ex = ROOT / "exercises" / f"{les.path.stem}.yaml"
    if ex.exists():
        _, ru, _ = C.check_exercise_yaml(les.path.stem, ex)
        for _, s in ru:
            for w, m in C.tokens(s):
                if not m:
                    out.add(C.norm(w))
    return out


def lesson_text(les):
    """本课课文、例句、练习的俄语（norm 后），用来匹配短语。"""
    out = []
    for i, sec, segs, rest in les.ru_lines():
        if C.is_vocab_section(sec):
            out += [C.norm(x) for x in segs]
    ex = ROOT / "exercises" / f"{les.path.stem}.yaml"
    if ex.exists():
        _, ru, _ = C.check_exercise_yaml(les.path.stem, ex)
        out += [C.norm(s) for _, s in ru]
    return out


def token_keys(t):
    """词形 t 可能对应的词条形式：精确形式与原形优先，否则用整个词形变化表。"""
    strong = {t}
    weak = set()
    if C.MORPH:
        for nf, lex in C.analyses(t):
            strong.add(nf)
            weak |= lex
    return strong, weak


def parse_vocab(les):
    rows = []
    for w, row, i, _ in les.vocab:
        line = les.lines[i]
        cells = line.strip().strip("|").split("|")
        first_cells = C.strip_markup(re.sub(r"\[\[.*?\]\]\{\.tr\}", "", cells[0]))   # 注音不参与匹配
        rows.append({"word": w, "line": line, "i": i, "pos": C.vocab_key_pos(cells),
                     "forms": {C.norm(t) for t, m in C.tokens(first_cells) if not m},
                     "head": {C.norm(t) for t, m in C.tokens(w) if not m}})
    return rows


NAME_ITEM = re.compile(r"(\[[^\]]+\]\{\.ru\})\s*([^　\[]*)")


def parse_names(les):
    out = []
    for i, ln in enumerate(les.lines):
        sec, fence, is_fence = les.meta[i]
        if fence and fence[-1].startswith("names") and not is_fence:
            body = ln.split("：", 1)[1] if "：" in ln else ln
            for m in NAME_ITEM.finditer(body):
                text = C.strip_markup(m.group(1))
                out.append({"item": (m.group(1) + " " + m.group(2).strip()).strip(), "i": i,
                            "forms": {C.norm(t) for t, mm in C.tokens(text) if not mm}, "text": text})
    return out


def main(apply):
    files = lesson_order()
    lessons = [C.Lesson(b, lid, p) for (b, lid), p in files]
    stems = [l.path.stem for l in lessons]
    used = [used_tokens(l) for l in lessons]
    texts = [" " + " ".join(lesson_text(l)) + " " for l in lessons]
    exact_heads = set()
    for (b, lid), p in C.lesson_files():
        if b == 1:
            for w, _, _, _ in C.Lesson(b, lid, p).vocab:
                hs = [C.norm(t) for t, m in C.tokens(w) if not m]
                if len(hs) == 1:
                    exact_heads.add(hs[0])

    # 词条归组
    groups = defaultdict(list)      # key → [(课序, 行)]
    keep_new_sense = defaultdict(list)
    for k, les in enumerate(lessons):
        for r in parse_vocab(les):
            if r["pos"] is None:            # 新义行留在原课
                keep_new_sense[k].append(r["line"])
                continue
            key = (C.nfc(r["word"]).lower(), r["pos"])
            groups[key].append((k, r))
    names = defaultdict(list)
    for k, les in enumerate(lessons):
        for n in parse_names(les):
            names[C.norm(n["text"])].append((k, n))

    # 索引：词形 → 词条组
    head_index, form_index = defaultdict(set), defaultdict(set)
    phrases = {}
    fixed = set()
    for key, lst in groups.items():
        w0 = C.strip_markup(lst[0][1]["word"])
        if "…" in w0 or ("," in w0 and len(lst[0][1]["head"]) > 1):   # 句型、词形列表：不自动移动
            fixed.add(key)
            continue
        if len(lst[0][1]["head"]) > 1:      # 多个实词组成的短语按整体匹配
            phrases[key] = [f for f in (C.norm(x).strip(" ,.!?") for x in re.split(r"[…,]", C.strip_markup(lst[0][1]["word"]))) if f]
            continue
        for _, r in lst:
            for f in r["head"]:
                head_index[f].add(key)
            for f in r["forms"]:
                form_index[f].add(key)
    name_index = defaultdict(set)
    for key, lst in names.items():
        for _, n in lst:
            for f in n["forms"]:
                name_index[f].add(key)

    first_use = {}
    first_name = {}
    unlisted = defaultdict(set)
    for k, toks in enumerate(used):
        for t in toks:
            strong, weak = token_keys(t)
            hit = set()
            if t in exact_heads:            # 本身就是词条（如 хорошо́），不再按原形归到别的词
                strong = {t}
            for f in strong:
                hit |= head_index.get(f, set()) | form_index.get(f, set())
            if not hit and t not in exact_heads:
                for f in weak:
                    hit |= head_index.get(f, set())
            nhit = set()
            for f in strong:
                nhit |= name_index.get(f, set())
            for key in hit:
                first_use.setdefault(key, k)
            for key in nhit:
                first_name.setdefault(key, k)
            if not hit and not nhit and len(t) > 1:
                # 语音课示例词、此前的词形等由 check.py 判断；这里只记录完全找不到的
                unlisted[k].add(t)

    for key, frags in phrases.items():
        for k, txt in enumerate(texts):
            if frags and all(re.search(r"(?<![а-я-])" + re.escape(f) + r"(?![а-я-])", txt) for f in frags):
                first_use.setdefault(key, k)
                break

    # 同形词（同一词形对应多个词条组）只靠文本分不清，不往前移
    by_head = defaultdict(set)
    for key in groups:
        by_head[C.norm(key[0])].add(key)
    homograph = {k for ks in by_head.values() if len(ks) > 1 for k in ks}

    plan_rows = defaultdict(list)   # 课序 → 应列的行
    moves = []
    for key, lst in groups.items():
        lst.sort(key=lambda x: x[0])
        first_listed = lst[0][0]
        if key in fixed or key in homograph or key[0] in SKIP:
            target = first_listed
        else:
            target = min(first_use.get(key, first_listed), first_listed)
        row = next((r for k, r in lst if k == target), lst[0][1])
        plan_rows[target].append(row["line"])
        listed = sorted({k for k, _ in lst})
        if listed != [target]:
            moves.append((key[0], [stems[k] for k in listed], stems[target]))
    for k, lst in keep_new_sense.items():
        plan_rows[k] += lst
    plan_names = defaultdict(list)
    for key, lst in names.items():
        lst.sort(key=lambda x: x[0])
        target = first_name.get(key, lst[0][0])
        plan_names[target].append(lst[0][1]["item"])

    print(f"移动/去重 {len(moves)} 个词条")
    for w, frm, to in moves[:4000]:
        print(f"  {w}: {', '.join(frm)} → {to}")
    print()
    for k, s in enumerate(stems):
        print(f"{s}: {len(plan_rows[k])} 词")
    if apply:
        for k, les in enumerate(lessons):
            rewrite(les, plan_rows[k], None)
        print("已改写")


def rewrite(les, rows, names):
    text = les.path.read_text(encoding="utf-8")
    lines = text.split("\n")
    off = les.body_line - 1
    # 原有行的顺序：先保留本课原有的行（原顺序），再追加移来的行
    existing = [ln for ln in (les.lines[r["i"]] for r in parse_vocab(les)) if ln in rows]
    added = [ln for ln in rows if ln not in existing]
    new_rows = existing + added
    vocab_idx = [r["i"] for r in parse_vocab(les)]
    # 找 vocab 块
    start = end = None
    for i, ln in enumerate(les.lines):
        if re.match(r"^:::\s*vocab", ln):
            start = i
        elif start is not None and end is None and re.match(r"^:::\s*$", ln):
            end = i
            break
    if start is None:
        raise SystemExit(f"{les.path.name} 没有 vocab 块")
    head = [les.lines[i] for i in range(start + 1, end)
            if les.lines[i].startswith("|") and i not in vocab_idx][:2]
    block = [les.lines[start]] + head + new_rows + [les.lines[end]]
    body = les.lines[:start] + block + les.lines[end + 1:]
    # 专有名词
    nstart = nend = None
    for i, ln in enumerate(body):
        if re.match(r"^:::\s*names", ln):
            nstart = i
        elif nstart is not None and nend is None and re.match(r"^:::\s*$", ln):
            nend = i
            break
    if names is None:
        pass
    elif names:
        nline = "专有名词：" + "　".join(names)
        if nstart is not None:
            body = body[:nstart + 1] + [nline] + body[nend:]
        else:
            vend = start + len(block) - 1
            body = body[:vend + 1] + ["", "::: names", nline, ":::"] + body[vend + 1:]
    elif nstart is not None:
        cut_to = nend + 1
        if cut_to < len(body) and body[cut_to] == "" and nstart > 0 and body[nstart - 1] == "":
            cut_to += 1
        body = body[:nstart] + body[cut_to:]
    les.path.write_text("\n".join(lines[:off] + body), encoding="utf-8")


# ---------- 补漏列 ----------

def history_rows():
    """git 历史里各课生词表出现过的行：norm(词头) → 行（越新越优先）。"""
    import subprocess
    commits = subprocess.run(["git", "log", "--format=%H", "--", "lessons"], capture_output=True,
                             text=True, cwd=ROOT).stdout.split()
    bank = {}
    for commit in reversed(commits[:60]):          # 从旧到新，新的覆盖旧的
        names = subprocess.run(["git", "ls-tree", "--name-only", commit, "lessons/"], capture_output=True,
                               text=True, cwd=ROOT).stdout.split()
        for name in names:
            if not re.fullmatch(r"lessons/L\d+\.md", name):
                continue
            text = subprocess.run(["git", "show", f"{commit}:{name}"], capture_output=True,
                                  text=True, cwd=ROOT).stdout
            m = re.search(r"^::: vocab\s*\n(.*?)^:::\s*$", text, re.S | re.M)
            if not m:
                continue
            for ln in m.group(1).splitlines():
                h = re.match(r"\|\s*\[(.+?)\]\{\.ru\}", ln)
                if h and ln.startswith("| ["):
                    bank[C.norm(C.strip_markup(h.group(1)))] = ln
    return bank


def unlisted_words():
    """跑 check.py，取每个漏列词第一次被报的课：[(课号, 词形)]。"""
    import subprocess
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "check.py")], capture_output=True,
                         text=True, cwd=ROOT).stdout
    seen, res, lesson = set(), [], None
    for ln in out.splitlines():
        m = re.match(r"== (\S+)（", ln)
        if m:
            lesson = m.group(1)
            continue
        m = re.match(r"\s+\[漏列\] (\S+?)：", ln)
        if m and lesson and re.fullmatch(r"L\d+", lesson):
            w = m.group(1)
            if C.norm(w) not in seen:
                seen.add(C.norm(w))
                res.append((lesson, w))
    return res


def find_row(w, bank):
    k = C.norm(w)
    if k in bank:
        return bank[k]
    if C.MORPH:
        for nf, _ in C.analyses(k):
            if nf in bank:
                return bank[nf]
    return None


def fill(apply):
    bank = history_rows()
    todo, missing = defaultdict(list), []
    for lesson, w in unlisted_words():
        row = find_row(w, bank)
        if row and row not in todo[lesson]:
            todo[lesson].append(row)
        elif not row:
            missing.append((lesson, w))
    for lesson, rows in todo.items():
        print(f"{lesson}: 补 {len(rows)} 行")
        for r in rows:
            print("   ", r[:90])
    if missing:
        print("历史里找不到、需要人工补的：", "、".join(f"{w}（{l}）" for l, w in missing))
    if apply:
        for lesson, rows in todo.items():
            path = ROOT / "lessons" / f"{lesson}.md"
            text = path.read_text(encoding="utf-8")
            m = re.search(r"(^::: vocab\s*\n.*?)(^:::\s*$)", text, re.S | re.M)
            new = m.group(1).rstrip("\n") + "\n" + "\n".join(rows) + "\n"
            path.write_text(text[:m.start()] + new + text[m.start(2):], encoding="utf-8")
        print("已补行")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "consolidate":
        main("--apply" in sys.argv)
    elif cmd == "fill":
        fill("--apply" in sys.argv)
    else:
        sys.exit(__doc__)
