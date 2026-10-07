#!/usr/bin/env python3
"""给课文生成朗读音频：每课一个 mp3，旁白和每个人物用固定音色。

用法：
    python tools/tts.py L89            # 一课或几课
    python tools/tts.py --book 1       # 整册（第一册、第二册……）
    python tools/tts.py --all          # 第一、二册全部
    选项：--device cuda|cpu（默认有显卡就用）  --force（已有的 mp3 也重录）  --batch N（每批句数，默认 8）

输出 audio/<课号>.mp3。安装和说明见 tts/README.md。

音色在 tts/voices.json：键是去掉重音、小写的说话人名，“课号:名字”可为某一课单独指定。
每个音色先用 Qwen3-TTS VoiceDesign 按 instruct 生成一段参考音频（tts/ref/，生成一次后复用），
再用俄语重音微调模型克隆这段声音朗读课文；课文里的重音符号（U+0301）直接传给模型。
"""
import argparse
import gc
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import web  # noqa: E402  复用课文解析

ROOT = Path(__file__).resolve().parent.parent
TTS = ROOT / "tts"
# 可用环境变量改成本地目录
DESIGN_MODEL = os.environ.get("TTS_DESIGN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
CLONE_MODEL = os.environ.get("TTS_CLONE_MODEL", "siriusfreak/qwen3-tts-12hz-1.7b-ru-stress-cf")
GAP = {"narrator": 0.9, "line": 0.5, "sentence": 0.35}
SEED = 7

def norm(name):
    s = unicodedata.normalize("NFD", name)
    s = s.replace("́", "")
    return unicodedata.normalize("NFC", s).lower().strip()

def segments(md):
    """课文节按顺序：prose 段落（旁白）、dialogue 行（说话人）。"""
    sec = re.search(r"^## 课文\n(.*?)^## ", md, re.S | re.M)
    out = []
    if not sec:
        return out
    for m in re.finditer(r"^:::\s*\{\.(prose|dialogue)[^\n]*\n(.*?)^:::\s*$", sec.group(1), re.S | re.M):
        kind, body = m.groups()
        if kind == "dialogue":
            for ln in web.lines(body):
                out.append((web.strip_md(ln["sp"]), web.strip_md(ln["text"])))
        else:
            for p in re.split(r"\n\s*\n", body.strip()):
                out.append(("narrator", web.strip_md(" ".join(p.split()))))
    return out

def lessons_of(book):
    pat = r"L\d+" if book == 1 else rf"B{book}-L\d+"
    codes = [p.stem for p in (ROOT / "lessons").glob("*.md") if re.fullmatch(pat, p.stem)]
    return sorted(codes, key=lambda c: int(re.search(r"(\d+)$", c).group(1)))

class Voices:
    def __init__(self, device, dtype):
        self.cfg = json.loads((TTS / "voices.json").read_text(encoding="utf-8"))
        self.device, self.dtype = device, dtype
        self.prompts = {}
        self.missing = set()
        self._clone = None

    def key(self, lesson, speaker):
        for k in (f"{lesson}:{norm(speaker)}", norm(speaker)):
            if k in self.cfg:
                return k
        self.missing.add(speaker)
        return "narrator"

    def ensure_refs(self, keys):
        """缺参考音频的音色先用 VoiceDesign 生成。"""
        todo = [k for k in keys if not (TTS / "ref" / self.cfg[k]["ref"]).exists()]
        if not todo:
            return
        import soundfile as sf
        import torch
        from qwen_tts import Qwen3TTSModel
        self._clone, self.prompts = None, {}  # 两个模型不同时占内存
        gc.collect()
        print(f"生成 {len(todo)} 个新音色：", "、".join(self.cfg[k]["name"] for k in todo), flush=True)
        m = Qwen3TTSModel.from_pretrained(DESIGN_MODEL, device_map=self.device, dtype=self.dtype)
        for k in todo:
            v = self.cfg[k]
            torch.manual_seed(1234)
            wavs, sr = m.generate_voice_design(text=v["ref_text"], instruct=v["instruct"], language="Russian")
            (TTS / "ref").mkdir(exist_ok=True)
            sf.write(TTS / "ref" / v["ref"], wavs[0], sr, subtype="PCM_16")
            print("  ", v["name"], v["ref"], flush=True)
        del m
        if self.device.startswith("cuda"):
            torch.cuda.empty_cache()

    @property
    def clone(self):
        if self._clone is None:
            from qwen_tts import Qwen3TTSModel
            self._clone = Qwen3TTSModel.from_pretrained(CLONE_MODEL, device_map=self.device, dtype=self.dtype)
        return self._clone

    def prompt(self, k):
        if k not in self.prompts:
            v = self.cfg[k]
            self.prompts[k] = self.clone.create_voice_clone_prompt(
                ref_audio=str(TTS / "ref" / v["ref"]), ref_text=v["ref_text"])
        return self.prompts[k]

MIN_SEC_PER_LETTER = 0.075  # 正常朗读约 0.08–0.13 秒/字母

def too_short(wav, sr, text):
    letters = len(re.findall(r"[^\W\d_]", text))
    return letters >= 20 and len(wav) / sr < MIN_SEC_PER_LETTER * letters

def split_long(text, limit=200):
    """长段落按句切开，再把相邻短句合并到不超过 limit 字符：模型读长段容易漏读，分批时长短也更整齐。"""
    if len(text) <= limit:
        return [text]
    sents = re.split(r"(?<=[.!?…»])\s+(?=[—«А-ЯЁA-Z])", text)
    parts = [sents[0]]
    for s in sents[1:]:
        if len(parts[-1]) + 1 + len(s) <= limit:
            parts[-1] += " " + s
        else:
            parts.append(s)
    return parts

def render(lesson, voices, force, batch=8):
    out = ROOT / "audio" / f"{lesson}.mp3"
    if out.exists() and not force:
        print(lesson, "已有，跳过")
        return
    md = (ROOT / "lessons" / f"{lesson}.md").read_text(encoding="utf-8")
    segs = segments(md)
    if not segs:
        print(lesson, "没有课文，跳过")
        return
    keyed = []  # (音色, 文本, 之后的停顿)
    for sp, text in segs:
        k = voices.key(lesson, sp)
        parts = split_long(text)
        for j, part in enumerate(parts):
            gap = GAP["sentence"] if j < len(parts) - 1 else GAP["narrator" if k == "narrator" else "line"]
            keyed.append((k, part, gap))
    voices.ensure_refs({k for k, _, _ in keyed})

    import numpy as np
    import soundfile as sf
    import torch
    # 按长度分批送进模型，长短相近的放一批，少补齐；生成后按课文顺序拼接
    order = sorted(range(len(keyed)), key=lambda i: len(keyed[i][1]))
    wavs_by_seg, sr = {}, 24000
    for b in range(0, len(order), batch):
        idx = order[b:b + batch]
        torch.manual_seed(SEED)
        wavs, sr = voices.clone.generate_voice_clone(
            text=[keyed[i][1] for i in idx], language="Russian",
            voice_clone_prompt=[item for i in idx for item in voices.prompt(keyed[i][0])])
        wavs_by_seg.update(zip(idx, wavs))
    # 批量生成偶尔跳过半句：按字母数估计应有时长，明显偏短的单独重录
    for i, (k, text, _) in enumerate(keyed):
        if not too_short(wavs_by_seg[i], sr, text):
            continue
        for seed in (SEED, SEED + 1, SEED + 2):
            torch.manual_seed(seed)
            wavs, sr = voices.clone.generate_voice_clone(text=text, language="Russian", voice_clone_prompt=voices.prompt(k))
            if len(wavs[0]) > len(wavs_by_seg[i]):
                wavs_by_seg[i] = wavs[0]
            if not too_short(wavs_by_seg[i], sr, text):
                break
        else:
            print(f"  {lesson} 第 {i + 1} 段可能读漏：{text[:40]}…", flush=True)
    pieces = []
    for i, (_, _, gap) in enumerate(keyed):
        w = np.asarray(wavs_by_seg[i], dtype=np.float32)
        pieces += [w, np.zeros(int(sr * gap), dtype=np.float32)]
    audio = np.concatenate([np.zeros(int(sr * 0.4), dtype=np.float32)] + pieces)
    out.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        wav = Path(tmpdir) / "audio.wav"
        sf.write(wav, audio, sr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", "loudnorm=I=-18",
                        "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "64k", str(out)], check=True)
    print(lesson, f"{len(audio) / sr:.0f} 秒", out.relative_to(ROOT), flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lessons", nargs="*")
    ap.add_argument("--book", type=int, action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--device")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--batch", type=int, default=8, help="一次送进模型的句数，显存不够就调小")
    a = ap.parse_args()

    import torch
    device = a.device or ("cuda:0" if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
    codes = list(a.lessons)
    for b in ([1, 2] if a.all else a.book):
        codes += lessons_of(b)
    if not codes:
        ap.error("请给出课号，或用 --book N / --all")

    voices = Voices(device, dtype)
    for c in codes:
        render(c, voices, a.force, a.batch)
    if voices.missing:
        print("以下说话人没有在 tts/voices.json 里配置音色，暂用旁白音色：", "、".join(sorted(voices.missing)))

if __name__ == "__main__":
    main()
