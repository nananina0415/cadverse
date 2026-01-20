#!/bin/bash
# Claude Code 임시 파일 정리 스크립트

echo "Cleaning Claude temporary files..."

# tmpclaude-* 파일 찾기 및 삭제
count=$(find . -maxdepth 1 -name "tmpclaude-*" -type f | wc -l)

if [ $count -gt 0 ]; then
    echo "Found $count temporary file(s)"
    find . -maxdepth 1 -name "tmpclaude-*" -type f -delete
    echo "✓ Removed $count file(s)"
else
    echo "✓ No temporary files found"
fi

echo "Done!"
