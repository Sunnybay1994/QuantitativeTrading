# M4-P7-R1：EOD 执行报告交付报告

日期：2026-08-02  
状态：R2 返工与 Windows 独立初验通过；等待 WSL 定向验证和主验

## 实现结果

- 新增 `quant.reporting.execution_report`，以 P5 `RecoveryResult`、`ReconciliationResult` 和 risk decisions
  构造零 IO、内容寻址、跨平台 canonical JSON 报告。
- 报告覆盖 order/fill/position/cash/risk/reconciliation/totals；report id 绑定全部公开内容。
- 原始 broker order id、risk subject/detail 与 reconciliation subject 不进入报告；只保留 SHA-256 身份。
- builder 重构 recovery、reconciliation、aggregate、checkpoint 并调用 command/event public identity verifier；risk command
  必须存在于 recovery 且绑定同 plan/approved intent。
- encoder 重新构造并验证公开 report 的结构、排序、计数和 identity，拒绝冻结对象 mutation 或绕过 builder 的非法对象。
- builder 按每个 aggregate 的 `applied_event_ids` 从 genesis 重放现有 OMS reducer，最终投影必须与持久 aggregate
  逐值相同；全部 retained events 必须恰好消费一次，拒绝缺失、跨 command、重复与孤儿 event。
- `quant.reporting` 包根同步导出公共类型与 builder/encoder。

## 修改文件

- `src/quant/reporting/execution_report.py`
- `src/quant/reporting/__init__.py`
- `tests/unit/test_execution_report.py`
- `docs/agent/M4_P7_R1_EOD执行报告任务单.md`
- 本报告

## Windows 自测

```powershell
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest tests/unit/test_execution_report.py -q --basetemp .pytest-p7d
D:\Miniforge3\python.exe -m ruff check src/quant/reporting/__init__.py src/quant/reporting/execution_report.py tests/unit/test_execution_report.py
D:\Miniforge3\python.exe -m mypy src/quant/reporting/__init__.py src/quant/reporting/execution_report.py tests/unit/test_execution_report.py
```

最终结果：`10 passed`；Ruff PASS；mypy PASS。pytest 仅报告工作区 `.pytest_cache` 因当前 Windows 权限不可写的 warning，
定向 `--basetemp` 测试产物创建与测试本身成功。

覆盖：空 EOD Gate、完整 partial+fill/ledger/risk、脱敏、risk 输入逆序、身份 mutation、跨 recovery risk command、
重复 plan、零文件/SQLite/network IO、report mutation 后 encoder fail closed，以及自洽 hostile 文本、自洽重复 command、
结构合法但 reducer 漂移的 aggregate。独立初验另加“aggregate 只消费 ACCEPTED、其余 retained fill 成为孤儿”反例并通过。

## 未关闭事项

- WSL Miniforge base 定向验证尚未形成；Windows 结果不替代 Linux Gate。
- P7 只关闭工程报告契约，不关闭 P6、P8、四周 PAPER/SHADOW soak、broker live 或 M4。
