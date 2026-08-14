# M1 U0C-R3：五日自然窗口终审任务单

日期：2026-08-12  
状态：**合同已冻结；当前 4/5；2026-08-14 自然任务结束前禁止执行终审**
设计依据：[M1_U0C-R3五日自然窗口终审预冻结设计审计报告.md](M1_U0C-R3五日自然窗口终审预冻结设计审计报告.md)

## 1. 唯一目标

在 2026-08-14 的自然任务结束后，以两个互不替代的证据轴判断 R3 窗口是否真正达到 5/5：

1. **Scheduler 轴**：五个注册任务定义未漂移、均在合同日 21:30 自然窗口完成且结果为 0，没有正面人工
   Run/重注册证据；
2. **数据闭包轴**：五份日 JSON exact、五份 daily receipt 与 raw/quality 字节闭包均由零网络
   `audit_daily_streak` 验真。

两轴同时 PASS 才可写 U0C-R3 5/5。本任务只关闭连续调度子 Gate，不自动关闭 HK60、复权、正式许可、M1
整体 Gate 或工作树合流问题。

## 2. 当前不可预支状态

截至 2026-08-14 00:38 +08:00，08-10、08-11、08-12、08-13 可暂记 4/5；四项
`LastTaskResult=0`，且 `LastRunTime` 均为各自合同日 `21:30:30+08:00`。08-13 正式日志为
`2026-08-13.json`，其 SHA-256 为
`f104f90f1423c5df63ddd0911e0d513dbb64cee3d34f8751bbbcebc03957edfd`；日志绑定的 run ID 为
`36a94469c5d795b39d36046e471e6a0d608479289e3023807e943c967e11dcd4`，receipt SHA-256 为
`aeaf384f948936e8c904ff81b0d5e268fdec952d342961508da600fd3502d796`。08-14 仍为 `Ready` 和哨兵
`LastRunTime`，下一次自然触发为 2026-08-14 21:30:30。禁止手工触发、补跑或提前计数；完整数据闭包
终审仍只能在 08-14 自然任务结束后执行。

2026-08-14 17:47 的终审前只读检查发现，Windows checkout 曾把已注册 runner 的 LF 字节展开为 CRLF：
物理 SHA 变为 `7f1aff00...e2`，WSL `bash -n` 在 `case ... in\r` 处失败。Git 索引中的原始 blob 仍精确为
注册 SHA `bdedb953...02c`，因此本轮没有修改脚本逻辑、没有重注册或触发任务，只从现有索引恢复同一冻结
字节，并在 `.gitattributes` 对该 runner 增加 `text eol=lf`。恢复后 Windows/WSL 物理 SHA 均重新等于
`bdedb953...02c`，`bash -n` 通过。该保护提交为 `068c7e1`。

同次检查还确认 Task Scheduler 当前只可枚举 08-14 任务；08-10～13 的 live task objects 已不再存在，
Operational 历史通道仍为 disabled。注册收据、五份 registered XML、前四日日志及逐日同时期状态记录仍在。
主 Agent 已启动只读 watcher，在 08-14 自然任务完成后立即保存 live XML、`LastRunTime` 和
`LastTaskResult`；watcher 不调用注册、修改或触发 API。终审必须如实判断这些证据是否满足 Scheduler 轴，
不得因五日日志绿色而自动把缺失的 live 历史对象表述为已证明。

## 3. 冻结调度合同

- 日期：`2026-08-10` 至 `2026-08-14` 五个共同开市日；
- 任务：`QuantTrading-M1-U0C-R3-YYYYMMDD`；
- XML `StartBoundary=YYYY-MM-DDT21:30:00+08:00`；API/UI 的 21:30:30 是已知显示粒度；
- Command：`C:\Windows\System32\wsl.exe`；
- Arguments：`-d Ubuntu -- bash /home/mabw/AI_Coding_win/QuantitativeTrading/scripts/run_m1_daily_streak_20260810_20260814.sh YYYY-MM-DD`；
- runner SHA-256：`bdedb95335c8bbeaf2238a443eb321dee2a9120d9caf74d65bc7de31af2df02c`；
- symbols：runner `000001.SZ 600000.SH 00005.HK 00700.HK`，intent canonical
  `000001.SZ,00005.HK,00700.HK,600000.SH`；
- source=`tushare`，`use_adjustment_factors=false`；
- log root：`artifacts/data_quality/m1_daily_streak/20260810_20260814/`；
- 注册收据 schema=`m1-u0c-r3-task-registration-v1`；
- `registered_definitions` SHA：08-10 `3b2809bc...6d85`、08-11 `ae4ac728...ec17`、08-12
  `1bf3ba07...113`、08-13 `3224c68a...c675`、08-14 `ca240d0a...84f5`；执行时必须从注册收据读取
  完整值并逐项复核，禁止依赖本文截断显示。

live XML 整体 SHA 会包含运行状态变化，禁止与注册 export SHA 做整文件相等。live 只比较：StartBoundary、
Command、Arguments、InteractiveToken、IgnoreNew、StartWhenAvailable=true、WakeToRun=true、PT2H、无 restart/
repetition；注册快照文件本身按完整 SHA 比较。

## 4. Scheduler 轴取证

终审外部取证 Agent 只读采集每任务：State、LastRunTime、LastTaskResult、NextRunTime、live XML 语义字段；复核
注册 receipt、五份 registered XML、runner SHA。通过要求：五任务非哨兵、LastTaskResult=0、LastRunTime 落在
各合同日 21:30 窗且无跨日补启风险、定义未漂移。

Operational 历史通道当前 `IsEnabled=False`，必须记录 `U0C_R3_HISTORY_CHANNEL_DISABLED`。缺少历史事件既不能
证明人工运行，也不能证明无人干预；只接受正面可观察证据。若发现 Delete/Create、Arguments 改动、用户明确
Run 或注册快照被改，报 `U0C_R3_MANUAL_INTERVENTION_EVIDENT`，窗口失败且不得补跑计入。

## 5. 数据闭包轴命令

仅在 08-14 任务自然结束后，于正式 WSL 项目根、Miniforge base、零网络运行一次：

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading
/home/mabw/miniforge3/bin/conda run -n base \
  python -B -m quant.data.audit_daily_streak \
  --dates 2026-08-10 2026-08-11 2026-08-12 2026-08-13 2026-08-14 \
  --symbols 000001.SZ 600000.SH 00005.HK 00700.HK \
  --data-root data \
  --artifact-root artifacts \
  --log-root artifacts/data_quality/m1_daily_streak/20260810_20260814
```

期望唯一 PASS：schema `m1-daily-streak-audit-v1`、status PASS、sessions=5、dates exact 五日。FAIL 为 exit 2
且稳定码：`M1_STREAK_INPUT_INVALID`、`M1_STREAK_CALENDAR_INVALID`、`M1_STREAK_RECEIPT_INVALID`、
`M1_STREAK_LOG_INVALID`。

终审必须实际 fresh verify 五日，不得只引用预冻结报告中 08-10/11 的 SHA。

## 6. Scheduler 报告级稳定分类

- `U0C_R3_WINDOW_INCOMPLETE`：08-14 未自然结束或仍有哨兵/未来 NextRunTime；
- `U0C_R3_SCHEDULER_DEFINITION_DRIFT`：注册 SHA、live 语义或 runner SHA 漂移；
- `U0C_R3_SCHEDULER_RESULT_INVALID`：任一 LastTaskResult 非 0 或应完成日仍未运行；
- `U0C_R3_NATURAL_WINDOW_MISMATCH`：LastRunTime/日志时间不在合同窗口或非法跨午夜；
- `U0C_R3_PREMATURE_DAY_LOG`：自然触发前已有该日日志；
- `U0C_R3_MANUAL_INTERVENTION_EVIDENT`：有正面人工/重注册证据；
- `U0C_R3_EVIDENCE_TAMPER`：敌对复制、重签或时间/身份篡改；
- `U0C_R3_HISTORY_CHANNEL_DISABLED`：非 FAIL 的诚实边界。

## 7. 必测/必查反例

独立初验至少新增实现者未用子集：缺/多/重复日期；日历不是 exact 五共同开市日；日 JSON 多键/少键/多行/
symlink；run_id/selector 错配；receipt/raw whole-rehash；复制另一日完整 closure；未来 mtime；live Arguments 或
StartBoundary 漂移；registered XML 改写；runner SHA 漂移；LastTaskResult 非0；LastRunTime 跨日；提前日日志；
Operational disabled 时错误推断“无人干预”。所有失败不得修改正式证据或补跑。

## 8. 串行执行与白名单

按用户 2026-08-13 的项目级协作裁决，当前暂停外部 Agent，由主 Agent 在 08-14 自然任务结束后串行完成：

1. 只读查询 Scheduler 轴并运行一次零网络离线 audit；
2. 按本任务冻结条件作正常工程核对，不另设“独立实现/独立初验”或内部 subagent 复验；
3. 写唯一 `docs/agent/M1_U0C-R3五日自然窗口终审报告.md`，并仅在两轴均 PASS 后同步
   UA-M1-003 与路线图状态。

禁止生产/tests/data/run_state/artifacts/计划任务写入；禁止联网、补跑、重注册、add/push。正式证据目录在终审
期间不可变。任何修复必须开新的未来窗口，不能补写本窗口。正常开发核对不构成额外独立验收阶段。

## 9. 停止条件

执行时刻早于 08-14 自然完成；未来任务被手工触发；发现定义/runner/注册快照漂移；提前日志；要求补跑计入；
历史通道被选择性开启/关闭以制造证据；audit 需要写 data 或联网；证据被修改；任何人试图把设计/2日/单日
SUCCESS 写成5/5或M1 Gate。命中立即停止并回报，不迁就。

## 10. 通过条件

五任务结果/时间/定义全绿、五日日志 exact、五份 receipt/raw/quality fresh闭包全绿、离线 audit exact PASS、
无正面人工/重注册证据，并诚实披露历史通道 disabled。满足后只关闭 U0C-R3 子 Gate；M1 总完成仍须另行
审计 HK60、正式许可/复权/CA、真实60日覆盖、ext4与工作树合流。
