# M1 SSE-E1 港股通事件方向映射修复 — 独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（未参与实现；cursor-grok-4.5-high）  
合同：[M1_SSE-E1港股通事件方向映射修复任务单.md](M1_SSE-E1港股通事件方向映射修复任务单.md)  
交付：[M1_SSE-E1港股通事件方向映射修复交付报告.md](M1_SSE-E1港股通事件方向映射修复交付报告.md)  
范围纪律：生产代码 / 实现测试 / 配置 / data 严格只读；本会话唯一写入为本报告。

## 结论

初验通过（EXIT 0）。冻结合同与实现、定向验证、未公开 /tmp 反例一致。  
不宣称既有 clean 事件已修复，不宣称 M1 Gate 终验通过；后续仍须单独授权 raw 保留、clean 原子重建与历史区间再发布。

## 标准—证据—结论映射

| 冻结合同项 | 证据 | 结论 |
| --- | --- | --- |
| 去空白后仅「调进」→ADD、「调出」→REMOVE | map_sse_events：strip_chars + is_in(["调进","调出"]) 前置校验；合法映射 when == "调进" → ADD；实现测 add_and_remove / strips_whitespace / mixed_legal_batch 均绿 | 通过 |
| null/空/01/02/英文 ADD·REMOVE/未知中文整批拒绝 | 返回 DF 前 raise ValueError("SSE_EVENT_ADJUST_TYPE_INVALID")；parametrize 覆盖上述非法值；rejects_legacy_01_even_in_mixed_batch 绿 | 通过 |
| 稳定脱敏、异常无原值回声 | 异常消息恒为精确字符串 SSE_EVENT_ADJUST_TYPE_INVALID；实现测 match=^SSE_EVENT_ADJUST_TYPE_INVALID$；/tmp 反例对原 token 做 in msg 断言未命中 | 通过 |
| 无默认 REMOVE（未知不得静默成 REMOVE） | 未知值在 select 之前整批拒绝；.otherwise(REMOVE) 仅在校验通过后作用于已确认的「调出」，不会落到未知值 | 通过 |
| 其他字段/route/source/security_type/published_date 语义未漂移 | select 列集仍为 route=SH_CONNECT、VALID_DATE→effective_date、SECURITY_CODE+".HK"、name_*、_security_type、FILE_DATE→published_date、source=sse；Schema 校验仍通过；未改 eligibility.py / Schema；SZSE mapper 范围外保持原样 | 通过 |
| 状态机经 mapper、不绕过 | test_sse_event_state_machine_add_remove_readd_via_mapper：先 map_sse_events 再 build_membership_intervals；eligibility 单测 4 passed | 通过 |
| 禁止网络/data/全量 pytest/Git | 本初验仅跑任务单四项定向命令 + /tmp 反例；未触碰上述禁止项 | 通过 |

## 定向验证（WSL Miniforge base）

工作目录：/mnt/g/BaiduSyncdisk/wsl/Cursor/quant  
调用：/home/mabw/miniforge3/bin/conda run -n base <cmd>

| 命令 | 结果 | EXIT |
| --- | --- | --- |
| python -m pytest tests/unit/test_connect_market.py -q | 17 passed（pandera DeprecationWarning 可忽略） | 0 |
| python -m pytest tests/unit/test_eligibility.py -q | 4 passed | 0 |
| ruff check src/quant/data/connect_market.py tests/unit/test_connect_market.py | All checks passed! | 0 |
| mypy src/quant/data/connect_market.py | Success: no issues found in 1 source file | 0 |

## 未公开对抗反例（实现者未使用）

脚本：/tmp/m1_sse_e1_adversarial_check.py（不入库；WSL base 执行）  
相对实现测差异：混批未知值不用 "01"，改用「扩容」、「转入」；并显式断言调用方 holder 在异常后仍为空（无部分 DataFrame）。

| 反例 | 期望 | 结果 |
| --- | --- | --- |
| ADJUST_TYPE=["调进","调出","扩容"] 同批 | 整批 ValueError("SSE_EVENT_ADJUST_TYPE_INVALID")；调用方得不到部分 DF；消息无原值回声 | PASS |
| ADJUST_TYPE=[" 调进 ","调出"," 转入 "] 同批 | 同上 | PASS |
| 对照：["调进","调出"] | action == ["ADD","REMOVE"] | PASS |

汇总：ALL_ADVERSARIAL_PASSED，EXIT_ADV:0。

## 范围与已知限制

- 白名单外文件：本会话未修改任何生产/测试/配置/data。
- 交付报告自测结论与本初验定向结果一致，经独立复跑与未公开反例加严后仍成立。
- 已知限制（任务书已冻结）：磁盘既有 clean 事件仍可能全为历史错误 REMOVE；本包零网络 mapper/测试修复不等于数据重建。
- 下一步：主 Agent 终验（契约/文档一致性）；另案设计并授权 clean 原子重建后方可宣称事件侧恢复。

## 退出码

0（初验通过，进入主验前置已满足）