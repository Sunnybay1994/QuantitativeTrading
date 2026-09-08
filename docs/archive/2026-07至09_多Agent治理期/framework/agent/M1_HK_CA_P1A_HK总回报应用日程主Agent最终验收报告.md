# M1 HK-CA P1A：HK总回报应用日程主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（仅来源无关 development 合同）**

## 1. 结论

P1A 已把fresh verified HK公司行动实施事实与fresh `VerifiedHkBarBundle`收缩成确定性应用日程：HKD
DIVIDEND、BONUS、SPLIT按ex-date归属，ex-date无bar时映射首个`>= ex_date`的retained bar；prewindow与future
行动显式绑定但不应用；窗口内RIGHTS与CNY dividend稳定fail closed。实现、自测、全新独立初验和主验均通过，
可进入P1B数值公式与发布合同设计。

本包不计算或发布ResearchPrice，不代表正式HK复权、HK60、M1或ext4 Gate通过。

## 2. 主验核对

- context携带两个public verifier的完整参数；builder/verifier分别fresh调用implemented action与bar bundle verifier；
- action/implementation exact一一对应，bar/availability exact keys与`bar_available_at<=as_of`闭合；
- schedule exact每个implemented event一行，canonical按symbol/ex-date/event-id排序；输入shuffle identity稳定；
- DIVIDEND/BONUS/SPLIT的pay/list与经济字段互斥由Pandera schema验证，SPLIT multiplier不得为1；
- schedule/row/plan identity绑定P0 query/actions/evidence、implementation projection、bar plan/publication、bars、
  availability、policy、as_of与完整有序行；
- plan exact process-local、不可pickle/subclass，public verifier fresh重建并比较内容与attestation；
- hostile verifier异常稳定脱敏，本模块零网络、零文件/store写入。

独立初验新增合法不同上游closure整计划替换并私有重签、同日多事件shuffle和递归hostile异常图，均通过。

## 3. 验证证据

- 实现最终：Windows/WSL P1A各`9 passed`，两平台上游schema+P0+implementation+P1A均`158 passed`，
  Ruff/mypy PASS；
- 独立复验：Windows与WSL base隔离源码同组均`160 passed`，Ruff/mypy PASS；
- 主Agent复核停牌映射、shuffle、RIGHTS/CNY、whole-resign四节点（含参数化）→`5 passed`；Ruff PASS，
  mypy四文件PASS；
- diff check通过；未联网、未触正式data/journal、未add/commit。

## 4. 保留边界

- 当前WSL为wslfs/DrvFS，不是ext4。
- P1B仍需单独冻结gross total-return数值公式、同日事件组应用、产物schema/receipt与fresh verifier；RIGHTS、
  CNY FX、税费和账户entitlement继续不在v1支持范围。
- 正式发布仍受02983可信metadata、licensed 01065 issue/spec、formal V3 migration与真实HK action source阻塞。
