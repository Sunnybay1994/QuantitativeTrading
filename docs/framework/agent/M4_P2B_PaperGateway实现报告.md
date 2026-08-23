# M4-P2B PaperGateway 实现报告

状态：实现与自测完成；等待独立初验与主 Agent 终验。

## 实现摘要

- 新增同时实现 submit/cancel transport 的确定性内存 PaperGateway。
- 注入 clock、fill policy、fault plan、B3 cost/FX；无 IO、网络、随机和系统时钟。
- 所有回调复用公共 event builder、transport verifier 与 OMS reducer。
- 支持 NOT_SENT/UNKNOWN、延迟 callback、精确重复、重启恢复源 command 和 cancel-fill 竞态。
- fill 按实际增量成交量调用 B3 `calculate_execution_cost`；限价与累计成交 fail closed。
- UNKNOWN 在实例内保持终态；NOT_SENT 可在显式重连后安全转入 SENT。broker/event/fee 身份不含 attempt。
- PAPER 拒单 code 使用单一固定集合 `{PAPER_RULE_REJECT}`，自由文本不得进入 `ExecutionEvent`。

## 独立复验返工

- **现象**：`PaperSubmitPlan.reject_code` 原先只检查可打印非空字符串，hostile policy 可把路径或 token 文本
  原样写入持久化 callback。
- **根因**：把字符串格式验证误当成领域值域闭包，没有冻结 PAPER adapter 可产生的拒单码集合。
- **应遵循规则**：持久化错误码必须来自有限 SSOT；本包只允许 `PAPER_RULE_REJECT`。直接构造与 policy
  返回值都必须重新验证，拒绝内容不得进入 callback 或异常文本。
- **最小复现**：policy 返回 `reject_code=r"C:\TOKEN_SECRET"`，旧实现会生成同文本的 `REJECTED` event。
- **新增测试**：路径、TOKEN、控制字符、未知大写 code、其他格式合法 PAPER code 均覆盖直接构造和冻结对象
  篡改返回；另验证允许码跨新实例/不同 attempt 的 event identity 稳定。
- **通过条件**：所有未知码统一 `PAPER_POLICY_INVALID`，cause/context 为空且无输入回显；允许码正常生成唯一、
  可重放的 `REJECTED` callback。

## 验证

Windows 原生 Miniforge：

```text
ruff check paper.py gateways/__init__.py test_paper_gateway.py
All checks passed!
mypy --no-incremental paper.py
Success: no issues found in 1 source file
pytest test_paper_gateway.py test_gateway_transport_contracts.py test_execution_oms.py test_m4_costs_fx.py
133 passed
```

WSL Miniforge `base`、DrvFS `/mnt/f`：同一定向 Ruff、mypy、pytest 最终分别通过，pytest 为
`133 passed`。mypy 2.2.0 使用 worktree 默认 SQLite cache 时曾报 INTERNAL ERROR；`--show-traceback`
定位为 DrvFS cache 的 `sqlite3.OperationalError: disk I/O error`。将临时 cache 显式隔离到
`/tmp/mypy-p2b-reject` 后通过，未发现代码错误。

Windows 仅有既有 `.pytest_cache` ACL warning；独立 `--basetemp` 测试结果不受影响。

## 边界

本交付无网络、SDK、持久层、随机或系统时钟；未修改 contracts、OMS、store、domain、B1-B3 或顶层
execution 导出。证据仅证明 Windows 与 WSL/DrvFS 的 development PAPER 合同，不代表正式 M4、真实 PAPER
soak 或 WSL/ext4 Gate。
