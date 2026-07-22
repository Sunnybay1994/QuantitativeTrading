# M3 G1-R0 主 Agent 最终验收报告

日期：2026-07-15  
状态：**主 Agent 最终验收通过；R0 完成，不关闭 B4/G1/M3 Gate**

## 1. 结论

R0 的权威 SH/SZ 日历前置和真实数据源烟测已经形成完整职责闭环：外部实现、全新外部独立初验和主 Agent
终验均通过。现有数据足以解析信号域 `2016-01-04..2026-06-26` 的 60-session warmup 与 10-session tail；
七个 Tushare G1 端点和 BaoStock reference bar 均有真实只读证据。

目标运行环境的 `renameat2(RENAME_NOREPLACE)` 能力仍为 `false`。因此当前只能继续实现并运行到
PREPARE/verify，不能正式 PUBLISH，也不能据此构造可供 G2A 消费的 `VerifiedG1Release`。禁止用普通 rename、
test monkeypatch 或 fake release 绕过该门禁。

## 2. 职责闭环

- 实现：[`M3_G1_R0权威日历补全与真实源烟测交付报告.md`](M3_G1_R0权威日历补全与真实源烟测交付报告.md)，
  状态“待独立初验”。前一无报告实现会话按
  [`M3_G1_R0二次执行无报告收尾返工任务单.md`](M3_G1_R0二次执行无报告收尾返工任务单.md) 重新执行，
  旧 stdout 未被采信。
- 独立初验：[`M3_G1_R0权威日历补全与真实源烟测独立初验报告.md`](M3_G1_R0权威日历补全与真实源烟测独立初验报告.md)，
  全新 `cursor-grok-4.5-high` 会话结论“初验通过（可交主验）”。首次初验会话只留下骨架后超时，已单独记录，
  不算通过或合同失败。
- 主验：主 Agent 独立运行 WSL base 探针并执行本报告的范围、凭据和一致性核对。

## 3. 数据与真实依赖证据

| 项 | 最终证据 |
|---|---|
| SH/SZ 自然日历 | 各 4383 行、4383 唯一日期，范围均为 `2015-01-01..2026-12-31` |
| 沪深一致性 | 日期域 mismatch=0，`is_open` mismatch=0 |
| history window | `2015-10-09..2026-07-10`；外部实现、独立初验手工重算和主验三方一致 |
| 七个 Tushare 端点 | 实现会话全部 PASS；独立初验另发起 `dividend` 全历史请求，53 行、16 列、未触阈值 |
| BaoStock | 实现与独立初验均重新 login/request/logout，`000001.SZ@2026-01-05` 返回 1 行 finite 数据 |
| 主验真实请求 | 主 Agent 另发起 Tushare `daily` 请求，返回唯一 `000001.SZ@2026-01-05` 行且列顺序精确 |
| 发布能力 | 实现、独立初验目标文件系统和主验公共 probe 均为 `false` |

主验临时脚本在完成后已删除；没有把 token、配置或绝对路径写入产物。

## 4. 测试与静态检查

实现报告记录：

- 定向 pytest：`186 passed`；
- 全量 pytest：`798 passed`；
- Ruff：通过；
- mypy：79 个 source files 通过。

独立初验没有把实现报告复述当成唯一证据，而是重新计算日历、重新访问 Tushare/BaoStock、重新 probe，并
增加 59 warmup/9 tail fail-closed 反例。主验又独立执行日历、history、Tushare daily 和 renameat2 一体探针，
退出码为 0。

## 5. 安全与范围

- 实现报告、初验报告和本日新增 Tushare calendar JSON 的 token assignment、Bearer、api_key、Windows 用户
  路径、WSL home、DrvFS 路径扫描为 0 命中。
- 项目 Git 元数据当前为空，WSL/Windows 都不能使用 `git status`；主验改用项目内时间窗和路径分类核对。
- 排除缓存后，R0 数据变化只包含任务书允许的 Tushare calendar raw 与 SH/SZ clean 日历；没有 `src/`、
  `tests/` 或 `configs/` 变化。其余近期 Markdown 是主 Agent 的任务书、准则和调度 SSOT 更新。
- 外部实现和独立初验均未修改 token 配置，也未把凭据放入 stdout 摘要或报告。

## 6. 非阻断债务与下一步

1. Pandera Polars backend 在重 Schema 路径触发约 79 万/98 万条 `DeprecationWarning`，令定向/全量 pytest
   分别耗时约 36/51 分钟。初验确认主导指纹是 Pandera 内部对 Polars `concat` 的弃用警告，当前没有断言或
   数据正确性失败，故作为 P2 性能/可读性债务记录，不返工 R0；后续应单独治理，不能长期用全局忽略掩盖
   其他 warning。
2. 宿主 Windows Miniforge profile 有 `bad marshal data` 噪声，但实际项目命令均在 WSL base 中成功执行；
   该宿主噪声不属于项目运行时，也不改变 R0 结论。
3. 下一组可并行任务是 R1A 运行身份/计划骨架与 R1L 崩溃安全 journal 写锁。两包完成外部实现—独立初验
   闭环并经主验后，才能进入 R1B；正式发布能力另在 R1C PREPARE 之后解决，G2A 仍不得提前启动。

