# M4-P1 OMS 状态机独立初验报告

日期：2026-07-16  
初验模型：`cursor-grok-4.5-high`（非 fast；**未使用** GPT/Terra）  
身份：外部独立初验 Agent（**未参与** M4-P1 实现）  
结论：**通过（可交主验）**；**未关闭** M4 / Gate；**未勾选**路线图

环境：`cwd=/home/mabw/win/Cursor/quant`；`conda run -n base …`。  
未改生产代码、未改仓库测试、未执行 `git init`、未跑全量 pytest、未 LIVE/真实券商。

---

## 1. 初验范围与证据边界

| 项 | 处理 |
|---|---|
| 任务合同 SSOT | `docs/agent/M4轻量交易闭环分包任务书.md` M4-P1；交接卡 `M3_M4_Grok交接清单.md` M4-P1 |
| 实现者自述 | `docs/agent/M4_P1_OMS状态机交付报告.md`（**不作证据**；仅对照声称） |
| 只读核对 | `src/quant/execution/oms.py`、`tests/unit/test_execution_oms.py` |
| 写入白名单 | **仅本报告** |
| 禁止 | 改代码；全量 pytest；LIVE/真实券商；宣称 Gate 关闭 |

对抗使用一次性 `/tmp/m4_p1_oms_adversarial_verify.py`（不入库）。

命名说明：任务书白名单写 `tests/unit/test_oms.py`；交付物为 `tests/unit/test_execution_oms.py`。初验按**实际文件**执行，记为命名偏差、不阻塞。

---

## 2. 质量命令复跑摘要（初验自跑为准）

| 命令 | 摘要 |
|---|---|
| `conda run -n base python -m pytest -q tests/unit/test_execution_oms.py` | **20 passed**（约 1.65s） |
| `conda run -n base python -m ruff check src/quant/execution/oms.py tests/unit/test_execution_oms.py` | **All checks passed** |
| `conda run -n base python -m mypy src/quant/execution/oms.py` | **Success: no issues found in 1 source file** |
| 全量 pytest | **未跑**（任务禁止） |
| LIVE / 真实券商 | **未跑**（任务禁止） |

---

## 3. 任务书逐条映射（M4-P1 ∩ reduce_order）

| 要求 | 证据 | 判定 |
|---|---|---|
| 入口 `reduce_order(aggregate, command, event) -> OrderAggregate` | `oms.py` 公开签名；`new_order_aggregate` 种子 `CREATED` | 通过 |
| 纯函数，无 IO | 模块无 sqlite/httpx/requests/urllib/socket；单测 `test_no_network_or_db_imports_in_oms_module`；仅内存 `replace` | 通过 |
| 合法状态转移 | `CREATED→SUBMITTED\|REJECTED`；fill 自 `SUBMITTED\|PARTIAL_FILLED\|CANCELLING`；cancel 自同三态；终态 `_TERMINAL={FILLED,CANCELLED,REJECTED}` | 通过 |
| 同 `event_id` 幂等 no-op | `event.event_id in applied_event_ids` → 原样返回；单测 `test_idempotent_replay_same_event` / `test_duplicate_fill_same_payload_is_noop` | 通过 |
| 非法转移 / 非单调成交 fail closed | `OmsError`；ACK 后旧 NEW、重复经济 fill、cum 回退、终态回退等实现者单测 + 初验对抗 | 通过 |
| 反例：重复/乱序 event | 实现者：`test_out_of_order_partial_*`、`test_duplicate_fill_*`；初验：等 cum 非单调、CANCELLING 后迟到更低 cum | 通过 |
| 反例：fill 超量 | 实现者：builder `ContractError`；初验：对 builder 谎报 `command_quantity` 后 OMS 仍拒 `cum > qty` | 通过 |
| 反例：cancel-fill 竞态 | 实现者：全成 `FILLED` / 部分后 `CANCELLED`；初验：CANCELLING 上乱序更低 fill、重复 `CANCEL_ACCEPTED` | 通过 |
| 反例：终态后非法回退 | 实现者：FILLED/CANCELLED；初验：REJECTED 后再 ACCEPTED | 通过 |
| 反例：同 event_id 异 payload | D0 `__post_init__` 拒伪造 id（`replace` 改字段即 `ContractError`）；OMS 对已应用 id **不重核 payload**（依赖 D0 content-hash，与交付披露一致） | 通过（分层防御） |
| 白名单：未改 `__init__.py` / contracts / store / ports | 只读范围未见越权修改需求；本初验未改任何生产文件 | 通过 |
| 基于待主验 D0 预实现披露 | 交付报告与模块 docstring 已披露；**不得**解读为 D0/M4 Gate 已关 | 已记录 |

### 3.1 reduce_order 行为摘要（只读映射）

```text
幂等：applied_event_ids 命中 → 原 aggregate（不做 payload 比对）
绑定：aggregate.command_id == command.command_id == event.command_id
终态：FILLED | CANCELLED | REJECTED → 任意新 event_id → OmsError
ACCEPTED：仅 CREATED；cum==0 → SUBMITTED
REJECTED：仅 CREATED；需 reject_code → REJECTED
PARTIAL_FILL/FILL：仅 SUBMITTED|PARTIAL_FILLED|CANCELLING；
  cum 严格单调；last == cum-prev；cum≤qty；
  PARTIAL 不得触顶；FILL 必须触顶；CANCELLING 上 PARTIAL 保持 CANCELLING
CANCEL_ACCEPTED：SUBMITTED|PARTIAL_FILLED（CANCELLING 上新 id 非法）
CANCELLED：三态；cum 须等于 filled_quantity
```

---

## 4. 新增对抗反例（实现者未用）

脚本：`/tmp/m4_p1_oms_adversarial_verify.py`  
结果：**10 PASS / 0 FAIL**

| # | 反例 | 期望 | 实测 |
|---|---|---|---|
| 1 | CREATED 上直接 FILL | OmsError | PASS |
| 2 | SUBMITTED 后再 REJECTED | OmsError | PASS |
| 3 | CANCELLING 上第二笔异 id CANCEL_ACCEPTED | OmsError | PASS |
| 4 | CANCELLED.cum ≠ filled | OmsError | PASS |
| 5 | CANCELLING 后迟到更低 cum PARTIAL | OmsError（非单调） | PASS |
| 6 | 同 cum 异 event_id 第二笔 PARTIAL | OmsError | PASS |
| 7 | 同 event_id 异 payload：`replace` 伪造 | D0 ContractError；真事件重放 no-op | PASS |
| 8 | builder 谎报更大 command_quantity 造 cum=120 | OMS 拒超量 | PASS |
| 9 | 终态 REJECTED 后再 ACCEPTED | OmsError | PASS |
| 10 | SUBMITTED 直接 CANCELLED（无 CANCEL_ACCEPTED） | CANCELLED / filled=0 | PASS（合法路径） |

主反例一句话：**对 builder 谎报更大 `command_quantity` 造出 cum=120 的 FILL，OMS 仍按真实 command.qty fail-closed 拒超量。**

---

## 5. 发现问题

| 级别 | 项 | 说明 |
|---|---|---|
| 观察 | 测试文件名 | 任务书 `test_oms.py` vs 交付 `test_execution_oms.py`；不阻塞 |
| 观察 | 同 id 异 payload | OMS 层不做 payload 比对，依赖 D0 content-hash；分层正确，主验应确认 D0 仍有效 |
| 无阻塞缺陷 | — | 对抗 10/10 与 scoped 质量门均绿 |

---

## 6. 结论与交接

**独立初验：通过。** 可交主 Agent 终验。

主验建议关注：

1. D0 content-hash 与 OMS「仅按 event_id 幂等」的分层契约是否仍成立；  
2. 与 P0 持久化 / P2 Gateway 编排衔接时，cancel–fill 竞态与终态语义是否保持一致；  
3. 测试文件命名与任务书白名单是否需文档对齐。

**声明**：未通过更高 Gate；未宣称 M4 / 路线图完成。
