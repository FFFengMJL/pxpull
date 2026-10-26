# pxpull 开发说明

本文件面向在本仓库里工作的 AI 代理与人类贡献者。与具体机器相关的路径、镜像、代理等设置请写进
`AGENTS.local.md`（已在 `.gitignore` 中忽略），不要把本机环境写进这里。

## 项目

- 用途：在 Linux/macOS 上原生解析 PxCook（像素大厨）的 `.pxcp` 设计文件，导出画板整图、图层
  元数据、切图，并生成可点选/测量的 `viewer.html`；只读，不编辑或回写设计稿。
- 运行时只依赖 Pillow，支持 Python ≥3.10；查看器是单个 HTML 文件，不引入构建步骤或 CDN。

## 常用命令

```bash
uv sync
uv run pytest            # 15 个用例，全部使用合成 .pxcp，不依赖真实设计稿
uv run ruff check .
uv run pxpull info examples/demo.pxcp
uv run pxpull export examples/demo.pxcp -o /tmp/pxpull-demo
```

## 约定

- 不要提交真实设计稿、导出的画板/切图、客户或项目名称；测试与示例只用 `examples/demo.pxcp`
  这类合成数据（`examples/make_demo.py` 可重新生成）。
- 修改解析逻辑时同步更新 `tests/` 与 README 的「格式」说明，并保持 Python 3.10 兼容。
- `uv.lock` 以官方 PyPI 生成（`UV_DEFAULT_INDEX=https://pypi.org/simple uv lock`）。两道防线：
  `.githooks/pre-commit`（`make hooks` 启用）拦“锁文件被镜像改写”，`make lock-check`（CI 同样执行
  `uv lock --check`）拦“锁文件与 pyproject 不一致”。`UV_FROZEN=1`（或 `--frozen`，Makefile 已默认开启）
  只是本机兜底，避免跑一次 `uv run` 就触发改写。
- 命令行行为变化（参数、退出码、输出目录）要同步 README 与 `docs/`，避免文档示例不可执行。
- 提交信息说明动机；发版前跑 `uv build` 与 `git status` 自检。

## 文件分工

| 路径 | 内容 |
| --- | --- |
| `pxpull.py` | 解析器 + CLI（info/assets/elements/render/viewer/slice/export） |
| `pxpull_viewer.py` | 查看器 HTML 生成器 |
| `tests/` | 合成 `.pxcp` 构造器与回归测试 |
| `README.md` | 用法、格式逆向结果、限制 |
| `examples/demo.pxcp` | 公开演示用合成设计稿 |
| `scripts/check-lock.sh` | 锁文件 host 检查（pre-commit 与 CI 共用） |
| `.githooks/pre-commit` | 提交前检查；`make hooks` 启用 |
