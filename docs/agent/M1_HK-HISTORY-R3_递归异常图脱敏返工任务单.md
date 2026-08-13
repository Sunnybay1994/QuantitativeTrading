# M1 HK-HISTORY-R3：递归异常图脱敏返工任务单

日期：2026-08-11  
状态：**实现已交付；待未参与本轮实现的全新外部初验 Agent 复验**  
交付报告：[`M1_HK-HISTORY-R3_递归异常图脱敏返工交付报告.md`](M1_HK-HISTORY-R3_递归异常图脱敏返工交付报告.md)  
前置：[`M1_HK-HISTORY-R2_无行情事实与零网络恢复独立初验报告.md`](M1_HK-HISTORY-R2_无行情事实与零网络恢复独立初验报告.md) 结论 **FAIL**

## 1. 现象—根因—规则

- 现象：对 recover/evidence 读取注入包含 token 与绝对路径的递归异常后，public `HKHistoryBackfillError` 文本虽为 `HK_HISTORY_REFERENCE_INVALID`，但 `__context__` 仍指向 hostile `RuntimeError`；递归异常图和 traceback 可泄露 marker。
- 根因：R2 recover/evidence/seed 路径在 active `except` block 内直接 `raise ... from None`。这只抑制展示并清除显式 cause，不保证 `__context__ is None`。
- 应遵循规则：所有 public 失败必须在退出 active handler 后抛稳定 code；`__cause__` 与 `__context__` 均为 `None`，异常文本、repr、format traceback 和递归图均不得包含 token、供应商原文或绝对路径。
- 同模块 finalize-v3 loader 已存在布尔失败标记、退出 except 后再 raise 的已验收模式；本包复用语义，不创建平行异常系统。

## 2. 最小返工范围

1. 收紧 `recover_existing_hk_history_requests` 可达的 evidence projection、seed、anchored read、journal binding/receipt/raw recovery 异常翻译。
2. 同步收紧直接 public `load_hk_no_trade_evidence`、v2 plan/load/recover 的同类 stable error 边界，避免同一 R2 API 因入口不同而泄漏。
3. 保持既有稳定错误码分类：plan conflict/incomplete/raw invalid/reference invalid 不得被一律吞成同一码。
4. 不改变 bar/no-trade 互斥、evidence identity、v2 plan/journal/receipt、attempt/replay、network_requests=0、clean 零写或正式 finalize 语义。
5. 禁止记录/回显 caught exception；只保留内部布尔/枚举失败状态，在 handler 外抛稳定错误。

若要修改 public API、schema、journal bytes、receipt identity、正式 data 或网络路径，立即停止并报告，不得扩大返工。

## 3. 必须新增的正式回归

至少覆盖：

1. `_read_anchored_path` 抛 `RuntimeError(HOSTILE_TOKEN + absolute_path) from ValueError(HOSTILE_TOKEN)`；public recover 返回 exact `HK_HISTORY_REFERENCE_INVALID`，cause/context 均为 `None`，递归图/traceback/repr 无 marker/path。
2. hostile 异常分别发生在 evidence projection、seed load、journal binding/receipt/raw read 的可达位置；验证错误分类不漂移。
3. 直接 `load_hk_no_trade_evidence` 的 hostile read/JSON/projection 异常同级脱敏。
4. 合法 recover→ABSENT→replay、bar∩no-trade、01065 无 licensed evidence、合法不同 closure 整体重签、binding alias/same-bytes inode、attempt 预植与零网络/零 clean 对照保持通过。
5. hostile marker 断言必须递归遍历 `__cause__/__context__` 并格式化 traceback，不能只检查 `str(public_error)`。

## 4. 白名单

允许修改：

- `src/quant/data/hk_history_backfill.py`
- `tests/unit/test_hk_history_backfill.py`
- `docs/agent/M1_HK-HISTORY-R2_无行情事实与零网络恢复任务单.md`（只更新状态/链接）
- 本任务单（只更新状态）
- 唯一交付报告：`docs/agent/M1_HK-HISTORY-R3_递归异常图脱敏返工交付报告.md`

禁止修改其他 production/tests/config/docs、正式 `data/`/journal/clean、任何其他 worktree；禁止联网、消耗 Tushare/HKEX 额度、add、commit、push。

## 5. 验证与通过条件

1. Windows 先跑新增 hostile 节点与 R2 recover 聚焦节点；再跑任务单原定向组。
2. WSL Miniforge `base` 在 `/mnt/f` 跑同组；如实记录 DrvFS，不能宣称 ext4 Gate。
3. 双平台定向 Ruff/mypy/cold import；scoped `git diff --check`。
4. 不运行真实数据、不联网、不创建正式 v2 journal/clean。

只有满足以下条件才可交独立复验：

- public recover/evidence/seed 的 hostile 递归异常图完全脱敏；
- R2 初验其余 6 组独立反例不回归；
- Windows/WSL 定向测试与静态检查通过；
- 生产/测试改动仅限白名单，journal/receipt/identity 字节合同不变。

实现后必须由未参与 R3 实现的全新 `cursor-grok-4.5-high` 会话独立复验；初验 PASS 后仍须主 Agent 终验。本包不解锁 licensed `01065`、正式 HK60、M1 或 ext4 Gate。

