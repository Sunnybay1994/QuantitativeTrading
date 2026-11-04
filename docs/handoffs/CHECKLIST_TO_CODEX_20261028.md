# 工作清单交接 → Codex（2026-10-28）

> 历史交接记录。2026-11-04 已取消 Concord；原任务认领、消息和角色分派要求失效。当前执行以用户指令及 [工作清单_20261102](../工作清单_20261102.md) 为准。

来源：Cursor Developer `cursor:8e0e1ef7`  
目标文档：`docs/工作清单_20261027.md` + `docs/任务书规范.md`  
仓库：`F:\AI_Coding\QuantitativeTrading`（branch `main`，勿 push）

## 请 Codex 接手的目标

按工作清单完成 **F0–F3 / S1–S4 / D1–D2** 共 8 项。每项五条验收全满足才算完成；本轮 **11-10** 由 `quant doctor` 总验收，**禁止手写闭合路线图**，**禁止 UpdateGoal complete**（除非真全部满足）。

## 当前进度（以磁盘与计划任务为准，勿凭记忆）

| 项 | 状态 | 关键 commit / 证据 |
|---|---|---|
| F0 | 通过 | 工作区曾收口；注意 live writer 脏文件勿扫进提交 |
| F1 | **waiting:2026-10-29** | doctor 已实现；需 DailyObservation **连续两次** LastTaskResult=0 且产物含 doctor 页。日历未到不得写通过 |
| F2 | **waiting:2026-11-08** | 代码侧多已修；IntelWeekly 仍 result=1（下次 11-01）；batch_000076 有 `input_invalidation.json`，**不会再被调度跑完**；活批已到 000078 |
| F3 | 通过 | `c93ec89c`；quarantine 48；排行榜 Q10 一行 PAPER_CANDIDATE |
| S1 | 通过 | `8e33e140` |
| S2 | 通过 | `1f089903` |
| S3 | **waiting:2026-11-03** | `733df3fc` 影子接线；需 11-02/11-03 真实成交与 DailyObservation result=0，勿伪造 |
| S4 | 通过 | `8db82de0`；覆盖停在 2025-07、budget stop；ledger 在 **2026-10** 非 11 月；勿再烧 event_extract |
| D1 | **waiting:2026-11-06** | 三段任务已有 result=0；coverage 多日 ≥门槛；仍需连续两次 + 日历 |
| D2 | 通过 | `9577c32c`，文档 ≤10KB |

近期本会话提交（勿重复做）：
- `e9ed2098` 晚到相同预测去重
- `6b8ac2eb` 核验输入即可发早盘上下文
- `30177793` DailyObservation `-WaitForWriter`；baostock 工作日 21–23 defer
- `a6608df4` doctor 忽略 Disabled 任务（NightlyResearch）
- `5432614b` 清单进度笔记

## 进行中：今晚日更（优先处理）

- 任务：`QuantitativeTrading-DailyObservation` **仍 Running**（2026-10-28 21:30，result=267009）
- 目录：`artifacts/daily/sue_v2/2026-10-28_213437_920541`
- `summary.json`：`status=incomplete`，`dependencies=complete`，**`model=running`**
- `model/refresh_progress.json`：**卡在 `financials`**，`started_at=21:35:22`，`updated_at` 未再前进
- 进程：`43112` = `quant research daily --to 2026-10-28`；子进程 **`43684`** = `run_daily_observation`（约 idle，CPU 增量≈0）
- 财务产物已写到 `artifacts/data/financial_updates_v3_20261028` 的 `_000`…`_007`（最晚约 21:48），之后疑似卡在后续 period / `refresh_quarter` / 切 snapshot
- **不要**把手工重跑记成 F1 生产回执；**先诊断再决定是否停进程**（停的话记清原因，等调度自己再跑）
- 配置注意：今晚跑的是 `configs/research/daily_observation_q2_sue_v2_20260930.toml`（不是 20260912）

## 硬注意事项（必须遵守）

1. **日历门槛**：F1≥10-29、F2≥11-08、S3≥11-03、D1≥11-06；未到只能 **waiting**，不得写「通过」。
2. **生产回执**：接调度的只认 `Get-ScheduledTaskInfo` 连续两次 `LastTaskResult=0` + 对应日期产物；**手工跑不算**。
3. **安全**：无前视；raw 不可覆盖；`auto_trade=false`；真金下单须用户确认；凭据不进 Git；不改 §1.2 门槛。
4. **batch_000076**：有 `FROZEN_INPUTS_INVALIDATED` 回执，调度会跳过；**勿删/勿改**该回执去“复活”076；活批是后续 batch。
5. **S4**：勿再开 LLM 回填；summary 里 `llm_calls=0` 是缓存重写计数，真实调用看 ledger/log。
6. **Git**：只提交当前任务相关文件；live mining/gp_hints/daily 脏树勿扫进提交；**不要 push**；PowerShell 提交用 here-string 管进 `git commit -F -`。
7. **Python**：研究/测试用 `D:\Miniforge3\envs\m3chain312\python.exe` + `PYTHONPATH=src`；调度用 `D:\Miniforge3\python.exe`。
8. **协作**：以当前用户指定的执行会话为准；对外发送仍须用户授权。
9. **机器**：盘后 CN 15:10 / HK 16:40 / US 次日 06:00；日更 08:30/17:30/21:30；勿随意休眠。
10. **一次只开一项**；实验结果不手写文档，机器产物为准。

## 建议 Codex 下一步顺序

1. 诊断并处理卡住的 `financials`（43684），让今晚调度日更能结束；看是否出现 LastTaskResult=0 + doctor 页。
2. 仍保持 F1 **waiting:2026-10-29**，凑齐连续两次 result=0。
3. F2：盯 IntelWeekly 11-01；勿追求“完成 076”。
4. D1：继续积累 coverage 与连续两次 result=0，勿手跑。
5. S3：等到 11-02 自然成交。
