# M3 G1 B2A 请求计划与 Journal 五次返工交付报告

日期：2026-07-13  
独立四次复验：[`M3_G1_B2A请求计划与Journal独立四次复验报告.md`](M3_G1_B2A请求计划与Journal独立四次复验报告.md)  
四次返工：[`M3_G1_B2A请求计划与Journal四次返工交付报告.md`](M3_G1_B2A请求计划与Journal四次返工交付报告.md)  
状态：已完成新 P1/P2 最小返工并自测；等待独立五次复验，不代表 B2A/B2/G1/M3 通过

## 1. 范围与红灯证据

本轮只修改 `src/quant/data/m3_backfill.py`、`tests/unit/test_m3_backfill_requests.py`，并新增本报告。
未修改 `storage.py`、独立报告、SSOT、路线图、Gate 或其他任务包；未联网、未读取 token 或 `_old/`。
独立四次复验确认前次 P1/P2 已关闭，本轮没有重写已通过的状态矩阵。

先增加三个生产回归。修复前结果为 **3 失败**：

- COMPLETE-A → COMPLETE-B：旧实现的最终门禁仍看到 `COMPLETE`，先新增旧 candidate 和 receipt，最后才因
  receipt 与当前 raw 不一致失败；
- candidate false → true：旧实现接受绕过 journal lock 出现的合法 candidate，并新增 receipt 后成功；
- candidate true → false：旧实现把被移除的 candidate 静默重建，再新增 receipt 后成功。

三个重试路径的 connector、monotonic、sleep 都为 `0/0/0`。红灯证明问题不是网络副作用，而是首次 journal
证据发布前的 identity 和存在性门禁不完整。

## 2. P1：commit 前重验同一份 raw 证据

### 2.1 现象、根因与规则

`COMPLETE` 只描述物理布局，不代表 raw snapshot identity。第一次 `verify_request` 和 candidate 构造完成后，
如果 raw pair 被公开 `RawStore.write_request` 替换为内容不同但同样合法的 COMPLETE pair，仅复查状态字符串
不能证明 candidate 仍绑定当前证据。

应遵循的规则是：首次 candidate 发布前，必须重新读取当前 raw 的物理和逻辑证据，并证明它仍与已构造
candidate 完全一致；最终 receipt verifier 的失败不能代替首次持久化前门禁。

### 2.2 最小修复

RECOVER 且 candidate 不存在时，执行顺序现在是：

1. 第一次严格 `verify_request`，读取 Parquet、执行字段/行数策略验证并构造 candidate；
2. 发布前确认 raw 布局仍为 COMPLETE；
3. 调用生产 verifier `_verify_candidate(spec, candidate, raw_store, policy)`；
4. verifier 再次严格读取 `RequestRawSnapshot` 和 Parquet，重建 candidate 并进行 dataclass 全等比较；
5. 立即复查 candidate 路径仍不存在，再调用既有 `_write_dataclass_once` 不覆盖写。

全等比较覆盖 candidate 已绑定的 request/endpoint/parameters、snapshot/path、raw file hash、metadata hash、
size、rows、columns 和规范化 response content digest。任一不同都在 candidate/receipt 写入前以
`CANDIDATE_RAW_EVIDENCE_MISMATCH` 或相应稳定 verifier 错误 fail-closed。

### 2.3 反例结果与边界

测试在第一次 verify/build 后、最终 publication recheck 位置把 COMPLETE-A 删除，再通过公开 RawStore 写入
列契约相同但单元格不同的 COMPLETE-B。修复后稳定返回 `CANDIDATE_RAW_EVIDENCE_MISMATCH`，candidate 和
receipt 均不存在，API/clock/sleep 为 `0/0/0`。

本修复处理重验前发生的受控替换，并在重验通过后立即做 candidate existence 检查和不覆盖写；不承诺消除
重验完成后的纳秒级外部恶意替换，也不宣称提供跨 raw/journal 的通用事务隔离。

## 3. P2：消费冻结的 candidate existence

### 3.1 现象、根因与规则

`_NoReceiptPreflight` 已冻结 `candidate_exists`，但四次返工只把 `mode` 传入恢复层，导致恢复执行期把 candidate
出现或消失解释为合法的新闭包。冻结的决策字段必须实际参与执行期比较；存在性漂移应在任何当前执行器的
candidate/receipt 新写入前失败。

### 3.2 最小修复

`_recover_candidate` 新增必填参数 `expected_candidate_exists`：

- no-receipt 分支传入 `preflight.candidate_exists`；
- committed receipt 分支固定传入 `True`；
- NETWORK 由 `_NoReceiptPreflight` 不变量固定为 `False`。

恢复入口通过 `_regular_file_exists` 获取当前值并与冻结值比较，不一致立即返回
`REQUEST_EVIDENCE_CLOSURE_CHANGED`，不读取漂移后的 candidate 继续恢复，也不重建已消失的 candidate。

### 3.3 双向反例

- false → true：受控动作绕过正常 journal writer lock 发布合法 candidate。修复后外部 candidate bytes 原样
  保留，当前执行器不新增 receipt；
- true → false：受控动作绕过 lock 移除 candidate。修复后不静默重建 candidate，也不新增 receipt。

两种情况均返回 `REQUEST_EVIDENCE_CLOSURE_CHANGED`，connector/clock/sleep 为 `0/0/0`。P2 仍按独立复验
定义记录为防御性边界：正常项目 writer 应遵守 journal 全局锁，复现明确绕过该锁。

## 4. 回归覆盖

新增三项测试之外，完整 B2A/storage 定向套件继续覆盖：

- 前述 NETWORK → COMPLETE、RECOVER → ABSENT/EMPTY、candidate publication 前状态漂移；
- 9 类非法 raw 布局和 COMPLETE/intent/candidate 静态闭包；
- 4 个合法及非法 enum、exact-bool、mode/closure 的 preflight 直接构造；
- forged request/batch、journal 非普通文件、不覆盖写；
- mkdir/open/close/link/fsync/lock cleanup、Parquet 和 classifier/provider 错误脱敏；
- `RawStore.write` legacy API 与 request raw 幂等、单边/symlink 行为。

## 5. 验证结果

全部命令在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py -k "same_raw_evidence or candidate_appearance or candidate_disappearance"
3 passed, 113 deselected in 1.77s

python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
124 passed in 7.26s

python -m pytest -q
425 passed, 1179 warnings in 14.19s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 是既有 Pandera/Polars deprecation warning，本轮未修改其来源。

## 6. 状态

- 新 P1/P2 的实现者自测已通过；
- 未修改独立报告、路线图、Gate 或 SSOT 状态；
- 当前只能写“等待独立五次复验”；
- 独立复验通过后仍需主 Agent 最终验收，不得据此宣称 B2A、B2、G1 或 M3 通过。
