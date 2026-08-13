# M3 G7C R1 正式 A 股公司行动 Entitlement 状态机独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**FAIL；返回返工，不得进入主 Agent 最终验收，不解锁 G7D remaining**

## 1. 独立性与范围

- 本 Agent 未参与 G7C R1 实现，使用全新独立上下文。
- 已完整阅读 `AGENTS.md`、`.ai` 直接适用规则、G7C 任务单（含两次重冻后的最终合同）、实现交付报告、G7D-F0 R3 主验报告、`corporate_actions.py`、安全导出以及 formal/development 新旧测试。
- 生产代码和实现者测试全程只读；本报告是唯一新增文件。未联网、未 `git add/commit`、未读写正式 G1 数据/journal。
- 独立 QA 仅在系统临时目录构造最小内存 facts，退出即清理；未将 QA 测试落盘到实现者测试文件。

## 2. 标准—证据—结论

| 合同标准 | 独立证据 | 结论 |
| --- | --- | --- |
| exact `VerifiedAShareMarketFacts` 和 identity 绑定 | 用同经济帧另签 `input_market_facts_sha256` 后复用旧 replay，得到唯一稳定错误且无 cause/context | 通过 |
| 窗前 record 零持仓证据 | 在首个 execution session 前增加权威 SH open record day；初始状态精确含 `(event_id, 0)`，且 positions 为空 | 通过 |
| 漏过权威结算 session 必须失败 | 令 due 为 SH open 但从 execution dates 删去；下一个 execution `advance` 稳定失败，未迟到入账 | 通过 |
| RIGHTS 、mixed event、HALF_UP、fractional stock、hostile ambient Decimal | 实现者 formal/development 定向组合 24 passed；代码对 RIGHTS 正/零持仓、`1.005 -> 1.01`、私有 Context 和 exact integer stock 有直接覆盖 | 通过 |
| hostile Mapping 异常脱敏 | `items()` 抛出含 TOKEN/event/quantity 的嵌套异常，对外仅 `M3_A_SHARE_ENTITLEMENT_INVALID`，无 cause/context | 通过 |
| 所有 processed/quantity 证据按 `event_id` 全局严格递增，合法 release 能完整 replay | 第一个 record day 事件 ID=`b*64`，第二个 record day ID=`a*64`；第二次 record-close 对合法 facts 抛出稳定错误 | **不通过** |
| transition/posting 必须由输入 replay 唯一复算，不允许缺失应有 posting | 对含 mixed cash+stock 的真实 CAPTURE transition 和同日 recognize+settle transition 分别 `replace(..., postings=(), cash_delta=0, settled_stock=())`，两个伪造对象均构造成功 | **不通过** |
| 不得从裸 positions/quantities 签发或恢复 formal replay，不得跳过 phase | 公开 dataclass 可构造，模块可达 `_expected_positions` + `_register_formal_replay` 可直接签发 `next_session_index=1/PRE_OPEN/quantity=100` 的状态；未执行 record-close/CAPTURE，后续公开 `advance` 却接受并生成 recognize posting | **不通过** |

## 3. 返工问题

### P0-1：transition 只校验“已提供 posting 各自合法”，不校验完整集合

- **现象**：删除 CAPTURE transition 的唯一 CAPTURE posting，或删除同日 mixed event 的全部 RECOGNIZE/SETTLE postings，`AShareEntitlementReplayTransition` 仍构造成功。结果 replay 已进入 CAPTURED/SETTLED，但账户汇总 delta 为零，审计输出与状态分裂。
- **根因**：`_formal_transition_postings_valid` 仅 `for posting in transition.postings` 逐条检查；空 tuple 空真，没有从前态+操作日+后态复算 exact posting tuple。
- **违反规则/不变量**：任务单 §6 “transition/posting 必须由输入 replay 唯一复算”，§4 mixed CAPTURE exact 一条，§5 所有 recognize 在所有 settle 前，§7 posting 唯一与 delta 完整性。
- **最小复现**：构造 cash=`0.01005`、stock=`0.1`、quantity=`100`、pay/list=`ex_date` 的 exact facts；完成真实 capture/advance；对返回 transition 执行 `dataclasses.replace(..., postings=(), cash_delta=Decimal(0), settled_stock=())`；当前构造成功。
- **必须新增的测试**：CAPTURE 少/多/换序 posting；同日 mixed event 的 recognize 少一 leg、settle 少一 leg、全部删除、recognize/settle 交错、不同 event 换序；每个都必须稳定失败。
- **通过条件**：formal transition 只能由两个公开状态转移入口签发；对 posting tuple 的任何缺失、额外、重排或 delta 漂移均在公开消费前失败。

### P0-2：模块级可达签发器允许跳过 record-close 注入历史持仓

- **现象**：caller 可从 exact facts 和自报 quantity 构造未经 CAPTURE 的 `AShareEntitlementReplayState`，调用模块可达 `_register_formal_replay`后，公开 `advance_formal_a_share_entitlements_pre_open` 接受该状态。独立 QA 成功绕过第一日 RECORD_CLOSE/CAPTURE，直接以 quantity=100 进入除权日。
- **根因**：formal state 是可直接构造的公开 dataclass；`_REPLAY_REGISTRY`、`_replay_fingerprint`、`_expected_positions` 和无验证的 `_register_formal_replay` 均位于模块可达表面。下划线命名不构成 capability 边界。
- **违反规则/不变量**：任务单 §3 不得公开跳过 phase/从裸 positions 签发或恢复 formal replay，§4 record-close quantity 必须来自当日账户总持仓，§7 完整 release 必须逐 session replay。
- **最小复现**：从 `initialize` 后不执行 record-close；用 `_formal_domain`、`_expected_positions((event_id,100), ..., next_index=1, phase=PRE_OPEN)` 构造公开 state；调用 `_register_formal_replay(state)`；公开 `advance(ex_date, state, facts)` 当前成功。
- **必须新增的测试**：遍历模块可达 callable/registry，证明没有接受裸 identity/positions/quantities/phase 的通用签发器；公开 constructor/`replace`、直接 registry 写入、复用旧 registry payload、跳过 CAPTURE 的未签发 state 全部被拒绝。
- **通过条件**：签发权必须收入不可由 caller 访问/写入的闭包边界；模块表面无 generic mint/register/registry payload；只有 initialize/advance/capture 能产生可被后续 formal 入口接受的 state/transition。

### P1-3：跨 record day 的 event_id 非单调时，合法 release replay 自相矛盾

- **现象**：较早 record day 的 ID=`b*64`、较晚 record day 的 ID=`a*64` 均为合法 exact ledger 事件；第二次 record-close 抛出 `M3_A_SHARE_ENTITLEMENT_INVALID`，完整 release 无法 replay。
- **根因**：捕获入口以 `replay.record_quantities + additions` 按日期追加（`corporate_actions.py:669`）；验证同时要求 tuple 全局等于 `sorted(...)`（`:970`），`expected_ids` 又来自全局 event-id 顺序。事件 ID 与 record date 无单调合同，两个要求不可同时满足。
- **违反规则/不变量**：任务单 §3 `record_quantities` 按 event_id 严格递增，§4 每个 record-close 处理当日完整事件集，§7 同 release 必须完整 replay。
- **最小复现**：两个 cash-only 事件，符号不同；record/ex 依次为 execution dates `[0]/[1]` 与 `[2]/[3]`；ID 依次为 `b*64`、`a*64`；两日都给 quantity=100。第二次 capture 失败。
- **必须新增的测试**：跨日 ID 逆序；同日多 event ID 逆序；窗前 event ID 与窗内 ID 交错；完整 replay 的 processed IDs/record quantities/positions/postings 全部仍为冻结的 canonical event-id 顺序。
- **通过条件**：合法 ledger 不依赖 event ID 与日期的隐式相关性；每次合并后以冻结 canonical event-id 顺序存储，且不通过排序修复本应由 G7D-F0 拒绝的八表物理乱序。

## 4. 验证结果

Windows 原生 `D:\Miniforge3\python.exe`，显式绑定 worktree `PYTHONPATH=src`：

- formal + development 定向 pytest：`24 passed`（72.17s）；
- 定向 Ruff：PASS；
- 定向 mypy `corporate_actions.py`：PASS；
- cold import：PASS，未加载 Qlib。

WSL Miniforge base，绝对 `PYTHONPATH=/home/mabw/.../m3-g4-formal/src`：

- 同一 formal + development 定向 pytest：`24 passed`（63.23s）；
- 定向 Ruff：PASS；
- 定向 mypy：PASS；
- cold import：PASS，未加载 Qlib；
- `stat -f` 结果 `FS_TYPE=wslfs`，当前为 `/mnt/f` DrvFS，不是 ext4。

一条最初 WSL 组合命令因 PowerShell 引号/变量承载返回 5.7s 空输出，未计入证据；随后使用绝对 WSL 路径全部重跑并取得上述可观测结果。pytest 仅有既有 Pandera deprecation 与无法写 `.pytest_cache` 的告警。

## 5. 结论与边界

G7C R1 的常规状态转移、窗前零证据、身份冲突、漏 due 失败、RIGHTS 和 Decimal 基础语义已有有效证据；但三项问题分别破坏完整 release 可重放性、transition 审计完整性与 formal 签发边界。因此独立初验结论为 **FAIL，返回返工**。

本结论仅针对 G7C formal 纯内存工程合同；Windows/DrvFS 绿测不等于 Linux/ext4 Gate，也不等于完整账户回测、真实 full-work 或 M3 Gate 关闭。
