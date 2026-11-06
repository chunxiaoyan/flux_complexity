# flux_complexity

基于 dependency flux 与句法复杂度研究的本地工具（开发中）。v1 计算两个指标：**flux size** 与 **flux weight**。

- 计算口径：[docs/spec.md](docs/spec.md)
- 阶段 1 审阅说明：[docs/review_stage1.md](docs/review_stage1.md)

## 安装与命令行使用

```bash
uv venv .venv
uv pip install -e ".[dev]"
.venv/Scripts/fluxcalc compute 文件.conllu --scheme UD -o positions.csv --sentences sentences.csv
```

运行测试：`.venv/Scripts/python -m pytest -q`
