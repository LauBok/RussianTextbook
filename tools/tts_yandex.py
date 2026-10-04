#!/usr/bin/env python3
"""用 Yandex SpeechKit 给课文逐句生成音频。

用法：
    export YANDEX_API_KEY=...        # 服务账号的 API 密钥（角色 ai.speechkit-tts.user）
    python3 tools/tts_yandex.py L01

输出：audio/L01/01.mp3、02.mp3 …，以及 audio/L01/manifest.json（句子序号、角色、文本、文件名）。
角色的声音按课文开头 speakers 的性别分配：f → alena，m → filipp。
课文里的重音符号（U+0301）转换成 SpeechKit 的重音标记：在重读元音前加 +。
"""
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import web  # noqa: E402  复用课文解析

import yaml

ROOT = Path(__file__).resolve().parent.parent
URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
VOICE = {"f": "alena", "m": "filipp"}
ACUTE = "́"


def to_speechkit(text):
    """Здра́вствуйте → Здр+авствуйте；去掉引号，破折号改为停顿。"""
    t = unicodedata.normalize("NFD", text)
    t = re.sub(r"(\w)" + ACUTE, lambda m: "+" + m.group(1), t)
    t = unicodedata.normalize("NFC", t)
    t = re.sub(r"[«»„“”\"]", "", t)
    t = re.sub(r"\s*[—–]\s*", ", ", t).strip(" ,")
    return t


def synth(text, voice, key, speed="0.9"):
    body = urllib.parse.urlencode({
        "text": text, "lang": "ru-RU", "voice": voice,
        "speed": speed, "format": "mp3",
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Authorization": "Api-Key " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main(lesson):
    key = os.environ.get("YANDEX_API_KEY")
    if not key:
        sys.exit("缺少环境变量 YANDEX_API_KEY")
    md = (ROOT / "lessons" / f"{lesson}.md").read_text(encoding="utf-8")
    front = yaml.safe_load(md.split("\n---\n", 1)[0].lstrip("-\n"))
    speakers = front.get("speakers", {})
    lines = web.lines(web.block(md, "dialogue"))
    out = ROOT / "audio" / lesson
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, ln in enumerate(lines, 1):
        gender = speakers.get(ln["sp"], "f")
        name = f"{i:02d}.mp3"
        (out / name).write_bytes(synth(to_speechkit(ln["text"]), VOICE[gender], key))
        manifest.append({"n": i, "sp": ln["sp"], "text": ln["text"], "file": name, "voice": VOICE[gender]})
        print(name, ln["sp"], to_speechkit(ln["text"]))
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
