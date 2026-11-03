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

第一、二册的俄语标重音，第三册起按 CLAUDE.md（练习里的俄语不标，生词表标）。判定答案时忽略重音符号、ё/е 差别、大小写、标点和破折号，所以 `accept` 里不需要为这些差别重复列出。

## 题型

**`picture_qa` 看图问答**　`items[].image`（`img/<课号>/` 下的 SVG）、`qword`（Кто / Что）、`answer`（可接受答句列表）；`example` 为作例题的小题序号。

**`choice` 选择或填空**　`items[].stem`（空位写 `___`）、`options`、`answer`。

**`fill` 填写词形**　`items[].stem`（空位写 `___`）、`hint`（括号里给的原形）、`accept`（可接受答案列表）。

**`rewrite` 改写**　`example: {cue, answer}`；`items[].cue`、`accept`。

**`translate` 翻译**　`items[].zh`、`accept`（完全正确的参考译文，全部列出）、`rubric`（判卷要点：本题必须用对的语法和词）。答案与 `accept` 之一一致时直接判对，否则交给 Claude 按 `rubric` 批改。

**`open` 开放题**（缩写、作文、情景对话）　`items[].prompt`、`length`（字数范围）、`model`（参考范文）、`rubric`（必须包含的信息、本课要用的语法）、`notes`（范文的结构和写作要点，进答案附录）。一律交给 Claude 批改。

## 测试页的分值

期中、期末和入册复习测试的每道大题可加 `points`（每小题分值），构建时自动在题目要求后写出“（每小题 2 分，共 20 分）”；只有一个小题的大题写成“（共 15 分）”。

## 答题空间

开放题按 `length` 上限留横线（手写俄语约每行 8 词，至少 6 行）；翻译题题目超过 25 字留两行，否则一行（普通课的翻译题留 1 行）。需要别的行数时，在小题里写 `lines: N`（如俄译汉按汉字算，可直接指定）。

## 试卷册（exams/K*.yaml）

《第一册试卷》每套一个文件，`lesson` 写卷号（`K03`），卷级字段另有 `range`（考试范围，如 `L01-L29`）、`total`（满分）、`minutes`（时限）。题型同上：

- 单项选择、完形填空、阅读理解用 `choice`；完形填空和阅读的文章写在 `passage`，参考译文写在 `passage_zh`。阅读的几篇各占一个题组，`task` 写成“阅读理解（一）：……”“阅读理解（二）：……”，排版时合为一道大题。
- 语法填空用 `fill` 加 `passage`：空和括号里的提示词都写在文章里（`(1) []{.blank} (жить)`），小题只写 `accept`。
- 汉译俄用 `translate`，补全对话、便条、续写用 `open`。

写完运行 `python3 tools/check.py exams/K03.yaml`（只许用 range 末课及以前学过的词）、`python3 tools/exam.py --balance K03`（正确答案均匀分到 A B C D）、`python3 tools/exam.py --check`（查重复题干），排版 `python3 tools/exam.py` → `dist/第一册试卷.pdf`。
