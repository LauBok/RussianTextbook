#!/usr/bin/env python3
"""编写规范检查。

    python3 tools/check.py            # 检查 lessons/ 下全部课
    python3 tools/check.py L01 L02    # 只报告这几课（词表仍按课号顺序从头累积）

按课号顺序（P1–P8、L01–L100，然后第二、三、四册）读取每课生词表和专有名词，累积成已学词集合。
每课检查：

  词汇　课文、课前问题、语法例句、语音例句、练习里的俄语词是否在本课或此前各课的词表里：
        漏列　　　用了，但哪一课的词表都没有
        提前使用　用了，但要到后面某课才列为新词
        重复　　　本课列为新词的词，此前已有一课列过
  词表　本课新词数量；本课新词是否在课文、例句、练习中用到
  重音　多音节词是否标了重音，单音节词是否误标，重音符是否放在元音上
  ё　　 应写 ё 的地方是否写成了 е
  标记　俄语是否都放在 [...]{.ru} 或 lang="ru" 的块里
  练习　exercises/<课>.yaml 是否符合 exercises/FORMAT.md

词形还原用 pymorphy3（pip install pymorphy3）。有问题时退出码为 1。
"""
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

try:
    import pymorphy3
    MORPH = pymorphy3.MorphAnalyzer()
except ImportError:  # 没装 pymorphy3 时只认词表里出现过的词形
    MORPH = None

ROOT = Path(__file__).resolve().parent.parent
ACUTE = "́"
VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
CYR = re.compile(r"[А-Яа-яЁё]")
WORD = re.compile(r"-?[А-Яа-яЁё́]+(?:-[А-Яа-яЁё́]+)*-?")
HOMOGLYPH = re.compile(r"[А-Яа-яЁё][́]?[aeopcxyAEOPCXYKMTBH]|[aeopcxyAEOPCXYKMTBH][А-Яа-яЁё]")
# 单音节前置词、语气词在 не́ был、на́ пол、за́ город 一类组合里可以带重音
# 不带重音的多音节虚词：обо мне́、изо всех сил 这类前置词变体
UNSTRESSED_POLY = {"обо", "изо", "подо", "ото", "передо", "нибудь"}
STRESSABLE_MONO = {"не", "ни", "на", "за", "по", "под", "из", "от", "без", "до", "про", "над"}
BOOK_SIZE = {1: 108, 2: 72, 3: 60, 4: 40}
# 检查词汇的节；其余各节（生词表、注释、俄罗斯知识、作者简介、译文）只查书写
VOCAB_SECTIONS = ("课前问题", "课文", "选文", "语法", "语音", "练习")
EX_TYPES = {
    "picture_qa": {"req": ["image", "qword", "answer"], "ru": ["qword", "answer"]},
    "choice": {"req": ["stem", "options", "answer"], "ru": ["stem", "options", "answer"]},
    "fill": {"req": ["stem", "accept"], "opt": ["hint"], "ru": ["stem", "hint", "accept"]},
    "rewrite": {"req": ["cue", "accept"], "ru": ["cue", "accept"]},
    "translate": {"req": ["zh", "accept", "rubric"], "ru": ["accept"]},
    "open": {"req": ["prompt", "length", "model", "rubric", "notes"], "ru": ["model"]},
}
EX_ZH = {"task", "why", "zh", "rubric", "notes", "prompt"}
WHY_REQUIRED = {"picture_qa", "choice", "fill", "rewrite"}


# ---------- 课号 ----------

def book1_ids():
    return [f"P{i}" for i in range(1, 9)] + [f"L{i}" for i in range(1, 101)]


def all_ids():
    ids = [(1, x) for x in book1_ids()]
    for b in (2, 3, 4):
        ids += [(b, f"B{b}-L{i:02d}") for i in range(1, BOOK_SIZE[b] + 1)]
    return ids


def canon(name):
    """命令行和文件名 → 规划课号：L01 → L1，P01 → P1，B2-L1 → B2-L01。"""
    m = re.fullmatch(r"B([234])-L(\d+)", name)
    if m:
        return int(m.group(1)), f"B{m.group(1)}-L{int(m.group(2)):02d}"
    m = re.fullmatch(r"([PL])(\d+)", name)
    if m:
        return 1, f"{m.group(1)}{int(m.group(2))}"
    return None


# ---------- 文本工具 ----------

def nfc(s):
    return unicodedata.normalize("NFC", s)


def norm(w):
    """查词用：去重音、小写、ё → е。"""
    return nfc(w).replace(ACUTE, "").lower().replace("ё", "е")


def plain(w):
    return nfc(w).replace(ACUTE, "").lower()


def spans(text):
    """找出 [...]{...} 形式的行内元素，支持嵌套，返回 (起, 止, 内容起, 内容止, 属性)。"""
    out, stack, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            stack.append(i)
        elif c == "]" and stack:
            start = stack.pop()
            if i + 1 < n and text[i + 1] == "{":
                j = text.find("}", i + 1)
                if j > 0:
                    out.append((start, j + 1, start + 1, i, text[i + 2:j]))
                    i = j
        i += 1
    return out


def strip_markup(s):
    """去掉嵌套的 [..]{..} 外壳，只留文字。"""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\[([^\[\]]*)\]\{[^}]*\}", r"\1", s)
    return s


def ru_segments(text):
    """返回 [.ru] 元素里的俄语（最外层），以及去掉 .ru/.tr/.sp 元素后的剩余文本。"""
    segs, cut = [], []
    for s, e, cs, ce, attrs in spans(text):
        cls = re.findall(r"\.([\w-]+)", attrs)
        if "syl" in cls:
            cut.append((s, e))          # 语音课的音节练习，不是词
        elif "ru" in cls or 'lang="ru"' in attrs:
            if not any(a <= s and e <= b for a, b in cut):
                segs.append(strip_markup(text[cs:ce]))
                cut.append((s, e))
        elif "tr" in cls:
            cut.append((s, e))
    rest = list(text)
    for a, b in cut:
        for k in range(a, b):
            rest[k] = " "
    return segs, "".join(rest)


def tokens(s):
    """俄语词。以连字符开头或结尾的是词素（-ович、за-），返回时标出。"""
    prev = ""
    for m in WORD.finditer(nfc(s)):
        w = m.group(0)
        morpheme = w.startswith("-") or w.endswith("-")
        bare = w.strip("-")
        # не́ было、не́ были：重音移到 не 上，后面的词不再标重音
        if prev == "не" + ACUTE and norm(bare) in ("было", "были") and ACUTE not in bare:
            bare = bare[:2] + ACUTE + bare[2:]
        prev = bare.lower()
        yield bare, morpheme


# ---------- 读课文 ----------

def vocab_key_pos(cell):
    """重复判定用的词性标记：词性首标记，动词再加变位类型（I / II）。
    释义以“新义”开头的行返回 None，表示旧词的新义项。"""
    if len(cell) > 2 and strip_markup(cell[2]).strip().startswith("新义"):
        return None
    if len(cell) < 2:
        return ""
    parts = [p for p in re.split(r"[\s,(]", strip_markup(cell[1]).strip()) if p]
    if not parts:
        return ""
    if parts[0] in ("impf.", "pf.") and len(parts) > 1 and parts[1] in ("I", "II", "irr."):
        return f"{parts[0]} {parts[1]}"
    return parts[0]


class Lesson:
    def __init__(self, book, lid, path):
        self.book, self.id, self.path = book, lid, path
        raw = nfc(path.read_text(encoding="utf-8"))
        self.front, self.body, self.body_line = {}, raw, 1
        if raw.startswith("---\n"):
            end = raw.index("\n---\n", 4)
            self.front = yaml.safe_load(raw[4:end]) or {}
            self.body = raw[end + 5:]
            self.body_line = raw[:end + 5].count("\n") + 1
        self.lines = self.body.split("\n")
        self.vocab = []      # (词, 该行全部俄语, 行下标, 词性)
        self.names = []
        self._parse_blocks()

    def _parse_blocks(self):
        """逐行标出所在的节和是否处在 lang="ru" 的块里。"""
        self.meta = []
        section, fence = "", []
        for ln in self.lines:
            h = re.match(r"^##\s+(.+)", ln)
            if h:
                section = h.group(1).strip()
            f = re.match(r"^:::+\s*(.*)$", ln)
            if f:
                if f.group(1).strip():
                    fence.append(f.group(1).strip())
                    self.meta.append((section, list(fence), True))
                    continue
                if fence:
                    fence.pop()
                self.meta.append((section, list(fence), True))
                continue
            self.meta.append((section, list(fence), False))
        for i, ln in enumerate(self.lines):
            sec, fence, is_fence = self.meta[i]
            if is_fence:
                continue
            if fence and fence[-1].startswith("vocab") and ln.startswith("| ["):
                cell = ln.strip().strip("|").split("|")
                m = re.match(r"\s*\[(.+?)\]\{\.ru\}", cell[0])
                if m:
                    segs, _ = ru_segments(ln)
                    pos = vocab_key_pos(cell)
                    self.vocab.append((m.group(1).strip(), " ".join(segs), i, pos))
            if fence and fence[-1].startswith("names"):
                segs, _ = ru_segments(ln)
                self.names += segs

    def lineno(self, i):
        return self.body_line + i

    def ru_lines(self):
        """逐行给出 (行号, 节, 俄语片段列表, 非俄语剩余文本)。"""
        for i, ln in enumerate(self.lines):
            sec, fence, is_fence = self.meta[i]
            if is_fence or ln.lstrip().startswith("<!--"):
                continue
            in_ru = any('lang="ru"' in f for f in fence)
            if in_ru:
                # 对话块里说话人用 .sp 标，其余整行都是俄语
                segs = [strip_markup(ln)]
                rest = ""
            else:
                segs, rest = ru_segments(ln)
            yield i, sec, segs, rest


# ---------- 词表 ----------

class Lexicon:
    """一组词表的全部词形（norm → 带 ё、不带重音的拼写）。"""

    def __init__(self):
        self.forms = {}

    def add(self, text):
        for w, morpheme in tokens(text):
            if not morpheme:
                self.forms.setdefault(norm(w), set()).add(plain(w))

    def update(self, other):
        for k, v in other.forms.items():
            self.forms.setdefault(k, set()).update(v)

    def knows(self, w):
        k = norm(w)
        if k in self.forms:
            return True
        if MORPH is None:
            return False
        for nf, lex in analyses(k):
            if nf in self.forms or any(f in self.forms for f in lex):
                return True
        return False


@lru_cache(maxsize=None)
def analyses(k):
    """(原形, 词形集合) 列表，都已 norm。"""
    out = []
    for p in MORPH.parse(k):
        try:
            lex = frozenset(norm(f.word) for f in p.lexeme)
        except Exception:
            lex = frozenset()
        out.append((norm(p.normal_form), lex))
    return out


@lru_cache(maxsize=None)
def yo_spellings(k):
    """词典里与 k 同形（ё 当 е）的已知写法。"""
    if MORPH is None:
        return frozenset()
    return frozenset(p.word for p in MORPH.parse(k) if p.is_known)


def yo_problem(w, lex):
    """w 写了 е 而应写 ё 时返回正确写法。"""
    p = plain(w)
    if "е" not in p:
        return None
    # 重音位置：去掉组合符后第几个字母带重音
    stressed, idx = set(), 0
    for ch in nfc(w).lower():
        if ch == ACUTE:
            stressed.add(idx - 1)
        else:
            idx += 1
    cands = set(yo_spellings(p.replace("ё", "е")))
    cands |= lex.forms.get(norm(w), set())
    ok = []
    for c in cands:
        if len(c) != len(p):
            continue
        yo = [i for i, ch in enumerate(c) if ch == "ё"]
        if any(p[i] != "е" for i in yo):
            continue
        if stressed and yo and not all(i in stressed for i in yo):
            continue
        ok.append(c)
    if ok and all("ё" in c and c != p for c in ok):
        return sorted(ok)[0]
    return None


# ---------- 单词书写检查 ----------

def check_word(w, morpheme, need_stress):
    """返回这个词的书写问题。"""
    probs = []
    low = nfc(w)
    if HOMOGLYPH.search(low):
        probs.append(("书写", f"{w}：混入了拉丁字母"))
    if morpheme:
        return probs
    vowels = sum(1 for ch in low if ch in VOWELS)
    acutes = low.count(ACUTE)
    for i, ch in enumerate(low):
        if ch == ACUTE and (i == 0 or low[i - 1] not in VOWELS):
            probs.append(("重音", f"{w}：重音符没有放在元音上"))
        if ch == ACUTE and i > 0 and low[i - 1] in "ёЁ":
            probs.append(("重音", f"{w}：ё 本身表示重音，不再加重音符"))
    if not need_stress:
        return probs
    has_yo = any(ch in "ёЁ" for ch in low)
    if vowels >= 2 and acutes == 0 and not has_yo and norm(w) not in UNSTRESSED_POLY:
        probs.append(("重音", f"{w}：多音节词没有标重音"))
    if vowels == 1 and acutes and norm(w) not in STRESSABLE_MONO:
        probs.append(("重音", f"{w}：单音节词不标重音"))
    if acutes > 1 and "-" not in w:
        probs.append(("重音", f"{w}：标了 {acutes} 个重音"))
    return probs


# ---------- 练习 YAML ----------

def ru_strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from ru_strings(x)
    elif isinstance(v, dict):
        for x in v.values():
            yield from ru_strings(x)


def check_exercise_yaml(stem, path):
    """返回 (问题列表, [(位置, 俄语字符串)], [(位置, 中文字符串)])。"""
    probs, ru, zh = [], [], []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return [("练习", f"YAML 解析失败：{e}")], ru, zh
    if not isinstance(data, dict):
        return [("练习", "顶层应为映射")], ru, zh
    if data.get("lesson") != stem:
        probs.append(("练习", f"lesson 应为 {stem}，实为 {data.get('lesson')!r}"))
    exs = data.get("exercises")
    if not isinstance(exs, list) or not exs:
        return probs + [("练习", "缺少 exercises 列表")], ru, zh
    for k in set(data) - {"lesson", "exercises", "grammar", "heading", "intro"}:
        probs.append(("练习", f"顶层多出字段 {k}"))
    for k in ("grammar", "heading", "intro"):
        if isinstance(data.get(k), str):
            zh.append((k, data[k]))
    seen = set()
    img_dir = ROOT / "img" / stem
    for n, ex in enumerate(exs, 1):
        where = f"第 {n} 题"
        if not isinstance(ex, dict):
            probs.append(("练习", f"{where}：应为映射"))
            continue
        eid = ex.get("id")
        where = f"{eid or f'第 {n} 题'}"
        if not eid:
            probs.append(("练习", f"{where}：缺少 id"))
        elif eid in seen:
            probs.append(("练习", f"{where}：id 重复"))
        seen.add(eid)
        t = ex.get("type")
        if t not in EX_TYPES:
            probs.append(("练习", f"{where}：未知题型 {t!r}"))
            continue
        spec = EX_TYPES[t]
        if not isinstance(ex.get("task"), str) or not ex.get("task"):
            probs.append(("练习", f"{where}：缺少 task"))
        if t in WHY_REQUIRED and not ex.get("why"):
            probs.append(("练习", f"{where}：封闭题缺少解析 why"))
        allowed = {"id", "type", "task", "why", "items", "example", "placeholder"}
        for k in set(ex) - allowed:
            probs.append(("练习", f"{where}：多出字段 {k}"))
        for k in ("task", "why"):
            if isinstance(ex.get(k), str):
                zh.append((f"{where}.{k}", ex[k]))
        items = ex.get("items")
        if not isinstance(items, list) or not items:
            probs.append(("练习", f"{where}：缺少 items"))
            continue
        exm = ex.get("example")
        if t == "picture_qa":
            if exm is not None and not (isinstance(exm, int) and 1 <= exm <= len(items)):
                probs.append(("练习", f"{where}：example 应为 1–{len(items)} 的小题序号"))
        elif t == "rewrite":
            if exm is not None:
                if not (isinstance(exm, dict) and exm.get("cue") and exm.get("answer")):
                    probs.append(("练习", f"{where}：example 应有 cue 和 answer"))
                else:
                    ru += [(f"{where}.example", exm["cue"]), (f"{where}.example", exm["answer"])]
        elif exm is not None:
            probs.append(("练习", f"{where}：{t} 题型没有 example 字段"))
        for i, it in enumerate(items, 1):
            iw = f"{where}.{i}"
            if not isinstance(it, dict):
                probs.append(("练习", f"{iw}：小题应为映射"))
                continue
            for k in spec["req"]:
                if it.get(k) in (None, "", []):
                    probs.append(("练习", f"{iw}：缺少 {k}"))
            for k in set(it) - set(spec["req"]) - set(spec.get("opt", [])):
                probs.append(("练习", f"{iw}：多出字段 {k}"))
            for k in ("answer", "accept", "rubric", "options"):
                if k in it and k in spec["req"] and not (t == "choice" and k == "answer"):
                    if not isinstance(it[k], list):
                        probs.append(("练习", f"{iw}：{k} 应为列表"))
            if t in ("choice", "fill") and "___" not in str(it.get("stem", "")):
                probs.append(("练习", f"{iw}：stem 里没有空位 ___"))
            if t == "choice" and isinstance(it.get("options"), list) and it.get("answer") not in it["options"]:
                probs.append(("练习", f"{iw}：answer 不在 options 里"))
            if t == "picture_qa":
                if it.get("qword") not in ("Кто", "Что"):
                    probs.append(("练习", f"{iw}：qword 应为 Кто 或 Что"))
                if it.get("image") and not (img_dir / it["image"]).exists():
                    probs.append(("练习", f"{iw}：图片 img/{stem}/{it['image']} 不存在"))
            if t == "open" and not re.fullmatch(r"\d+\s*[–-]\s*\d+", str(it.get("length", ""))):
                probs.append(("练习", f"{iw}：length 应写成字数范围，如 80–120"))
            for k in spec["ru"]:
                for s in ru_strings(it.get(k)):
                    ru.append((iw, s))
            # 不加引号的流式列表会在逗号处把一句话拆开：整句答案都应以标点结尾
            if t in ("translate", "rewrite", "picture_qa"):
                for k in ("accept", "answer"):
                    for x in it.get(k) or []:
                        if isinstance(x, str) and re.match(r"[а-яё]", x.strip()):
                            probs.append(("练习", f"{iw}：{k} 里的 {x!r} 以小写字母开头，可能是 YAML 没加引号被逗号拆开了"))
            for k in EX_ZH & set(it):
                for s in ru_strings(it[k]):
                    zh.append((f"{iw}.{k}", s))
    return probs, ru, zh


# ---------- 课文缩略图 ----------

def check_scene(stem):
    """img/<课>/scene.svg：240×160 横幅、线条风格（#2b2b2b，线宽 3），图里不放文字。"""
    path = ROOT / "img" / stem / "scene.svg"
    if not path.exists():
        return []
    svg = path.read_text(encoding="utf-8")
    probs = []
    if 'viewBox="0 0 240 160"' not in svg:
        probs.append("scene.svg 的 viewBox 应为 0 0 240 160")
    if re.search(r"<text\b", svg):
        probs.append("scene.svg 里不放文字")
    if 'stroke="#2b2b2b"' not in svg or 'stroke-width="3"' not in svg:
        probs.append("scene.svg 应与其他插图同一线条风格：stroke=\"#2b2b2b\"、stroke-width=\"3\"")
    if re.search(r'(fill|stroke)="(?!none|#2b2b2b)[^"]*"', svg):
        probs.append("scene.svg 只用 #2b2b2b 一种颜色")
    lib_path = ROOT / "img" / "characters.svg"
    lib = set(re.findall(r'<symbol\b[^>]*\bid="([^"]+)"', lib_path.read_text(encoding="utf-8"))) if lib_path.exists() else set()
    for ref in re.findall(r'<use\b[^>]*\bhref="#([^"]+)"', svg):
        if ref not in lib:
            probs.append(f"scene.svg 引用的人物 #{ref} 不在 img/characters.svg 里")
    return probs


# ---------- 主流程 ----------

def order_key(book, lid):
    m = re.search(r"([PL])(\d+)$", lid)
    return book, m.group(1) == "L", int(m.group(2))


def lesson_files():
    found = []
    for p in sorted((ROOT / "lessons").glob("*.md")):
        if p.stem.endswith("-答案"):
            continue
        c = canon(p.stem)
        if c:
            found.append((c, p))
    found.sort(key=lambda x: order_key(*x[0]))
    return found


def lesson_lexicon(les):
    lex = Lexicon()
    for w, row, _, _ in les.vocab:
        lex.add(w + " " + row)
    for n in les.names:
        lex.add(n)
    return lex


class Checker:
    def __init__(self, lessons):
        self.lessons = lessons
        self.own = [lesson_lexicon(l) for l in lessons]
        self.everything = Lexicon()        # 所有课的词，用来查 ё
        for lx in self.own:
            self.everything.update(lx)
        self.first = {}                    # (norm(词条), 词性) → 第一次列入的课
        self.pos_of = {}

    def where_listed(self, w, k):
        """w 不在已学词里时：返回后面第一次列入它的课，没有则 None。"""
        for j in range(k + 1, len(self.lessons)):
            if self.own[j].knows(w):
                return self.lessons[j].path.stem
        return None

    def check_vocab_use(self, w, where, k, known, agg, used):
        """词汇问题按词归并：同一个词在一课里只报一次，列出全部位置。"""
        used.add(norm(w))
        if len(norm(w)) < 2 or known.knows(w):
            return
        key = norm(w)
        if key not in agg:
            later = self.where_listed(w, k)
            agg[key] = [w, later, []]
        if where not in agg[key][2]:
            agg[key][2].append(where)

    def check_lesson(self, k, known):
        les = self.lessons[k]
        out = []
        stem = les.path.stem
        need_stress_text = les.book <= 2

        # 重复
        for w, _, i, pos in les.vocab:
            if pos is None:          # “新义：……”：旧词的新义项，不算重复
                continue
            key = (nfc(w).lower(), pos)
            if key in self.first and self.first[key] != stem:
                out.append((les.lineno(i), "重复", f"{w}：{self.first[key]} 已列为新词"))
            else:
                self.first.setdefault(key, stem)

        used, agg = set(), {}
        for i, sec, segs, rest in les.ru_lines():
            ln = les.lineno(i)
            if CYR.search(re.sub(r"<!--.*?-->", "", rest)):
                bare = sorted(set(WORD.findall(nfc(rest))))
                out.append((ln, "标记", f"俄语没有放在 {{.ru}} 里：{'、'.join(bare)}"))
            stress = need_stress_text or sec.startswith("生词")
            vocab_sec = any(sec.startswith(s) for s in VOCAB_SECTIONS)
            for seg in segs:
                for w, morpheme in tokens(seg):
                    for cat, msg in check_word(w, morpheme, stress):
                        out.append((ln, cat, msg))
                    if morpheme:
                        continue
                    y = yo_problem(w, self.everything)
                    if y:
                        out.append((ln, "ё", f"{w}：应写作 {y}"))
                    if vocab_sec:
                        self.check_vocab_use(w, ln, k, known, agg, used)

        # 练习
        ex_path = ROOT / "exercises" / f"{stem}.yaml"
        has_marker = "<!-- EXERCISES -->" in les.body
        if ex_path.exists():
            if not has_marker:
                out.append((None, "练习", "课文里缺少 <!-- EXERCISES --> 标记"))
            probs, ru, zh = check_exercise_yaml(stem, ex_path)
            out += [(None, c, m) for c, m in probs]
            for where, s in ru:
                for w, morpheme in tokens(s):
                    for cat, msg in check_word(w, morpheme, need_stress_text):
                        out.append((f"练习 {where}", cat, msg))
                    if morpheme:
                        continue
                    y = yo_problem(w, self.everything)
                    if y:
                        out.append((f"练习 {where}", "ё", f"{w}：应写作 {y}"))
                    self.check_vocab_use(w, f"练习 {where}", k, known, agg, used)
            for where, s in zh:
                segs, rest = ru_segments(s)
                if CYR.search(rest):
                    bare = sorted(set(WORD.findall(nfc(rest))))
                    out.append((f"练习 {where}", "标记", f"俄语没有放在 {{.ru}} 里：{'、'.join(bare)}"))
                for seg in segs:
                    for w, morpheme in tokens(seg):
                        for cat, msg in check_word(w, morpheme, need_stress_text):
                            out.append((f"练习 {where}", cat, msg))
        else:
            if any(sec.startswith("练习") for sec, _, _ in les.meta):
                out.append((None, "练习", f"练习写在 Markdown 里，应移到 exercises/{stem}.yaml"))
            elif not has_marker:
                out.append((None, "练习", "没有练习：缺少 exercises 数据和 <!-- EXERCISES --> 标记"))
            else:
                out.append((None, "练习", f"缺少 exercises/{stem}.yaml"))
        out += [(None, "插图", m) for m in check_scene(stem)]
        answer_md = les.path.with_name(f"{stem}-答案.md")
        if answer_md.exists():
            out.append((None, "练习", f"{answer_md.name} 应由 exercises/{stem}.yaml 生成，不手写"))

        for w, later, places in agg.values():
            locs = "、".join(f"第 {p} 行" if isinstance(p, int) else p for p in places)
            if later:
                out.append((None, "提前使用", f"{w}：到 {later} 才列为新词（{locs}）"))
            else:
                out.append((None, "漏列", f"{w}：没有列入任何一课的词表（{locs}）"))

        # 本课新词是否用到
        for w, _, i, _ in les.vocab:
            parts = [norm(t) for t, m in tokens(w) if not m]
            if parts and not any(word_used(p, used) for p in parts):
                out.append((les.lineno(i), "词表", f"{w}：课文、例句和练习里都没有用到"))
        return out


def word_used(k, used):
    """词条 k 的某个词形是否出现在 used 里。"""
    if k in used:
        return True
    if MORPH is None:
        return False
    return any(nf == k or k in lex for u in used for nf, lex in analyses(u))


def main(argv):
    wanted = {canon(a) for a in argv}
    if None in wanted:
        sys.exit(f"无法识别的课号：{' '.join(a for a in argv if not canon(a))}")
    if MORPH is None:
        print("提示：没有安装 pymorphy3，变化后的词形只能按词表原样匹配，会多报词汇问题。\n")
    files = lesson_files()
    lessons = [Lesson(b, lid, p) for (b, lid), p in files]
    have = {c for c, _ in files}
    checker = Checker(lessons)
    known = Lexicon()
    total = 0
    for k, les in enumerate(lessons):
        known.update(checker.own[k])
        probs = checker.check_lesson(k, known)
        if wanted and (les.book, les.id) not in wanted:
            continue
        missing = [lid for b, lid in all_ids()
                   if order_key(b, lid) < order_key(les.book, les.id) and (b, lid) not in have]
        print(f"== {les.path.stem}（新词 {len(les.vocab)} 个，{len(probs)} 个问题）")
        if missing:
            print(f"  [提示] 此前有 {len(missing)} 课尚未编写，漏列和提前使用只依据已编写的课判断")
        for where, cat, msg in probs:
            loc = "" if where is None else (f"第 {where} 行 " if isinstance(where, int) else f"{where}：")
            print(f"  {loc}[{cat}] {msg}")
        print()
        total += len(probs)
    print(f"共 {total} 个问题")
    return total


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1:]) else 0)
