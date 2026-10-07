# 课文录音

`tools/tts.py` 给第一、二册课文生成朗读音频，每课一个 mp3，存进 `audio/<课号>.mp3`。旁白和每个人物用固定音色，课文里的重音符号直接传给模型，按标出的重音读。

用到两个开源模型（Apache-2.0，免费，可商用），第一次运行时自动从 HuggingFace 下载：

| 模型 | 用途 | 大小 |
|---|---|---|
| `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` | 按文字描述生成音色（只在新增音色时用） | 4.5 GB |
| `siriusfreak/qwen3-tts-12hz-1.7b-ru-stress-cf` | 俄语重音微调版，克隆音色、朗读课文 | 4.3 GB |

## 安装（Windows / Linux，英伟达显卡）

显存 8 GB 以上即可（RTX 50 系也行，PyTorch 要用下面的 cu128 版）。需要 Python 3.10 以上和 ffmpeg（Windows 可 `winget install ffmpeg`，Ubuntu `sudo apt install ffmpeg`）。

```bash
cd RussianTextbook
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux: source .venv/bin/activate
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install qwen-tts soundfile huggingface_hub pyyaml
```

确认显卡可用：`python -c "import torch; print(torch.cuda.is_available())"` 应输出 `True`。

国内下载 HuggingFace 慢，可先设镜像：Linux `export HF_ENDPOINT=https://hf-mirror.com`，Windows PowerShell `$env:HF_ENDPOINT="https://hf-mirror.com"`。

## 生成

```bash
python tools/tts.py L89              # 一课（可以写几个课号）
python tools/tts.py --book 1         # 第一册全部
python tools/tts.py --book 2         # 第二册全部
python tools/tts.py --all            # 第一、二册全部
```

已经生成过的课自动跳过，加 `--force` 重录。中途中断，重新运行同一条命令会接着录。没有显卡时加 `--device cpu` 也能跑，但很慢（一分钟音频要算七分钟左右）。

句子按长短分批送进模型，默认一批 8 句（`--batch N`），12 GB 显存的 RTX 5070 上一分钟音频约算 40 秒；显存不够时调小。旁白长段落先按句切开再读。批量生成偶尔会漏读半句，脚本按字母数核对每句时长，偏短的单独重录；重录三次仍偏短的会提示“可能读漏”，需要试听。

## 音色

`tts/voices.json` 里每个音色一条：

- 键：去掉重音、小写的说话人名，与课文 `speakers` 对应；写成 `B2-L39:бабушка` 只用于那一课。
- `instruct`：音色描述（英文），决定声音的年龄、性别、性格、口音。
- `ref_text`、`ref`：参考音频的文本和文件名（在 `tts/ref/`）。

旁白和主要人物（王磊、伊万、玛丽亚、安娜、米沙、奥莉加老师、由美、皮埃尔、季马）的参考音频已在 `tts/ref/` 里，都是试听确认过的。配角第一次出现时，脚本先按 `instruct` 生成参考音频再朗读，之后各课复用同一段声音。

改某个人物的声音：改 `instruct`，删掉 `tts/ref/` 里对应的 wav，再用 `--force` 重录有这个人物的课。新出现、没在 `voices.json` 里配置的说话人暂用旁白音色，运行结束时会列出来。
