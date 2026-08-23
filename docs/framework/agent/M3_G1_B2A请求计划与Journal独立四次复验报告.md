# M3 G1 B2A 请求计划与 Journal 独立四次复验报告

日期：2026-07-13  
四次返工：[`M3_G1_B2A请求计划与Journal四次返工交付报告.md`](M3_G1_B2A请求计划与Journal四次返工交付报告.md)  
前次独立复验：[`M3_G1_B2A请求计划与Journal独立三次复验报告.md`](M3_G1_B2A请求计划与Journal独立三次复验报告.md)

## 1. 身份、范围与结论

本报告由未参与实现和四次返工的独立验收 Agent 编写。本轮只读检查生产代码，在系统临时目录运行隔离
反例；未联网、未读取 Tushare token、未访问 `_old/`，也未修改生产代码或测试。唯一项目写入是本报告。

**结论：独立四次复验不通过。** 四次返工已经关闭独立三次复验的原 P1 `NETWORK → COMPLETE` 先写
candidate 问题，以及原 P2 `_NoReceiptPreflight` 直接构造不变量问题；静态非法状态、公开 dataclass、IO
脱敏和 legacy API 均未回归。但独立新增反例发现：candidate 写入前只复查 raw 状态为 `COMPLETE`，未确认
它仍是刚刚验真的同一 raw snapshot，失败前会新增 candidate 和 receipt。另有一个受限可达的 candidate
existence 漂移缺口。分别记为 **P1** 和 **P2**，故不能进入“独立四次复验通过”状态，也不代表 B2A、
B2、G1 或 M3 Gate 通过。

## 2. 四次返工已关闭的前次问题

### 2.1 原 P1：NETWORK 决策后 raw 变 COMPLETE

复现步骤保持与独立三次复验一致：先形成合法 intent-only 状态；预检返回 `NETWORK` 后，由第二 raw writer
通过公开 `RawStore.write_request` 写入同 request 的合法 COMPLETE raw，再进入 `_recover_candidate`。

结果：稳定返回 `REQUEST_EVIDENCE_CLOSURE_CHANGED`，connector/monotonic/sleep 为 `0/0/0`；既有 intent
保留，candidate 和 receipt 均未新增，journal 普通文件内容集合完全不变。原 P1 已关闭。

### 2.2 原 P2：`_NoReceiptPreflight` 运行时不变量

直接构造共验证 16 个非法组合，**16/16 全部拒绝**：

- 原七类：非法 raw/mode enum、`int` 冒充 bool、COMPLETE 缺 intent、candidate 缺 intent、
  COMPLETE+NETWORK、ABSENT+RECOVER；
- 新增类型和闭包反例：raw/mode 为 bytes 或 `None`、intent 为 `None`、candidate 为 list、
  EMPTY+candidate+NETWORK、EMPTY+RECOVER 等。

四个冻结合法组合 **4/4 通过**：ABSENT/无 intent/NETWORK、EMPTY/有 intent/NETWORK，以及 COMPLETE/
有 intent/RECOVER 下 candidate 不存在和存在两种状态。原 P2 已关闭。

## 3. 第二 writer 与写入紧前重验矩阵

共执行 9 个受控漂移组合。按“当前执行器不得新增或覆盖不应产生的 journal 证据”的最终口径，7 个符合、
2 个暴露新 finding。所有组合 connector/monotonic/sleep 都为 `0/0/0`。

| 预检后或写入前变化 | 是否为实现报告已有组合 | 结果 | journal 观察 |
|---|---|---|---|
| NETWORK → COMPLETE | 是 | 通过 | 保留 intent；不新增 candidate/receipt |
| RECOVER → ABSENT | 否 | 通过 | 不新增、不覆盖 |
| RECOVER → EMPTY | 是 | 通过 | 不新增、不覆盖 |
| RECOVER，candidate 从不存在变为合法文件 | 否 | **失败，见 P2** | 接受外部 candidate，并新增 receipt |
| NETWORK，candidate 并发出现 | 否 | 通过 | closure changed；外部 bytes 不覆盖，无 receipt |
| candidate 写入紧前 COMPLETE → EMPTY | 否 | 通过 | closure changed；不新增 candidate/receipt |
| candidate 写入紧前 COMPLETE → 单边非法 raw | 否 | 通过 | `RAW_RECOVERY_INVALID`；零 journal 增量 |
| candidate 写入紧前 candidate 并发出现 | 否 | 通过 | closure changed；外部 bytes 不覆盖，无 receipt |
| candidate 写入紧前 raw 被替换为另一套 COMPLETE | 否 | **失败，见 P1** | 新增旧 candidate 和 receipt 后才失败 |

上述新增组合共 7 个，超过“至少 6 个实现报告未列组合”的要求。单边 raw 返回
`RAW_RECOVERY_INVALID` 而非 `REQUEST_EVIDENCE_CLOSURE_CHANGED`，但它稳定脱敏、零 API/clock/sleep、零
journal 副作用，不构成 finding。

## 4. 新 finding

### P1：candidate 写入前只复查状态字符串，未复查同一 raw snapshot 身份

- **现象**：`_recover_candidate` 在 `src/quant/data/m3_backfill.py:821`–`:829` 验真 raw 并基于该 snapshot
  构造 candidate；写入紧前的 `src/quant/data/m3_backfill.py:830`–`:834` 只再次调用
  `inspect_request_state` 并要求结果仍为 `COMPLETE`、candidate 仍不存在。若第二 raw writer 在这两个阶段
  之间把 raw pair 替换为另一套内容不同但布局同样合法的 COMPLETE pair，检查仍通过。随后旧 candidate
  和旧 receipt 被持久化，最终 verifier 才以 `RECEIPT_RAW_EVIDENCE_MISMATCH` 失败。
- **根因**：最终门禁验证了布局状态，没有重读 snapshot 并比较 checksum、metadata hash、size、rows、
  columns 等已经绑定进 candidate 的物理证据。`COMPLETE` 不是 raw identity。
- **应遵循规则**：candidate 首次发布前必须确认当前 raw 仍与构造 candidate 所用 snapshot 完全相同；不能
  以最终 verifier 的失败代替首次持久化之前的门禁。门禁失败时不得新增 candidate 或 receipt。
- **最小复现**：准备合法 intent + COMPLETE raw、无 candidate/receipt；预检和第一次 `verify_request`
  完成后，在最终 `inspect_request_state` 执行前删除原 pair，并通过公开 `RawStore.write_request` 写入列契约
  相同、单元格值不同的新 pair。最终状态仍为 COMPLETE。执行器的 connector/monotonic/sleep 是 `0/0/0`，
  但 journal 新增 candidate 和 receipt，之后才报 `RECEIPT_RAW_EVIDENCE_MISMATCH`。
- **可达性与边界**：探针使用受控第二 raw writer 精确命中四次返工明确新增的“candidate 发布前复查”位置；
  替换发生在复查之前，因此可通过比较 snapshot identity 检出，并非要求消除检查完成后的纳秒级或内核级
  不可避免竞态。本轮也不要求跨 raw/journal 的通用事务。
- **新增测试**：在最终 pre-publication recheck 前完成 COMPLETE-A → COMPLETE-B 替换；分别快照 raw 与
  journal 普通文件内容，断言稳定 closure 错误、`0/0/0`，且 candidate/receipt 均不存在。
- **通过条件**：最终 commit 前重新读取并比较当前 `RequestRawSnapshot` 与已构造 candidate 的全部绑定证据；
  任一不同即在 `_write_dataclass_once(candidate_path, ...)` 之前 fail-closed。比较通过后立即执行既有的不覆盖
  写；不继续递归要求消除检查完成后的不可避免瞬时替换。

### P2：冻结的 `candidate_exists` 未进入执行期漂移比较

- **现象**：`_NoReceiptPreflight` 冻结并验证 `candidate_exists`，但 no-receipt 执行分支只向
  `_recover_candidate` 传递 `preflight.mode`（`src/quant/data/m3_backfill.py:588`–`:594`）。预检为
  `RECOVER` 且 candidate 原本不存在时，如果合法 candidate 在 `_recover_candidate` 入口前出现，函数在
  `src/quant/data/m3_backfill.py:814`–`:819` 将它当作普通既存恢复证据；外层随后新增 receipt，整个执行成功，
  没有报告同 request evidence closure changed。
- **根因**：expected mode 只冻结 NETWORK/RECOVER 大分支，未比较预检时的 candidate existence；状态对象中
  已有的 `candidate_exists` 成为未消费的决策字段。
- **应遵循规则**：同 request 竞态应 fail-closed；已冻结的证据存在性必须在执行前比较。外部新出现的文件
  可以保留且不得覆盖，但当前执行器不应基于漂移后的闭包继续发布 receipt。
- **最小复现**：准备合法 intent + COMPLETE raw、无 candidate/receipt；预检返回 RECOVER 后，在恢复入口
  前发布与当前 raw 完全一致的 candidate。执行器不调用 connector/clock/sleep，也不覆盖 candidate，却新增
  receipt 并成功返回。
- **可达性与严重度**：candidate 没有公开发布 API，正常项目 writer 应遵守 journal 全局 writer lock；稳定
  复现需要外部动作绕过该 lock 或直接写文件，因此低于公开 raw writer 可达的 P1，记为 P2。但任务书要求
  同 request 并发竞态 fail-closed，且冻结对象明确保存该字段，所以仍应关闭。
- **新增测试**：覆盖 preflight candidate false→true；断言外部 candidate bytes 原样保留、无 receipt、
  `0/0/0` 且返回 closure changed。可同时覆盖 true→false，避免执行器静默重建被移除的证据。
- **通过条件**：将 expected candidate existence 一并传给恢复门禁；实际 existence 与预检不一致时在任何
  candidate/receipt 新写入之前失败。不要删除或覆盖外部文件。

## 5. 静态非法状态与历史回归

### 5.1 静态非法 14 状态

独立重跑结果 **14/14 通过**。九种非法 raw 布局（单边 data、单边 metadata、request symlink、request
普通文件、额外文件、未知目录、file symlink、directory symlink、FIFO），以及 COMPLETE 缺 intent、
candidate 缺 intent、candidate+raw ABSENT、candidate+raw EMPTY、损坏 intent，全部满足：

- connector/monotonic/sleep 为 `0/0/0`；
- raw 与 journal 普通文件集合和内容执行前后不变；
- 返回稳定的 `RAW_ORPHAN_OR_INVALID_LAYOUT`、`REQUEST_EVIDENCE_CLOSURE_INVALID` 或 `INTENT_INVALID`。

### 5.2 公开调用边界、IO 脱敏和 legacy API

定向 121 项套件全部通过，覆盖：

- forged batch/request 及嵌套对象构造后篡改在 IO 前拒绝；
- journal 未知项、symlink、FIFO 和不覆盖写；
- mkdir/open/close/link/fsync/lock cleanup、Parquet chained error、provider/classifier error 的稳定脱敏；
- `RawStore.write` legacy 幂等和 request raw 单边/symlink 行为。

未发现原 P1-1、P1-3、P1-4 或 legacy 行为回归。

## 6. 工具链结果

所有命令均在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
121 passed in 7.48s

python -m pytest -q
422 passed, 1179 warnings in 13.53s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 是现有 Pandera/Polars deprecation warning。真实网络、token 和真实 Tushare 配额不在本轮
范围内。

## 7. 下一轮通过条件

1. candidate 发布前重读并比较同一 raw snapshot 的绑定证据，关闭 P1；
2. 执行层比较冻结的 candidate existence，关闭 P2；
3. 把两个最小反例加入生产回归，并保持本报告的 9 个漂移组合、16 个非法/4 个合法 preflight 构造、
   静态非法 14 状态全部通过；
4. 重跑定向/全量 pytest、Ruff、mypy，并在返工报告中逐项记录“现象—根因—规则—复现—测试—通过条件”。

P1、P2 全部关闭后才可重新申请独立复验；独立复验通过后仍须主 Agent 最终验收，且不能据此自动宣称
B2A、B2、G1 或 M3 Gate 通过。
