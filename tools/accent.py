#!/usr/bin/env python3
"""朗读稿：把课文整理成给 tools/tts.py 朗读的文本，每课一份 tts/text/<课号>.txt。

    python tools/accent.py B3-L05 B4-L09     # 生成或更新这几课
    python tools/accent.py --book 3          # 整册（第一、二册只给有数字、缩写的课生成）
    python tools/accent.py --todo            # 列出还有待定词的朗读稿
    python tools/accent.py --check           # 核对朗读稿：待定词是否填完、文字是否和课文一致

第三册起课文不标重音，模型自己猜容易读错，所以朗读前在朗读稿里给多音节词补上重音（课文本身不改）：
  - 重音词典（tools/data/stress.tsv.gz）里这个词形只有一种重音的，直接标上；
  - 词典没收、而全书生词表和第一、二册里标过、只有一种重音的，照书上标；
  - 同形异义（词典里有几种重音）、词典和书都没有的词，写成待定：{стоит?сто́ит|стои́т}、{Третьякова?}；
  - 数字、罗马数字、拉丁字母和大写缩写也写成待定，如 {1832?}、{XII?}、{МГУ?}，要改写成读出来的词。
待定词由人按上下文定下来：把整个 {…} 换成带重音的读法，如 {году?го́ду|году́} → году́，
{1832?} → ты́сяча восемьсо́т три́дцать второ́м。

朗读稿每段以“@说话人 校验码”开头，校验码由课文原段算出。课文改了以后重新运行本脚本：
没改的段保留已经定好的读法，改过的段重新生成。tts.py 遇到待定词没填完或者朗读稿过期的课会停下来。
"""
import argparse
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stress  # noqa: E402
import tts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEXT = ROOT / "tts" / "text"
ACUTE = "́"
WORD = re.compile(r"[А-Яа-яЁёA-Za-zÀ-ɏ0-9́]+(?:-[А-Яа-яЁёA-Za-zÀ-ɏ0-9́]+)*")
TODO = re.compile(r"\{[^{}]*\?[^{}]*\}")
# 要整体改写成词的记号：数字连同其中的标点（11.10、1–4、30 000、0,1 %）、%、№、+、常用缩写、姓名首字母
ABBR = r"гг|г|вв|в|кв|руб|коп|мин|сек|ч|м|км|см|кг|ул|пр|тел|комн|д|стр|тыс|млн|млрд|им|янв|февр|апр|авг|сент|окт|нояб|дек|т\. ?[дпе]|и др|и пр"
SPECIAL = re.compile(
    r"[+№§]?\s?\d+(?:[  ]\d{3})*(?:[.,:/–—-]\d+)*(?:-[а-я]{1,4}\.?)?(?:[  ]?%)?|[%№§+]"
    r"|[A-Za-zÀ-ɏ]+(?:\.[A-Za-zÀ-ɏ]+)*\.?"
    r"|(?<![А-Яа-яЁё́])кв\. ?м\b\.?"
    r"|(?<![А-Яа-яЁё́])(?:" + ABBR + r")\.(?=[\s,;:)»]|$)"
    r"|(?<![А-Яа-яЁё́])[А-ЗЙ-ЮЁ]\.(?=\s?[А-ЯЁ»”)]|\s*\n|\s*$)")
RESIDUE = re.compile(r"[0-9A-Za-zÀ-ɏ%№§+]|[а-яё́]\.[а-яё]|(?<![А-Яа-яЁё́])(?:" + ABBR + r")\.(?=[\s,;:)»]|$)", re.I)


# 词典里有几种重音、但另一种读法极少见（古旧、专名或罕用词形）的词，直接取常用读法
DEFAULTS = """и́ли уже́ по́сле оди́н того́ пото́м пе́ред мину́т тому́ киломе́тров вода́ са́мое ме́тров ви́дно на́чал
недалеко́ со́рок писа́ть писа́л писа́ли написа́ть ма́ло второ́й больши́х больши́е больша́я большу́ю языко́в ина́че
круго́м а́вгуста удало́сь стро́ить стро́или на́шей гото́в одновре́менно то́тчас доро́га доро́ги го́сти со́чи по́ле
слу́чай происхо́дит выхо́дит основно́м подня́лся поги́б глаза́ темно́ должно́ ни́же Ки́ев Макси́м Гера́сим""".split()


def digest(sp, text):
    return hashlib.sha1(f"{sp}\n{text}".encode("utf-8")).hexdigest()[:8]


class Accenter:
    def __init__(self):
        self.table = stress.load()
        self.defaults = {stress.key(w): stress.positions(w) for w in DEFAULTS}
        self.book = defaultdict(set)  # 全书标过重音的词形 → 重音位置
        for _, _, ln in stress.sources(set()):
            for w in stress.stressed_words(ln):
                self.book[stress.key(w)] |= stress.positions(w)

    def part(self, w):
        if re.search(r"[0-9A-Za-z]", w) or (len(w) > 1 and w.isupper()):
            return "{" + w + "?}"
        if stress.syllables(w) < 2 or ACUTE in w or "ё" in w.lower():
            return w
        k = stress.key(w)
        d, b = self.table.get(k, set()), self.book.get(k, set())
        if k in self.defaults:
            pos = self.defaults[k]
        elif len(d) == 1 and (not b or b == d):
            pos = d
        elif not d and len(b) == 1:
            pos = b
        else:
            cands = sorted(d | b)
            return "{" + w + "?" + "|".join(stress.mark(k, {p}) for p in cands) + "}"
        (p,) = pos
        return w[:p + 1] + ACUTE + w[p + 1:]

    def word(self, w):
        if re.search(r"[0-9A-Za-zÀ-ɏ]", w):
            return "{" + w + "?}"
        return "-".join(self.part(p) for p in w.split("-"))

    def text(self, s, special=True):
        out = []
        for i, piece in enumerate(re.split(f"({SPECIAL.pattern})", s) if special else [s]):
            if i % 2:  # 记号：前面的空白保留在外面
                core = piece.lstrip()
                out.append(piece[:len(piece) - len(core)] + "{" + core + "?}")
            else:
                out.append(WORD.sub(lambda m: self.word(m.group()), piece))
        return "".join(out)


def path(lesson):
    return TEXT / f"{lesson}.txt"


def parse(p):
    """朗读稿 → [(说话人, 校验码, 文本)]。"""
    out = []
    for block in re.split(r"\n\s*\n", p.read_text(encoding="utf-8").replace("\r\n", "\n").strip()):
        head, _, body = block.partition("\n")
        m = re.fullmatch(r"@(\S+) ([0-9a-f]{8})", head.strip())
        if not m:
            raise ValueError(f"{p.name}：段首应为“@说话人 校验码”：{head}")
        out.append((m.group(1), m.group(2), body.strip()))
    return out


def write(lesson, segs):
    TEXT.mkdir(parents=True, exist_ok=True)
    path(lesson).write_text("\n\n".join(f"@{sp} {h}\n{t}" for sp, h, t in segs) + "\n", encoding="utf-8")


def source(lesson):
    md = (ROOT / "lessons" / f"{lesson}.md").read_text(encoding="utf-8")
    return [(sp.replace(" ", "_"), text) for sp, text in tts.segments(md)]


def needs_script(lesson):
    return not re.match(r"(L|B2-L)\d+$", lesson)


def update(lesson, acc):
    """生成或更新朗读稿；返回待定词个数。第一、二册课文没有要改写的内容时不生成。"""
    src = source(lesson)
    old = {}
    if path(lesson).exists():
        for sp, h, t in parse(path(lesson)):
            old[(sp, h)] = t
    segs = [(sp, digest(sp, t), t) for sp, t in src]
    segs = [(sp, h, old.get((sp, h)) or acc.text(t)) for sp, h, t in segs]
    n = sum(len(TODO.findall(t)) for _, _, t in segs)
    if not needs_script(lesson) and not path(lesson).exists() and not n:
        return None
    write(lesson, segs)
    return n


def load(lesson):
    """tts.py 用：朗读稿 → [(说话人, 文本)]；第一、二册没有朗读稿时直接用课文。"""
    src = source(lesson)
    if not path(lesson).exists():
        if needs_script(lesson) and src:
            raise RuntimeError(f"{lesson} 没有朗读稿，先运行 python tools/accent.py {lesson}")
        return [(sp.replace("_", " "), t) for sp, t in src]
    segs = parse(path(lesson))
    if [(sp, digest(sp, t)) for sp, t in src] != [(sp, h) for sp, h, _ in segs]:
        raise RuntimeError(f"{lesson} 课文改过，朗读稿已过期，先运行 python tools/accent.py {lesson}")
    todo = [m.group() for _, _, t in segs for m in TODO.finditer(t)]
    if todo:
        raise RuntimeError(f"{lesson} 朗读稿还有 {len(todo)} 个待定词：{' '.join(todo[:5])}…")
    return [(sp.replace("_", " "), t) for sp, _, t in segs]


def bare(s):
    return re.sub(r"\s+", " ", s.replace(ACUTE, "").replace("ё", "е").replace("Ё", "Е")).strip()


def check(lesson, acc):
    """朗读稿和课文逐段比对：去掉重音后，除了待定词的位置，文字应该完全一样。"""
    problems = []
    src = dict(((sp, digest(sp, t)), t) for sp, t in source(lesson))
    for sp, h, t in parse(path(lesson)):
        if (sp, h) not in src:
            problems.append(f"{sp} {h}：课文里没有这一段（朗读稿过期）")
            continue
        def matches(special):
            pattern = ""
            for piece in re.split(r"(\{[^{}]*\?[^{}]*\})", acc.text(src[(sp, h)], special)):
                pattern += r".+?" if TODO.fullmatch(piece) else re.escape(bare(piece))
            return re.fullmatch(pattern, bare(t), re.S)
        if not (matches(True) or matches(False)):  # 记号可以连同周围的标点整体改写，也可以只改写其中的字母数字
            problems.append(f"{sp} {h}：文字和课文不一致：{t[:60]}…")
        for m in TODO.finditer(t):
            problems.append(f"{sp} {h}：待定 {m.group()}")
        rest = TODO.sub("", t)
        for m in RESIDUE.finditer(rest):
            problems.append(f"{sp} {h}：还有没改写的记号“{m.group()}”：…{rest[max(0, m.start() - 30):m.end() + 20]}…")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lessons", nargs="*")
    ap.add_argument("--book", type=int, action="append", default=[])
    ap.add_argument("--todo", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    codes = list(a.lessons)
    for b in a.book:
        codes += tts.lessons_of(b)
    if a.todo or a.check:
        codes = codes or sorted(p.stem for p in TEXT.glob("*.txt"))
        acc = Accenter() if a.check else None
        total = 0
        for c in codes:
            if not path(c).exists():
                continue
            if a.check:
                probs = check(c, acc)
                for pr in probs:
                    print(c, pr)
                total += len(probs)
            else:
                n = sum(len(TODO.findall(t)) for _, _, t in parse(path(c)))
                if n:
                    print(c, n)
                total += n
        print("合计", total)
        return
    if not codes:
        ap.error("请给出课号，或用 --book N")
    acc = Accenter()
    stats = Counter()
    for c in codes:
        if not tts.segments((ROOT / "lessons" / f"{c}.md").read_text(encoding="utf-8")):
            continue
        n = update(c, acc)
        if n is None:
            continue
        stats["课"] += 1
        stats["待定"] += n
        print(c, f"待定 {n}" if n else "完成", flush=True)
    print(f"朗读稿 {stats['课']} 课，待定词 {stats['待定']} 个")


if __name__ == "__main__":
    main()
