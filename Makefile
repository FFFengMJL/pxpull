# 默认冻结锁文件：本机若配置了镜像，普通 uv run 会把镜像地址写回 uv.lock。
# 需要更新依赖时显式运行 uv lock，或 make test UV_FROZEN=0。
UV_FROZEN ?= 1
export UV_FROZEN

.PHONY: test lint fmt info export hooks check-lock lock-check

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

# 启用提交前检查（uv.lock 只允许官方 PyPI）
hooks:
	git config core.hooksPath .githooks
	@echo "已启用 .githooks/pre-commit"

check-lock:
	sh scripts/check-lock.sh uv.lock

# 确认 uv.lock 与 pyproject.toml 一致（本地可能有镜像配置，固定用官方源检查）
lock-check:
	UV_DEFAULT_INDEX=https://pypi.org/simple uv lock --check

# 示例：make info FILE=xxx.pxcp
info:
	uv run pxpull info "$(FILE)"

export:
	uv run pxpull export "$(FILE)" -o out/design
