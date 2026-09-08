# M3 G1-P3 B2C 执行事实：主 Agent 最终验收报告

日期：2026-07-14  
结论：**P3/B2C 子包通过主 Agent 最终验收**  
边界：不宣称 B2、G1、M3 或任一 Gate 完成；下一包为 P4A

## 1. 验收链路

- 原任务：[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](M3_G1_P3_B2C执行事实外部闭环任务单.md)
- 原实现：[`M3_G1_P3_B2C执行事实交付报告.md`](M3_G1_P3_B2C执行事实交付报告.md)
- 首轮独立初验：[`M3_G1_P3_B2C执行事实独立初验报告.md`](M3_G1_P3_B2C执行事实独立初验报告.md)，结论不通过
- 主 Agent 返工设计：[`M3_G1_P3_B2C执行事实初验一次返工任务单.md`](M3_G1_P3_B2C执行事实初验一次返工任务单.md)
- 原实现者返工：[`M3_G1_P3_B2C执行事实初验一次返工交付报告.md`](M3_G1_P3_B2C执行事实初验一次返工交付报告.md)
- 全新外部复验：[`M3_G1_P3_B2C执行事实初验一次返工独立复验报告.md`](M3_G1_P3_B2C执行事实初验一次返工独立复验报告.md)，结论通过

实现和复验分别使用不同 Cursor 会话，模型均为 `cursor-grok-4.5-high`；项目命令均在 WSL Miniforge `base`
运行。主 Agent 未在返工阶段代替外部实现者修改生产代码。

## 2. 阻断项与关闭证据

首轮初验发现 P1-1：合法 MATCHED 行只改 `event_ids_sha256` 并同步整表 `evidence_sha256` 后，构造与公开
verifier 仍通过。根因不是少一个比较，而是 result 未保存可供 verifier 重算 event-set hash 的事件 ID 集合。

返工后的 reconciliation evidence 新增规范 `event_ids_json`：排序、去重、小写 64 hex、无多余空白或转义；
`event_count` 与 `event_ids_sha256` 均由解析结果独立重算。NO_EVENT 精确保存 `[]`，构造与公开 verifier 共用同一
验证体。只改 json/count/hash 中任一字段，即使同步整表 digest，也会稳定返回
`G1_CORPORATE_ACTION_RECONCILIATION_INVALID` 且无异常链或敏感输入泄露。

信任边界保持明确：把 json/count/hash/digest 一起替换为另一套内部自洽结果，单靠自包含 verifier 无法证明来源；
P4A 必须从冻结 plan、verified responses 和输入表重新执行 P2/P3 后比较，不能只接收自报 result。

## 3. 主 Agent 未公开反例

主 Agent 使用临时测试文件执行并在验收后删除，未把验收探针留入生产测试集：

1. 用另一合法 64 hex event ID 替换 MATCHED 的 `event_ids_json`，保持事件数量不变、保留旧 event-set hash，
   同步整表 digest：构造和绕过构造后的公开 verifier 均拒绝。
2. 把 event-set hash 错算为“直接对 `event_ids_json` 文本做 SHA-256”，同步整表 digest：两条路径均拒绝。
3. 使用 65 位小写 hex ID 并同步整表 digest：两条路径均拒绝。

结果：**2 个主验测试通过**（第二个测试包含两种攻击）；所有失败均为稳定错误码且 `__cause__ is None`。
临时探针第一次因测试目录未加入模块搜索路径而在 collection 阶段失败；修正仅限临时 harness 后重跑通过，未涉及
生产缺陷或生产修改。

## 4. 正式验证

全部命令经 `wsl.exe` 在 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 使用
`/home/mabw/miniforge3/bin/conda run -n base`：

| 验证 | 主 Agent 结果 |
|---|---|
| P3 及上游定向矩阵 | **319 passed** |
| 全量 pytest | **609 passed** |
| Ruff | **All checks passed** |
| mypy | **76 source files，0 issues** |

测试产生的 Pandera/Polars deprecation warnings 为既有告警，不影响本包主业务闭环；WSL localhost proxy 提示也不
影响离线测试结果。本轮未联网、未读取 token、未访问 `_old/`、未写 raw/clean 数据。

## 5. 最终判断与后续

P3/B2C 的价格限制覆盖、公司行动选版、复权因子 reconciliation、lineage、Schema 与自包含身份闭包满足冻结
契约，P1-1 已关闭，允许作为 P4A 的已验收上游。

下一步按 [`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)
执行 P4A 外部实现—独立初验闭环。P4B 跨源证据、P4C 不可变发布、B2/G1/Gate 均仍未完成。
