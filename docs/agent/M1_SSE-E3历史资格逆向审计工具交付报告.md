# M1 SSE-E3 历史资格逆向审计工具交付报告

日期：2026-07-17  
角色：外部实现 Agent（cursor-grok-4.5-high）  
任务单：[M1_SSE-E3历史资格逆向审计工具任务单.md](M1_SSE-E3历史资格逆向审计工具任务单.md)  
结论：**实现自测完成，待独立初验与主验；未宣称 Gate 通过；未对真实 data 做历史覆盖发布**

## 1. 完成内容

- 新增纯函数 `verify_reverse_eligibility_history` 与 frozen/slots 值对象
  `VerifiedReverseEligibilityAudit`（构造时重算字段不变量）。
- 稳定错误码：`REVERSE_AUDIT_INPUT_INVALID` /
  `COVERAGE_INVALID` / `EVENT_CONFLICT` / `STATE_CONFLICT` / `COUNT_MISMATCH`，
  经 `EligibilityHistoryError` 抛出，不回声 symbol/path/raw。
- `CleanConnectSnapshotStore.read_route_date`、`CleanConnectEventStore.read_route`：
  精确路径只读；root/祖先/route/date/target 的 symlink、FIFO、目录、缺失 fail-closed；
  不做 legacy/全盘发现。
- 新 CLI `python -m quant.data.audit_connect_eligibility`：只读、零网络、不写 artifact；
  成功单行严格 JSON（无 symbols/path）；失败非零且无成功 JSON。
- README 增加只读审计命令说明；`quant.data` 仅安全导出值对象与纯函数。

## 2. 白名单改动文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/eligibility.py` | 逆向审计纯函数与值对象 |
| `src/quant/data/storage.py` | 显式安全 reader |
| `src/quant/data/audit_connect_eligibility.py` | 只读 CLI（新） |
| `src/quant/data/__init__.py` | 安全导出 |
| `tests/unit/test_eligibility.py` | 逆向审计单元覆盖 |
| `tests/unit/test_storage.py` | connect read fail-closed |
| `tests/unit/test_audit_connect_eligibility.py` | fixture/CLI/反例（新） |
| `README.md` | 只读审计命令 |
| `docs/agent/M1_SSE-E3历史资格逆向审计工具交付报告.md` | 本报告 |

未改 Schema/enums；边界 dtype 比 Schema `coerce=True` 更严，无合同冲突。

## 3. 验证（WSL Miniforge base）

```text
python -m pytest tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py -q
→ 18 passed；退出码 0

python -m pytest tests/unit/test_storage.py -q -k 'connect and read'
→ 9 passed, 20 deselected；退出码 0

ruff check <白名单源与测试>
→ All checks passed!；退出码 0

mypy src/quant/data/eligibility.py src/quant/data/storage.py src/quant/data/audit_connect_eligibility.py
→ Success: no issues found in 3 source files；退出码 0
```

全部使用 tmp/fake fixture（含 SH→268、SZ→417 合成逆推）；未访问项目真实 `data/`，未联网，未全量 pytest，未 Git。

## 4. 明确非宣称

- 不宣称 M1 Gate / SSE-E3 最终通过。
- 不宣称真实历史覆盖已发布、universe/baseline 已重建。
- 合成 fixture 规模 268/417 仅验证算法与合同；不等于官方端点实盘逆推证据（见 E1 主验）。

## 5. 风险与下一步

- 现有项目 clean 事件若仍含旧 mapper 错误 action，真实逆推可能 STATE_CONFLICT；需先完成 E2 授权 replace 后再跑真实审计。
- 独立初验须只读核对，并补任务单要求的 `/tmp` 反例：完整合法事件集中插入早于 baseline 的事件不得被静默过滤。
- 初验通过后由主 Agent 终验；实现者不得自行勾选路线图。
