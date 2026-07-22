# M3 另一个 Agent 任务单

你被分配实现 M3 的 **D1–D8**。函数签名、业务语义、目录、fixture 和验收条件的唯一事实来源是
[`M3实施与Agent交接.md`](../M3实施与Agent交接.md)；开始前必须完整阅读根目录 `AGENTS.md`、
`karpathy-guidelines.md` 和该交接文档。

## 执行顺序

1. 第一批：D1 readiness、D2 folds、D3 labels、D4 staging/manifest。
2. 第二批：D5 evaluate、D6 无状态 Top-k、D7 MLflow 薄适配器、D8 固定 dump 工具获取器。
3. 每完成一批先跑针对性测试，再跑全量 pytest、Ruff、mypy；不得等到最后一次性修复。

## 强制使用的验收数据

使用 `tests/fixtures/m3/` 的黄金 fixture。不得改动这些 fixture 或其 expected 文件来让实现通过；
如果认为真值有误，停止对应任务并在交付报告中给出逐行手算证据，由主 Agent 决定是否修改。

## 禁止范围

- 不实现或运行真实 Qlib/Alpha158/LightGBM 训练；不安装 `pyqlib`。
- 不修改 WSL base Python，不创建第二 conda 环境。
- 不调用 Tushare，不读取或输出 token。
- 不读取 `_old/`。
- 不改变已经冻结的 label、prediction、target Schema 和 M3 TOML 语义。
- 不实现 G0/G1、Qlib processor 防泄漏对账或最终统一回测接入。
- 不把 mock、fixture 或缺依赖分支描述为真实 Qlib 链路通过。

## 允许修改

- 交接文档第 3 节列出的 D1–D8 对应模块；
- 相应 `tests/unit/test_m3_*.py`；
- 必要的包 `__init__.py` 导出；
- 公共接口确有变化时按 SSOT 同步文档，但必须在交付报告单独列出并等待主 Agent 复核。

## 完成命令

在 WSL Miniforge base 中运行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

## 交付报告

按 D1–D8 逐项列出：修改文件、实现函数、针对性测试、边界用例、未实现项和原因。最后附三条全量
命令的原始摘要。不要勾选路线图 G0–G9，也不要宣称 M3 完成；主 Agent 会在用户下次下达验收任务
后独立复核。
