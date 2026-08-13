# M3 G7D-P1 执行纯函数合同主 Agent 阶段验收报告

日期：2026-08-02

## 结论

G7D 第一段开发契约通过：A 股板块与拒绝原因 SSOT、申报数量规则、目标差量、费用分项及执行值对象已完成
Windows 原生和 WSL base 定向验证。此结论仅覆盖纯函数合同，不代表 G7D 完成，更不代表正式 G1、Linux
ext4 Gate 或 M3 发布通过。

## 改动与边界

- `quant.domain.enums` 新增 `AShareBoard`，扩展执行拒绝原因；执行模块只 import 枚举，不复制字符串集合。
- 新增 `quant.backtest.a_share_execution` 的冻结值对象、板块规则、买卖申报数量、目标差量和 Decimal 费用函数。
- 主板/创业板卖出同时比较整手候选与公司行动零股尾数候选；科创板保留 `<200` 仅全仓卖尽的规则。
- 正目标因最小申报量向下映射为 0 时仍生成可审计 intent，留给后续层投影 `LOT_CONSTRAINT`。
- 本段没有网络请求，没有读取 `data/legacy`，没有写正式 G1 release、journal 或候选映射。

尚未纳入本段：八表 market-facts 闭包、开盘状态投影、卖单执行、离散现金买入分配及场景账户循环。

## 验证

Windows 原生 `D:\Miniforge3\python.exe`：

```text
python -m pytest -o pythonpath=src tests/unit/test_m3_a_share_execution.py -q
50 passed
python -m ruff check <G7D-P1 changed files>
All checks passed!
python -m mypy <G7D-P1 source files>
Success: no issues found in 4 source files
```

WSL Miniforge base（当前路径位于 `/mnt/f`，因此不是 ext4 Gate）：

```text
python -m pytest -o pythonpath=src tests/unit/test_m3_a_share_execution.py -q
50 passed
python -m ruff check <G7D-P1 changed files>
All checks passed!
python -m mypy <G7D-P1 source files>
Success: no issues found in 4 source files
```

Windows pytest 另有工作树 `.pytest_cache` 权限 warning，测试结果和源码校验不受影响。

## 剩余风险

- `ExecutionBatch` / `BuyAllocation` 目前只有边界值对象；真实守恒须由 G7D 后续卖出与买入分配实现验证。
- 正式 G2C 长时 fresh-chain 仍在独立工作树运行；本开发提交不进入其冻结源码范围。
- Windows 与 WSL/DrvFS 绿测只证明开发合同跨平台，不关闭 Linux/ext4 或正式发布 Gate。
