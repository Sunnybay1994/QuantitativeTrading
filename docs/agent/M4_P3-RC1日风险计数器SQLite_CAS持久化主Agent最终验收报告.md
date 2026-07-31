# M4 P3-RC1：日风险计数器 SQLite CAS 持久化主 Agent 最终验收报告

日期：2026-07-31（Asia/Shanghai）

结论：**隔离分支通过，待 G1 发布后合入主线。**

分支：`codex/m4-risk-counters`

基线：`6b64973`

## 1. 交付内容

- `DailyRiskCounters` 增加严格 canonical JSON 序列化、反序列化和版本化 SHA-256 identity；
- migration v3 新增每 session 唯一的 `daily_risk_counters`；
- repository 增加认证读取与 compare-and-set：
  - 显式首次初始化；
  - 精确已提交重试 no-op；
  - stale expected identity 拒绝；
  - 与 command / aggregate / outbox 共用现有事务；
- getter 验证 key、payload、identity 和 UTC `updated_at`，损坏行 fail closed；
- schema version 从 2 升至 3，v1/v2 数据按顺序迁移且旧 outbox 行语义不变。

## 2. 返工闭环

独立只读初验第一次发现两个 P2：

### P2-1：伪造 session date 泄漏实现异常

- 现象：`object.__setattr__(counters, "session_date", 7)` 后出现原始 `AttributeError`。
- 根因：serializer 在重新验证前调用 `.isoformat()`。
- 应遵循规则：所有伪造计数器必须在 SQL 前稳定失败。
- 修复：持久化字典生成前重新执行 dataclass 不变量验证；store 在异常块外映射
  `COUNTERS_INVALID`。
- 新增测试：伪造 session date，断言错误码、空 cause/context 和数据库无行。

### P2-2：深度畸形 JSON 泄漏 RecursionError

- 现象：深度 10,000 的数组 payload 读取时出现原始 `RecursionError`。
- 根因：JSON 解码和 row 认证均未覆盖结构深度异常。
- 应遵循规则：任意非规范持久 payload 都必须稳定映射 `ROW_CORRUPT`，但不得吞
  `KeyboardInterrupt` / `SystemExit`。
- 修复：仅增加 `RecursionError` 到结构解析异常集合，并在异常块外统一映射。
- 新增测试：直接篡改 SQLite payload，断言 `ROW_CORRUPT` 且 cause/context 为空。

同一独立只读会话复验两个原始最小复现和新增测试，结论通过，当前未发现剩余 P1/P2。

## 3. 验证证据

Windows 原生 Miniforge：

- 新增反例：`13 passed`
- 风险 + store + 新 CAS：`197 passed, 5 skipped`
- Ruff：通过
- mypy：3 个生产目标通过

WSL Miniforge base：

- 风险 + store + 新 CAS：`202 passed`
- Ruff：通过
- mypy：3 个生产目标通过

Windows 的 5 个 skip 是既有平台权限相关用例；WSL 同组全部执行。

独立只读复验：

- Windows 新测试：`13 passed`
- 伪造 session date 原始复现：
  `COUNTERS_INVALID`, cause/context 均为空，row 不存在
- 深度 JSON 原始复现：
  `ROW_CORRUPT`, cause/context 均为空
- `git diff --check`：通过

## 4. 不变量核对

- stale worker 不能覆盖胜出 worker；
- 成功提交后的相同状态重试不改变 `updated_at`；
- 事务异常时 command、aggregate、outbox 和 counters 全部回滚；
- 重启后 counter、identity 和 timestamp 保持；
- bool、负数、NaN 和伪造日期均在 SQL 前失败；
- identity、payload、timestamp 任一篡改均 fail closed；
- 不引入平台文件锁、路径或时区差异。

Decimal 的文本 scale 按现有 execution identity 约定保留并参与 identity；例如 `1.0` 与 `1.00`
是不同持久表示。数据库 round-trip 保留该表示，本切片不另建数值规范化口径。

## 5. 通过边界与剩余风险

本结论只关闭 P3-RC1 隔离实现：

- cancel 业务路径尚未接入并持久增加 `cancel_count`；
- PaperGateway、service、reconciliation、操作 CLI、日报和通知仍未实现；
- M4 最终要求的连续至少 28 天 PAPER/SHADOW 真实时间证据尚未开始；
- 合入主线后仍需在合流状态复跑定向验证，之后才能更新路线图状态。
