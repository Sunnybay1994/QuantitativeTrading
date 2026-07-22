# M4 B4-P0B 三包合流定向验证报告（D0+B2+P3）

日期：2026-07-17  
角色：全新外部只读合流验证 Agent（未参与 P0A/P0B1/P0B2/P0B3 实现；本会话仅写本报告）  
模型：`cursor-grok-4.5-high`  
合同 SSOT：[`M4_B4-P0B显式Route贯通外部闭环任务单.md`](M4_B4-P0B显式Route贯通外部闭环任务单.md) §5  
前置独立初验（均已通过，只读结论）：

| 包 | 报告 | 初验结论 |
| --- | --- | --- |
| P0A | [`M4_B4-P0A港股通RouteContext领域合同独立初验报告.md`](M4_B4-P0A港股通RouteContext领域合同独立初验报告.md) | 通过 |
| P0B1 | [`M4_B4-P0B1领域合同迁移独立初验报告.md`](M4_B4-P0B1领域合同迁移独立初验报告.md) | 通过 |
| P0B2 | [`M4_B4-P0B2港股通规则迁移独立初验报告.md`](M4_B4-P0B2港股通规则迁移独立初验报告.md) | 通过 |
| P0B3 | [`M4_B4-P0B3事前风控迁移独立初验报告.md`](M4_B4-P0B3事前风控迁移独立初验报告.md) | 通过 |

状态：**有条件通过**（route 前置外部闭环完成；见 §1 / §6）  
边界：未修改 `src/` / `tests/` / configs / data；唯一写入本报告；未跑全量 pytest；未宣称 Gate / M4 / B4 完成。

工作目录：`/home/mabw/win/Cursor/quant`（WSL：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`）  
环境：`/home/mabw/miniforge3/bin/conda run -n base <command>`

## 1. 总判

定向合流命令：**104 passed / 2 failed**。两失败均落在白名单外 `src/quant/data/repositories.py`（未传 `connect_contexts`），与 P0B1 初验已知清单一致；**不阻塞**「route 前置外部闭环」。

合同链只读核对：`ConnectRoute` → `VerifiedConnectMarketContext` → intent / snapshot → B2 → P3，日历开市与额度无第二套 SSOT。

**结论：有条件通过。** 条件＝承认 D1 repository / 生产 adapter 仍缺 `connect_contexts` 迁移；该缺口属下游，不否定三包 route 贯通。

**明确边界（≠ 完成）：** 三包+合流通过 **≠** B4 planner / D1 生产 repository / 真实 route 数据 / M4 Gate 完成。

## 2. 验证命令与结果

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/unit/test_execution_contracts.py tests/unit/test_execution_ports.py tests/unit/test_connect_execution.py tests/unit/test_pretrade_risk.py -q` | **104 passed, 2 failed** | 合流一次跑通；失败见 §3 |
| 分文件复核 | 见下表 | 与合流行一致 |
| `python -m ruff check`（contracts / ports / connect_execution / risk + 对应四测试） | 通过 | `All checks passed!` |
| 全量 pytest / M3 workflow / 网络 | 未运行 | 任务禁止 |

### 2.1 分文件结果

| 文件 | 结果 |
| --- | --- |
| `tests/unit/test_execution_contracts.py` | `28 passed` |
| `tests/unit/test_execution_ports.py` | `17 passed, 2 failed` |
| `tests/unit/test_connect_execution.py` | `19 passed` |
| `tests/unit/test_pretrade_risk.py` | `40 passed` |
| **合计（合流）** | **104 passed, 2 failed** |

### 2.2 运行时 SSOT 探针（只读）

| 探针 | 结果 |
| --- | --- |
| `SymbolMarketState` 有 `buy_quota_available` | False |
| `VerifiedConnectMarketContext` 有 `buy_quota_available` | True |
| `VerifiedMarketSnapshot` 有 `connect_contexts` | True |
| `OrderIntent` 有 `connect_route` | True |
| `connect_execution.ConnectCalendarState` | False（已退役） |
| `connect_execution._CONNECT_ROUTES` | False（已退役） |
| `evaluate_connect_intent` 参数 | `intent, state, position, connect_context, rule_config` |

## 3. 已知失败与是否阻塞 route 前置闭环

| 失败用例 | 根因 | 位置 | 阻塞 route 前置外部闭环？ |
| --- | --- | --- | --- |
| `test_validated_clean_market_composes_reader_and_quality_gate` | `build_verified_market_snapshot()` 缺必填 `connect_contexts` | `repositories.py:409` | **否**（D1 repository，任务单 §5 明示未完成） |
| `test_domain_and_from_states_errors_sanitized` | 同上 | `repositories.py:502` | **否** |

两失败与 P0B1 独立初验「白名单外预期失败」完全一致；P0B2/P0B3 未改 repository。核心 D0 合同 / B2 / P3 定向节点全绿（28+19+40，外加 ports 迁移相关 17）。

## 4. 合同链核对（ConnectRoute → … → P3）

| 环节 | 源码事实 | 合流证据 |
| --- | --- | --- |
| **P0A** `ConnectRoute` + `VerifiedConnectMarketContext` | route 精确枚举；`buy_quota_available` 仅在 context；不存 `connect_open` | contracts 含 context 测试；探针确认 |
| **P0B1** intent / snapshot | `OrderIntent.connect_route`；`VerifiedMarketSnapshot.connect_contexts`；state **无** quota | contracts `28 passed`；探针 |
| **P0B2** B2 | 消费单个 `connect_context`；`connect_open = mainland_open and hong_kong_open`；BUY 读 context quota；无 `ConnectCalendarState` | connect_execution `19 passed`；探针 |
| **P0B3** P3 | `_resolve_hk_connect_context` 按 `route is` 精确匹配；仅 HK BUY 读 `resolved.buy_quota_available`；SH/SZ 不消费 context | pretrade_risk `40 passed`；源码 ~215–246 / ~619–645 |
| **无第二套日历/额度 SSOT** | state 无 quota；B2 无独立日历值对象；P3 不读 `state.buy_quota_available` | `rg`：`src/` 无 `ConnectCalendarState`；quota 仅 context 路径 |

链路判定：**D0→B2→P3 领域消费链已贯通；唯一剩余断点在生产 repository 组装 snapshot 时未注入 contexts。**

## 5. 与各包独立初验的对齐

| 初验声明 | 合流复核 |
| --- | --- |
| P0A 通过；RouteContext 为额度/开市事实载体 | 合流未回退；contracts 仍绿 |
| P0B1 通过；ports 完整跑 2 failed（repository） | **复现**：同 2 用例、同 TypeError |
| P0B2 通过；`ConnectCalendarState` / `_CONNECT_ROUTES` 退役 | 探针 + `19 passed` |
| P0B3 通过；仅 `resolved.buy_quota_available` | `40 passed`；源码确认 |
| 各包：≠ Gate/M4/B4 | 本报告亦不宣称 |

未发现独立初验夸大或与合流运行矛盾之处。

## 6. 裁定与已知下游缺口

### 6.1 裁定

**有条件通过** — route 前置外部闭环（P0A + P0B1→P0B2→P0B3 定向合流）完成。

条件说明：合流命令中 2 个 ports 失败为已知、白名单外、D1 repository 未迁 `connect_contexts`；**不构成**对本闭环的否决。

### 6.2 已知下游缺口（范围外，非本合流缺陷）

1. **D1 / 生产 repository**：`ValidatedCleanMarketDataRepository` / `InMemoryMarketDataRepository.from_states` 调用 `build_verified_market_snapshot` 时未传 `connect_contexts`
2. **B4 planner**：未实现
3. **真实 route 数据 / adapter**：未接入
4. **M4 Gate / B4 整体**：未关闭、未宣称完成

### 6.3 缺陷清单

无 P0 / P1（针对 D0+B2+P3 route 贯通范围）。无返工项要求三包回滚。

---

本报告唯一写入路径：`docs/agent/M4_B4-P0B三包合流定向验证报告.md`。
