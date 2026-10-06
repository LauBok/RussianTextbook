#!/usr/bin/env python3
"""给课文生成朗读音频：每课一个 mp3，旁白和每个人物用固定音色。

用法：
    python tools/tts.py L89            # 一课或几课
    python tools/tts.py --book 1       # 整册（第一册、第二册……）
    python tools/tts.py --all          # 第一、二册全部
    选项：--device cuda|cpu（默认有显卡就用）  --force（已有的 mp3 也重录）

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
GAP = {"narrator": 0.9, "line": 0.5}
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

def render(lesson, voices, force):
    out = ROOT / "audio" / f"{lesson}.mp3"
    if out.exists() and not force:
        print(lesson, "已有，跳过")
        return
    md = (ROOT / "lessons" / f"{lesson}.md").read_text(encoding="utf-8")
    segs = segments(md)
    if not segs:
        print(lesson, "没有课文，跳过")
        return
    keyed = [(voices.key(lesson, sp), text) for sp, text in segs]
    voices.ensure_refs({k for k, _ in keyed})

    import numpy as np
    import soundfile as sf
    import torch
    pieces, sr = [], 24000
    for k, text in keyed:
        torch.manual_seed(SEED)
        wavs, sr = voices.clone.generate_voice_clone(text=text, language="Russian", voice_clone_prompt=voices.prompt(k))
        w = np.asarray(wavs[0], dtype=np.float32)
        gap = GAP["narrator"] if k == "narrator" else GAP["line"]
        pieces += [w, np.zeros(int(sr * gap), dtype=np.float32)]
    audio = np.concatenate([np.zeros(int(sr * 0.4), dtype=np.float32)] + pieces)
    out.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        sf.write(tmp.name, audio, sr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp.name, "-af", "loudnorm=I=-18",
                        "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "64k", str(out)], check=True)
    print(lesson, f"{len(audio) / sr:.0f} 秒", out.relative_to(ROOT), flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lessons", nargs="*")
    ap.add_argument("--book", type=int, action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--device")
    ap.add_argument("--force", action="store_true")
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
        render(c, voices, a.force)
    if voices.missing:
        print("以下说话人没有在 tts/voices.json 里配置音色，暂用旁白音色：", "、".join(sorted(voices.missing)))

if __name__ == "__main__":
    main()
