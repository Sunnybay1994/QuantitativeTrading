# M1 HK-CA P1A：HK 总回报应用日程实现交付报告

日期：2026-08-09  
状态：实现与双平台自测完成；待独立初验  
边界：development 合同；不是正式 HK 复权、HK60 或 M1 Gate

## 1. 交付结果

- 新增 `HkTotalReturnApplicationScheduleSchema`，冻结 `HK_GROSS_TOTAL_RETURN_SCHEDULE_V1` 的逐事件 schedule 字段、应用证据和 action-specific 互斥约束。
- 新增 process-local `HkTotalReturnFreshContext` 与 `VerifiedHkTotalReturnApplicationPlan`；禁止 pickle、继承、普通构造和原地赋值，DataFrame getter 返回 clone。
- builder 在生成任何行前 fresh 调用 `verify_implemented_hk_corporate_action_set` 与 `verify_hk_bar_bundle`；verifier 每次 fresh 重建完整 schedule 并 exact compare，不信任缓存或调用方重签。
- 支持窗口内 HKD `DIVIDEND`、`BONUS`、`SPLIT`；窗口内 `RIGHTS`/CNY dividend fail closed。prewindow/future 事件仍逐行绑定但没有 application bar 和经济投影，避免重复应用或提前应用。
- `APPLY_IN_WINDOW` 只从 verified retained bars 选择首个 `trade_date >= ex_date`，停牌/no-trade 日期自然映射到下一 retained bar；未读取系统日历。
- identity 绑定 P0 query/actions/evidence、implementation evidence/projection、bar plan/publication/bars/availability、aware UTC `as_of`、policy、逐行 identity 与 canonical ordered schedule。
- 本模块不计算 `ResearchPrice1dSchema`，不联网、不写文件、不读取正式 data/journal，也不调用 clock。

## 2. 文件

- `src/quant/domain/schemas.py`
- `src/quant/domain/__init__.py`
- `src/quant/data/hk_total_return_schedule.py`
- `tests/unit/test_hk_total_return_schedule.py`
- `docs/agent/M1_HK_CA_P1A_HK总回报应用日程任务单.md`
- 本报告

未修改既有 P0/PRE/PRE-B 生产实现和测试；worktree 中其他历史脏文件均保留。

## 3. 验证

Windows 原生 `D:\Miniforge3\python.exe`：

- `pytest test_schemas.py test_hk_corporate_actions.py test_hk_corporate_action_implementation.py test_hk_total_return_schedule.py -q`：158 passed。
- 最终 `pytest test_hk_total_return_schedule.py -q`：9 passed。
- 定向 Ruff：通过。
- 定向 mypy：通过。

WSL Miniforge base（当前路径位于 DrvFS/wslfs，不是 ext4）：

- 同组上游回归：158 passed。
- 最终定向测试：9 passed。
- 定向 Ruff：通过。
- 定向 mypy：通过。

`git diff --check`：通过；仅有既有 LF/CRLF 警告和不可读历史 pytest 目录警告。

## 4. 已覆盖的关键反例

- ex-date 无 bar 映射下一 retained bar；prewindow/future disposition；多 symbol、同日多事件 canonical 顺序；输入 shuffle identity 不变。
- 窗口内 RIGHTS/CNY、future bar availability、hostile upstream verifier fail closed。
- wholesale schedule 改写并重签、ordinary plan/context、pickle、clone/不可变边界。
- P0 actions 与 implementation evidence exact one-to-one、symbol/bar key closure、application availability identity 均由生产代码检查。

## 5. 未解锁边界

本包只解锁 P1B 数值公式任务书。RIGHTS investor policy、CNY PIT FX、正式 ResearchPrice 发布、02983 可信 metadata、licensed 01065 issue/spec、formal V3M migration、真实 HK action source 与 ext4 Gate 均仍待后续独立任务。
