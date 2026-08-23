# M4 P8 RUN-0C R1 VerifiedSoakSchedule 任务单

状态：主 Agent 串行实现与 Windows 开发检查完成；真实窗口选择与运行仍等待 UA-M4-002。

## 1. 目标

从 formal ledger provider 的 exact open sessions 生成可复算 `VerifiedSoakSchedule`。本包只定义计划窗口，不运行 session、不注册 scheduler。

## 2. 契约

- 输入 exact provider、readiness完成的aware UTC、用户未来批准的`not_before`日期与aware UTC now。
- 首日为同时晚于 readiness自然日且不早于`not_before`的第一个开市日。
- 末日为从首日起自然日跨度首次达到至少35日的开市日；中间包含provider域内全部开市日，不得漏日/插日。
- identity最终复用 `expected_schedule_identity(tuple)`，并另绑定provider identity、readiness与not_before。
- existing verifier fresh验证provider并重算整个窗口；失败稳定脱敏。

## 3. 边界

无可覆盖35日的fresh日历即失败。UA-M4-002仍控制真实开始日期、任务注册与28日自然运行；本包完成不等于已获运行授权。
