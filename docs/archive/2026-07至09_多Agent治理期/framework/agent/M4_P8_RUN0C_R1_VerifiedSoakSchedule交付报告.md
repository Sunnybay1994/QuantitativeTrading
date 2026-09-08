# M4 P8 RUN-0C R1 VerifiedSoakSchedule 交付报告

## 结论

已实现从 fresh formal ledger provider 自动选择连续 future open-session 窗口的 process-local capability。首日严格晚于 readiness自然日且不早于批准的`not_before`；末日为自然日跨度首次达到35日的开市日，中间开市日不得遗漏。

## 检查

- schedule focused + 既有 soak：49 passed、1 skipped。
- Ruff/mypy：通过。
- 覆盖连续窗口、35日跨度、日历不足、capability字段漂移与hostile verifier脱敏。

本包没有选择真实开始日、注册任务或运行 PAPER。UA-M4-002 与 honest current calendar仍是正式运行前置。
