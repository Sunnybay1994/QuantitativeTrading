# M4 P8 R4：稳定性与故障演练主 Agent 最终工程验收报告

日期：2026-08-09  
结论：**PASS（P8 工程合同）**  
正式状态：**`WAITING_FOR_SOAK_EVIDENCE`**

## 验收结论

1. R3 的 evidence root + independent anchor root、连续 append anchor chain、retained P5/P7 facts fresh reconstruction、
   可信本机 UTC 窗口、exact crash recovery、并发 sequence 竞争和 decision-time fresh verification/old-capability equality
   均通过独立对抗。另一份语义合法 retained closure 整体替换并全量重哈希，不能穿过既有 anchor。
2. R4 仅将 `quant.execution` 对 P8 soak 符号的 eager re-export 改为 exact-set PEP 562 惰性导出。
   `import quant.execution` 不加载 soak；首次访问冻结符号时加载并保留原 `__all__`/`from *` 公开兼容；
   未知属性标准抛 `AttributeError`。
3. 全新解释器可分别冷启动导入 `quant.backtest.event_simulator`、
   `quant.reporting.trading_metrics`、`quant.execution.soak` 以及包根惰性 soak 符号。R3 的循环依赖已关闭，
   不依赖 pytest 文件顺序。
4. development evidence 无论天数、sessions 和 drills 如何完整，均没有 PASS 分支。本地 hash chain/path identity
   是可信本机 append-only 合同，不被表述为外部签名或 WORM。

## 验证

主 Agent Windows 原生：

```text
test_execution_soak.py: 44 passed, 1 skipped
fresh cold-import probe: P8_COLD_IMPORT_MAIN_PASS
Ruff: All checks passed
mypy: Success, 2 source files
```

独立复验者的补充证据：

```text
Windows single files: event 21, metrics 11, soak 44 passed + 1 skipped
Windows P5-P8: 471 passed, 6 skipped
WSL base/DrvFS single files: event 21, metrics 11, soak 45 passed
WSL base/DrvFS P5-P8: 476 passed, 1 skipped
Ruff/mypy: PASS on both interpreters
```

独立审查额外重跑 legal closure 整体替换、stale capability TOCTOU 和 development never-PASS 反例。
WSL 路径为 `/mnt/f` DrvFS，仅是 base 解释器开发兼容证据，不等于 ext4/Linux Gate。

## 正式状态和剩余条件

P8 代码、fixture、恢复/重复执行、anchor、冷启动和双平台开发契约已完成工程收口。但 M4 正式 Gate
必须继续保持 `WAITING_FOR_SOAK_EVIDENCE`，直到正式 PAPER runner 在符合合同的真实环境中自然产生至少
28 日、完整 expected sessions、全部强制 fault drills、零未解释 issue 的证据，并完成 Linux/ext4 终验。

本报告不注册/启动正式 runner，不伪造历史时间，不执行网络/broker 调用，不触碰正式 artifacts/journal，
未 `git add/commit`。
