# M4-P1 OMS 状态机交付报告

日期：2026-07-16  
角色：外部实现 Agent（cursor-grok-4.5-high；仅实现与自测）  
状态：**待独立初验**（未关 Gate；未宣称 M4 / Gate 通过）  
任务书：[`M4轻量交易闭环分包任务书.md`](M4轻量交易闭环分包任务书.md) M4-P1  
交接卡：[`M3_M4_Grok交接清单.md`](M3_M4_Grok交接清单.md) M4-P1

## 1. 交付结论

已交付纯内存 OMS reducer：`new_order_aggregate` / `reduce_order` → `OrderAggregate`。合法状态转移、同 `event_id` 幂等 no-op、非法转移与非单调成交 fail closed。无网络/DB IO。未改 `__init__.py`、contracts、store、ports、config、domain。

**披露（强制）**：本包基于 **M4-C0/D0/D1 待主验** 合同预实现；不得将下游依赖解读为相关 Gate 已关闭。

## 2. 冻结入口

| 入口 | 语义 |
|---|---|
| `new_order_aggregate(command) -> OrderAggregate` | 绑定 command 的 `CREATED` 投影 |
| `reduce_order(aggregate, command, event) -> OrderAggregate` | 纯函数 reduce；同 event_id 已应用 → no-op |

状态：`CREATED → SUBMITTED|REJECTED`；`SUBMITTED|PARTIAL_FILLED|CANCELLING` 可成交/撤单；`FILLED|CANCELLED|REJECTED` 终态。Cancel–fill 竞态：`CANCELLING` 上允许单调成交，全成则 `FILLED`，否则 `CANCELLED` 保留已成量。

## 3. 修改文件（白名单）

- `src/quant/execution/oms.py`（新建）
- `tests/unit/test_execution_oms.py`（新建）
- `docs/framework/agent/M4_P1_OMS状态机交付报告.md`（本文件）

## 4. 验证摘要

| 命令 | 结果 |
|---|---|
| `conda run -n base python -m pytest -q tests/unit/test_execution_oms.py` | 20 passed |
| `conda run -n base python -m ruff check src/quant/execution/oms.py tests/unit/test_execution_oms.py` | All checks passed |
| `conda run -n base python -m mypy src/quant/execution/oms.py` | Success |

未跑全量 pytest（按任务约束）。

覆盖反例：ACK 后旧 NEW、重复 fill、乱序/非单调 partial、cancel–fill 竞态、累计超量（D0 builder）、delta 不一致、终态回退、command_id 错绑、PARTIAL 触顶/FILL 未满、无 sqlite/http 导入。

## 5. 已知边界

- 基于待主验 D0 合同预实现；状态仅为待独立初验。
- 同 event_id 异 payload 由 D0 content-hash 在构造期拦截；OMS 对已应用 event_id 做幂等 no-op。
- 未做 SQLite 持久化（P0）与 Gateway 编排（P2/P4）。

## 6. 声明

**未通过**更高 Gate；状态仅为「待独立初验」。独立初验通过后方可交主 Agent 终验。
