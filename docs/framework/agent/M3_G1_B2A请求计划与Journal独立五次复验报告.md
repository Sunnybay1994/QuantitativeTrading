# M3 G1 B2A 请求计划与 Journal 独立五次复验报告

日期：2026-07-13  
五次返工：[`M3_G1_B2A请求计划与Journal五次返工交付报告.md`](M3_G1_B2A请求计划与Journal五次返工交付报告.md)  
前次独立复验：[`M3_G1_B2A请求计划与Journal独立四次复验报告.md`](M3_G1_B2A请求计划与Journal独立四次复验报告.md)

## 1. 身份、范围与结论

本报告由未参与实现和五次返工的独立验收 Agent 编写。本轮只读检查生产代码，使用系统临时目录运行隔离
反例；未联网、未读取 Tushare token、未访问 `_old/`，也未修改生产代码或测试。唯一项目写入是本报告。

**结论：独立五次复验不通过。** 五次返工已经关闭独立四次复验的 COMPLETE-A → COMPLETE-B 预验证
替换，以及 candidate false→true/true→false 两个 existence 漂移问题。静态非法状态、preflight 构造、
expected mode、公开 dataclass、IO 脱敏和 legacy API 也均未回归。

但 commit 前完整 verifier 自身仍存在边界内的两次读取不一致：它先通过 `RawStore.verify_request` 得到
snapshot，随后再次按 path 读取 Parquet；若受控 raw writer 在这两个动作之间改变 metadata、物理 Parquet
bytes 或 metadata hash，而第二次读取的逻辑 frame 仍与旧 candidate 相同，verifier 会组合“旧 snapshot +
当前 frame”并错误通过。执行器随后新增 candidate 和 receipt，最终 receipt verifier 才失败。该问题发生在
最终 verifier 完成之前，不是本轮明确排除的检查后纳秒级替换，记为 **P1**。因此本报告不宣布 B2A、B2、
G1 或 M3 Gate 通过。

## 2. 五次返工已关闭的前次问题

### 2.1 COMPLETE-A → COMPLETE-B

重跑独立四次复验的原反例：在第一次 verify/build 完成后、最终 `_verify_candidate` 开始前，通过受控 raw
writer 把 COMPLETE-A 替换为内容不同但合法的 COMPLETE-B。

结果：`CANDIDATE_RAW_EVIDENCE_MISMATCH`；connector/monotonic/sleep 为 `0/0/0`；candidate 和 receipt 均
未新增，journal 普通文件内容集合不变。原 P1 在该注入位置已关闭。

### 2.2 candidate existence 双向漂移

| 漂移 | 结果 | journal 观察 |
|---|---|---|
| preflight false → recover 前 true | `REQUEST_EVIDENCE_CLOSURE_CHANGED` | 外部 candidate bytes 原样保留；无 receipt |
| preflight true → recover 前 false | `REQUEST_EVIDENCE_CLOSURE_CHANGED` | 不重建被外部移除的 candidate；无 receipt |

两项 connector/monotonic/sleep 都为 `0/0/0`。`expected_candidate_exists` 已进入恢复入口比较，独立四次
复验的原 P2 已关闭。

## 3. Commit 前对抗性变体

### 3.1 验证方法

准备合法 intent + COMPLETE-A、无 candidate/receipt。对 raw identity 类反例，在最终 `_verify_candidate`
内部的 `verify_request` 已返回、但其 `_read_parquet_sanitized` 尚未读取 Parquet 时执行受控变化。该注入点：

- 位于五次返工明确声称的 commit 前完整 verifier **内部且完成之前**；
- 所有变化在 candidate existence 最终检查和 `_write_dataclass_once` 之前完成；
- 不要求 verifier 完成后的纳秒级恶意替换，也不要求跨 raw/journal 通用事务隔离。

每项分别快照 journal 普通文件路径与 bytes，并记录 connector、monotonic、sleep。

### 3.2 结果矩阵

共执行 12 个漂移/commit 探针，9 个符合、3 个失败。所有探针 connector/monotonic/sleep 均为 `0/0/0`。

| 反例 | commit 前是否拦截 | executor journal 副作用 | 结果 |
|---|---|---|---|
| COMPLETE-A → 内容不同 COMPLETE-B，在 final verifier 开始前 | 是 | 无 | 通过 |
| candidate false → true | 是 | 不覆盖外部 candidate，无 receipt | 通过 |
| candidate true → false | 是 | 不重建，无 receipt | 通过 |
| final verifier 内 metadata-only identity 改变 | **否** | 新增 candidate + receipt | **失败，P1** |
| final verifier 内同逻辑内容、不同物理 Parquet bytes | **否** | 新增 candidate + receipt | **失败，P1** |
| final verifier 内 rows 改变 | 是 | 无 | 通过 |
| final verifier 内 columns 改变 | 是 | 无 | 通过 |
| final verifier 内 logical content 改变 | 是 | 无 | 通过 |
| final verifier 内 metadata checksum/hash 变为无效 | **否** | 新增 candidate + receipt | **失败，P1** |
| candidate commit 紧前出现冲突 bytes | 是 | 外部 bytes 原样保留，无 receipt | 通过 |
| expected NETWORK → COMPLETE | 是 | 保留 intent，无 candidate/receipt | 通过 |
| expected RECOVER → ABSENT | 是 | 无 candidate/receipt | 通过 |

新增 commit 前变体包括 metadata-only、同逻辑不同物理 bytes、rows、columns、content、hash 和外部 candidate
冲突，共 7 类，满足“至少 5 个”的要求。

三项失败的末端错误分别为 `RECEIPT_RAW_EVIDENCE_MISMATCH`、`RECEIPT_RAW_EVIDENCE_MISMATCH` 和
`RECEIPT_RAW_INVALID`。这些错误最终能够发现不一致，但发生在 candidate、receipt 已经持久化之后，不能
替代首次 commit 前门禁。

## 4. 新 P1：最终 candidate verifier 组合了两次不绑定的 raw 读取

- **现象**：`src/quant/data/m3_backfill.py:903`–`:911` 调用 `raw_store.verify_request`。该方法内部已经读取
  data/metadata bytes、校验 hash/rows/columns 并返回 snapshot，但不返回刚才解析的 frame。随后
  `src/quant/data/m3_backfill.py:912` 再次按 `snapshot.data_path` 读取 Parquet，并在 `:914` 用第一次 snapshot
  和第二次 frame 重建 expected candidate。两次读取之间 raw 可发生变化。
- **根因**：snapshot 的 file hash、metadata hash、size、rows、columns 来自第一次读取；response content
  来自第二次路径读取。两者没有证明来自同一份 raw bytes。只要第二次 frame 的逻辑内容与旧 frame 相同，
  candidate 全等比较就看不到当前物理文件或 metadata 已变。
- **应遵循规则**：`RawStore` 必须通过一次读取/验真返回绑定的 `snapshot + frame` bundle；candidate 和
  receipt verifier 必须消费该 bundle，不得在取得 snapshot 后再次按 path 读取 Parquet。最终 receipt
  verifier 失败不能替代 commit 前检查。
- **最小复现 A（metadata-only）**：最终 `verify_request` 返回 snapshot-A 后，只把 metadata 的合法
  `fetched_at` 改为另一时刻，data 不变。第二次读出的 frame 仍为 A，candidate 比较通过；新增 candidate、
  receipt 后才因 metadata hash 不一致失败。
- **最小复现 B（同逻辑、不同物理 bytes）**：snapshot-A 返回后，把同一 Polars frame 以不同 Parquet
  compression 重新编码，并同步更新 metadata checksum/size，形成严格合法的 COMPLETE-B。逻辑 content
  digest 不变，但物理 file hash/size 改变。当前 verifier 仍通过并 commit，末端才失败。
- **最小复现 C（hash）**：snapshot-A 返回后把 metadata checksum 改为错误值，布局仍 COMPLETE。第二次
  读取 data-A 后旧 candidate 比较通过；commit 后 receipt verifier 才以 raw invalid 失败。
- **可达性与冻结边界**：三个替换都由受控 writer 在最终 verifier 第一次读取结束后、第二次读取之前完成，
  即发生在 verifier 内部。修复可在现有 commit 前流程中检测，不需要文件系统事务或消除 verifier 完成后的
  不可避免瞬时竞态。
- **新增测试**：保留上述三项失败反例，并保留 rows、columns、content 三项已通过对照；每项断言
  connector/clock/sleep 为零，candidate/receipt 不存在。外部 raw 变化可以保留，不要求回滚。
- **通过条件**：`RawStore` 单次读取 data/metadata bytes，完成 hash/size/rows/columns/Parquet 验真，并从
  同一份 data bytes 解析 frame，返回不可混配的 `snapshot + frame` bundle；candidate/receipt verifier 不再
  按路径二读。metadata hash、data hash/size、rows/columns 和 response content 任一不一致均在 candidate
  首次写入前失败。冻结边界止于 bundle 验证返回后；不递归要求 bundle 返回后的纳秒级替换。

## 5. 静态状态、Preflight 与历史回归

### 5.1 静态非法 14 状态

独立重跑 **14/14 通过**。九种非法 raw 布局，以及 COMPLETE 缺 intent、candidate 缺 intent、
candidate+raw ABSENT/EMPTY、损坏 intent，均满足：

- connector/monotonic/sleep 为 `0/0/0`；
- raw/journal 普通文件路径和 bytes 执行前后相同；
- 返回稳定脱敏错误码。

### 5.2 Preflight 20 与 expected mode

- `_NoReceiptPreflight` 非法 type/enum/cross-field 组合：**20/20 拒绝**；
- 四个冻结合法组合：**4/4 通过**；
- expected NETWORK→COMPLETE、RECOVER→ABSENT，以及 candidate commit 前冲突 bytes：全部 fail-closed，
  不新增、不覆盖当前执行器不应产生的 journal 证据。

### 5.3 IO 脱敏、public dataclass 与 legacy

定向 124 项套件全部通过，继续覆盖：

- forged request/batch、嵌套构造后篡改的 pre-IO 拒绝；
- journal 非普通/未知项、symlink、FIFO、不覆盖语义；
- mkdir/open/close/link/fsync/lock cleanup、Parquet、provider/classifier 异常脱敏；
- `RawStore.write` legacy 幂等，以及 request raw 单边/symlink 行为。

未发现历史 P1-1、P1-3、P1-4 或 legacy API 回归。

## 6. 工具链结果

全部命令在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
124 passed in 7.27s

python -m pytest -q
425 passed, 1179 warnings in 13.74s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 是已有 Pandera/Polars deprecation warning。真实网络、token、真实 Tushare 配额不在本轮
范围内。

## 7. 下一轮通过条件

1. 由 `RawStore` 单次读取/验真返回 `snapshot + frame` bundle，candidate/receipt verifier 移除按路径二读，
   并把冻结边界明确止于 bundle 验证返回后，关闭 P1；
2. 将 metadata-only、同逻辑不同物理 bytes、hash 三个红灯反例加入生产回归；
3. 保持本报告 rows/columns/content、candidate 冲突、两项 candidate existence、expected mode、静态 14、
   preflight 20 全部通过；
4. 重跑定向/全量 pytest、Ruff、mypy，并在返工报告中完整记录现象、根因、规则、复现、测试和通过条件。

P1 关闭后才可重新申请独立复验；独立复验通过仍须主 Agent 最终验收，且不能据此自动宣称 B2A、B2、G1
或 M3 Gate 通过。
