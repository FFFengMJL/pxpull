#!/bin/sh
# 检查 uv.lock 是否只引用官方 PyPI（pypi.org/simple 与 files.pythonhosted.org）。
# 用法：sh scripts/check-lock.sh [文件|-]；- 表示从 stdin 读取（pre-commit 用）。
set -eu

file="${1:-uv.lock}"
if [ "$file" = "-" ]; then
    src=$(cat)
else
    [ -f "$file" ] || exit 0
    src=$(cat "$file")
fi

bad=$(printf '%s\n' "$src" \
    | grep -oE 'https://[^"]+' \
    | grep -vE '^https://(pypi\.org/simple|files\.pythonhosted\.org/)' \
    | sort -u || true)

if [ -n "$bad" ]; then
    echo "uv.lock 引用了非官方 PyPI 的地址：" >&2
    printf '%s\n' "$bad" | sed 's/^/  /' >&2
    echo "用 UV_DEFAULT_INDEX=https://pypi.org/simple uv lock 重新生成（本机有镜像时加 UV_FROZEN=1）。" >&2
    exit 1
fi
