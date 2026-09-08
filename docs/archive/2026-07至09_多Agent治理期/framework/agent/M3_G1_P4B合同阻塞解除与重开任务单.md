# M3 G1-P4B：合同阻塞解除与外部实现重开任务单

日期：2026-07-14  
状态：主 Agent 已复核首轮阻塞证据并修订合同；返回原外部实现会话继续 P4B  
原任务书：[`M3_G1_P4B跨源证据外部闭环任务单.md`](M3_G1_P4B跨源证据外部闭环任务单.md)  
阻塞报告：[`M3_G1_P4B跨源证据交付报告.md`](M3_G1_P4B跨源证据交付报告.md)

## 1. 现象

P4B 冻结 `CrossSourceReconciliationBundle.issues: tuple[G1QualityIssue, ...]`，且只允许
`CROSS_SOURCE_INCOMPLETE`、`CROSS_SOURCE_MISMATCH`。现行 `G1QualityIssue.__post_init__` 只接受
`m3_g1_candidate.py::_ISSUE_CODES`，该集合没有这两个码，因此任一合法跨源 issue 都无法构造。

## 2. 根因

主契约 [`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.10 已把两个跨源码纳入 G1 issue 全集；P4A 实现阶段
只冻结了主源 audit 所需的子集，P4B 任务书随后又错误禁止任何 `m3_g1_candidate.py` 修改。泛型值对象的合法码
边界与分阶段实现边界被混为一谈，形成不可同时满足的合同。

## 3. 应遵循规则与主 Agent 决策

`G1QualityIssue` 是 G1 共用的结构化问题值对象，不是 `audit_g1_candidate` 私有类型。合法码全集以主契约 §4.10
为准；具体函数仍只能产生其职责范围内的码。因此：

1. 允许 P4B 对 `src/quant/data/m3_g1_candidate.py` 做唯一外科式修改：向 `_ISSUE_CODES` 增加
   `CROSS_SOURCE_INCOMPLETE`、`CROSS_SOURCE_MISMATCH`；
2. 不修改 `audit_g1_candidate`，它仍不得产生跨源码；不改其他 P4A 身份、排序、passed 或失败语义；
3. 不另造平行 issue 类型，不用任意字符串或绕过构造器；
4. 历史 P4A 验收中“直接构造跨源码必须拒绝”的阶段性断言由本合同明确废止；历史报告保留，不回写成未发生。

## 4. 最小复现

阻塞报告 §2.4 已复现：两个码均不在 `_ISSUE_CODES`，构造均抛
`ValueError("G1QualityIssue code 非法")`。这不是 P4B 算法错误，而是现行枚举边界缺项。

## 5. 必须新增的回归测试

在本包允许的 `tests/unit/test_m3_reference.py` 覆盖：

1. 两个冻结跨源码均可构造、可进入 bundle，并遵循既有 exact type、排序和 passed 闭包；
2. 任意未冻结码仍被拒绝；
3. `audit_g1_candidate` 在原有合法/非法主源候选反例中只产生原主源码，不因枚举扩展改变结果；
4. reconciliation 缺行只产生 `CROSS_SOURCE_INCOMPLETE`，严格超过阈值才增加
   `CROSS_SOURCE_MISMATCH`，等于阈值不产生 mismatch issue。

不得删除、放宽或改写上游测试来掩盖回归。

## 6. 通过条件与重开方式

原实现 Agent 在同一会话继续执行原任务书全部 P4B 内容，并将原阻塞报告保留为历史证据；成功实现后另写
`docs/M3_G1_P4B跨源证据阻塞解除后交付报告.md`，链接原任务书、本任务单和原阻塞报告。完成定向/全量 pytest、
Ruff、mypy 后状态仍只能为“待独立初验/待主验”。随后必须由全新外部会话按原任务书独立初验矩阵验证。

本任务单不放宽任何 identity、preflight、journal、receipt、reconciliation、脱敏或零网络测试要求，也不表示
B4/G1/M3/Gate 通过。
