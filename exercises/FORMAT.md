# 练习数据格式

每课一个 `exercises/<课号>.yaml`。课文 Markdown 里在练习的位置写 `<!-- EXERCISES -->`，构建时由 `tools/exercises.py` 生成三样东西：PDF 练习节、书末答案（含解析）、交互页数据。练习只在 YAML 里写一次。

## 公共字段

| 字段 | 说明 |
|---|---|
| `id` | 本课内唯一，如 `e1` |
| `type` | 题型，见下 |
| `task` | 题目要求（中文） |
| `why` | 解析：为什么用这个形式、容易错在哪里 |
| `items` | 小题列表 |

俄语一律标重音。判定答案时忽略重音符号、ё/е 差别、大小写、标点和破折号，所以 `accept` 里不需要为这些差别重复列出。

## 题型

**`picture_qa` 看图问答**　`items[].image`（`img/<课号>/` 下的 SVG）、`qword`（Кто / Что）、`answer`（可接受答句列表）；`example` 为作例题的小题序号。

**`choice` 选择或填空**　`items[].stem`（空位写 `___`）、`options`、`answer`。

**`fill` 填写词形**　`items[].stem`（空位写 `___`）、`hint`（括号里给的原形）、`accept`（可接受答案列表）。

**`rewrite` 改写**　`example: {cue, answer}`；`items[].cue`、`accept`。

**`translate` 翻译**　`items[].zh`、`accept`（完全正确的参考译文，全部列出）、`rubric`（判卷要点：本题必须用对的语法和词）。答案与 `accept` 之一一致时直接判对，否则交给 Claude 按 `rubric` 批改。

**`open` 开放题**（缩写、作文、情景对话）　`items[].prompt`、`length`（字数范围）、`model`（参考范文）、`rubric`（必须包含的信息、本课要用的语法）、`notes`（范文的结构和写作要点，进答案附录）。一律交给 Claude 批改。
