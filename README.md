# 俄语教程

仿《新概念英语》结构的四册俄语自学教材，供中文母语者从零学到 C1。编写规范见 `CLAUDE.md`，四册大纲见 `docs/`。

## 生成

```
./build.sh L01                 # 印刷版 PDF 与答案，输出到 build/
python3 tools/web.py L01       # 交互课页，输出到 web/L01.html
```

依赖：pandoc、WeasyPrint、PyYAML；字体 PT Serif、PT Sans、Noto Serif CJK SC、Noto Sans CJK SC。
