# M4 P6 R4：PAPER 操作 CLI 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（开发工程合同）**

## 验收结论

1. exact pending 集合的真实变化（新增、缺失、未来 PENDING、LEASED、UNKNOWN 和明确 claim fence）稳定映射为
   confirmation drift，CLI exit 20，gateway 0。
2. SQLite exact query、claim write、savepoint rollback、transaction commit 和其他写失败不冒充集合漂移；
   service 返回 `SERVICE_EXACT_PENDING_WRITE_FAILED`，CLI 返回 exit 50 / `EXECUTION_RETRY_REQUIRED`。
3. 可重试事务失败下 delivery 保持 `PENDING/attempt_count=0`，gateway 零调用，没有部分 claim 或经济
   crossing。旧 allowlist 仍只派发选中成员。
4. 稳定异常在 active handler 外重建，cause/context 均为 `None`；CLI stdout 不泄露内部内容，stderr 只有稳定码。

## 验证

主 Agent Windows 原生定向：

```text
store + service + CLI: 265 passed, 5 skipped
Ruff: All checks passed
mypy: Success, 3 source files
```

独立复验者另外使用 SQLite authorizer/trigger 注入 query、claim、rollback、commit 失败和六类集合/fence
变化；Windows `265 passed, 5 skipped`，WSL base `/mnt/f` `270 passed`，两平台 Ruff/mypy 通过。DrvFS 证据
不等于 ext4/Linux Gate。

## 边界

P6 R4 工程合同正式收口。本 PASS 不开启 live，不代表 broker 真实通道、P8 真实 28 日、
Linux/ext4 或 M4 总 Gate 通过。本轮无网络/broker 调用，未触碰正式 artifacts/journal，未 `git add/commit`。
