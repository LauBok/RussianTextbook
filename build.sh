#!/usr/bin/env bash
# 用法：./build.sh L01   （不带参数则编译 lessons/ 下全部课）
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
lessons=("$@")
[ ${#lessons[@]} -eq 0 ] && lessons=($(ls lessons/*.md | xargs -n1 basename | sed 's/\.md$//'))
for L in "${lessons[@]}"; do
  src="lessons/$L.md"
  if [ -f "exercises/$L.yaml" ]; then
    python3 tools/exercises.py "$L" >/dev/null
    src="build/gen/$L.md"
    pandoc "build/gen/$L-答案.md" -f markdown -t html5 -s \
      --template template.html --lua-filter zh-punct.lua -V css=../style.css \
      -o "build/$L-答案.html"
    python3 -m weasyprint "build/$L-答案.html" "build/$L-答案.pdf"
    echo "build/$L-答案.pdf"
  fi
  pandoc "$src" -f markdown -t html5 -s \
    --template template.html --lua-filter zh-punct.lua -V css=../style.css \
    -o "build/$L.html"
  python3 -m weasyprint "build/$L.html" "build/$L.pdf"
  echo "build/$L.pdf"
done
