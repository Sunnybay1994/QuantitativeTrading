# M1 HK-CA P1A：HK 总回报应用日程独立复验报告

日期：2026-08-09  
角色：未参与实现的独立复验 Agent  
结论：**PASS**  
边界：仅证明来源无关 development 合同通过；不是正式 HK 复权、HK60、M1 Gate 或 Linux/ext4 Gate。

## 1. 复验范围

已完整核对任务书、实现交付报告、`HkTotalReturnApplicationScheduleSchema`、
`hk_total_return_schedule.py`、新增实现测试，并向上审阅两个 public verifier 的真实闭包语义。
生产代码和实现者测试全程只读；本轮只新增本报告。

## 2. 契约核对

- builder 在构造任何 schedule 行前，依次 fresh 调用
  `verify_implemented_hk_corporate_action_set` 和 `verify_hk_bar_bundle`；不信任 capability
  dataclass 字段或私有 token。
- plan verifier 每次重复上述 fresh 验证，然后从当前 context 重建完整 schedule，对 policy、
  `as_of`、ordered content hash、plan identity、DataFrame 和 process-local attestation 做 exact compare。
- action 与 implementation evidence 以 `event_id` 建立 exact one-to-one，并核对
  event/symbol/type/source/source event/revision；实施确认时间不得晚于 `as_of`。
- action symbol 集与 bar symbol 集精确一致；bar 与 availability 的 `(symbol, trade_date)` 键集及行数
  精确一致；任一 future availability 都 fail closed。
- 窗口内仅支持 HKD `DIVIDEND`、`BONUS`、`SPLIT`；窗口内 `RIGHTS` 和 CNY
  dividend 整个 plan 拒绝。prewindow/future 行继续绑定上游 identity，但没有 application bar，
  不进入窗内应用。
- `APPLY_IN_WINDOW` 仅从 verified retained bars 选第一个 `trade_date >= ex_date`，
  因此 no-trade 日映射到下一个实际 retained bar，不依赖系统日历。
- canonical 顺序为 `(symbol, ex_date, event_id)`；行 identity 绑定行内全部字段，plan
  identity 绑定 `as_of`、policy 和 ordered schedule content。
- schema 限制了唯一 event/row identity、application evidence 的全有或全无，以及
  DIVIDEND/BONUS/SPLIT/窗外 unsupported 分支的经济字段互斥。
- `VerifiedHkTotalReturnApplicationPlan` 禁止普通构造、继承、原地赋值和 pickle；
  DataFrame getter 返回 clone。即使调用模块私有重签函数，fresh upstream rebuild 仍拒绝与
  context 不同的整计划。
- hostile 上游异常在离开 active `except` 后映射为稳定码；cause/context 为 `None`，
  path/raw/TOKEN marker 不进入对外 traceback/repr。本模块无网络、无文件写入、无 store mutation。

## 3. 独立对抗

除实现者测试外，在 Windows 以不落盘脚本补充了三组反例：

1. 用合法但内容不同的上游 action closure 生成 plan B，将 plan A 的全部 schedule、hash、
   identity 替换为 B 并用私有 attestation 重签；对 context A 验证仍以
   `HK_TOTAL_RETURN_VERIFY_FAILED` 拒绝。
2. 同 symbol、同 ex-date 的 DIVIDEND/SPLIT 以相反输入顺序构建；两个 plan identity
   完全一致，输出按 event id canonical 排序。
3. bar public verifier 抛出带显式 cause/context 和多层 SECRET/TOKEN marker 的递归异常图；
   builder 只暴露 `HK_TOTAL_RETURN_INPUT_INVALID`，新异常的 cause/context 均为 `None`，
   格式化 traceback 不含 marker。

对抗结果：`P1A_INDEPENDENT_ADVERSARIAL_PASS`。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`，强制 `PYTHONPATH=<worktree>/src`：

- `pytest -p no:cacheprovider test_schemas.py test_hk_corporate_actions.py test_hk_corporate_action_implementation.py test_hk_total_return_schedule.py -q`：**160 passed**。
- 定向 Ruff：**All checks passed**。
- 定向 mypy：**Success: no issues found in 3 source files**。
- 不落盘独立对抗：**PASS**。

WSL Miniforge `base`，同样强制 worktree `PYTHONPATH`：

- 同组定向 pytest：**160 passed**。
- 定向 Ruff：**All checks passed**。
- 定向 mypy：**Success: no issues found in 3 source files**。
- 当前路径文件系统为 `wslfs`/DrvFS，不是 ext4。

第一次 Windows pytest 未显式设置 `PYTHONPATH` 时，editable 环境误导入了根工作区的
`quant`，导致 collection error；设置 worktree 源码隔离后上述回归稳定通过。该现象是验证环境
隔离问题，不是 P1A 实现缺陷。

`git diff --check`：通过，仅报告既有 LF/CRLF 提示；未 add/commit，无关历史脏文件保留。

## 5. 最终判定与未解锁边界

P1A 的来源无关 schedule 合同与冻结任务书一致，独立复验 **PASS**，可进入主 Agent
最终验收；主验通过后只解锁 P1B 数值公式任务书。

仍未解锁：RIGHTS investor policy、CNY PIT FX、正式 ResearchPrice 发布、02983 可信
metadata、licensed 01065 issue/spec、formal V3M migration、真实 HK action source、Linux/ext4 Gate
以及正式 HK60/M1 Gate。
