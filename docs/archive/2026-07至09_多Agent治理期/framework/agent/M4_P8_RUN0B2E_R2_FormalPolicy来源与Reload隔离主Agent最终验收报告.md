# M4 P8 RUN-0B2E R2：Formal Policy 来源与 Reload 隔离主 Agent 最终验收报告

日期：2026-08-12  
结论：**PASS（Windows 工程合同）；RUN-0B2F 可继续；Linux/ext4 与正式运行 Gate 未关闭**

## 验收结论

- formal B1 descriptor 只能由 exact policy/binding builder 本次签发的同一 process-local 实例通过 `_prove_policy`；来源登记位于 builder/prover 共享的 closure-private identity weak-reference registry，development descriptor 的 classification/digest whole-rehash以及合法 descriptor 的 same-value clone 均不能冒充 formal 来源。
- cold root → materialized fresh 四链 → 唯一 B1 store → formal capability 的正向闭环保持绿色。
- unknown concurrent file 使 rollback fail closed 并保留现场，不递归误删。
- binding/account reload 对抗在 fresh 子进程完成，旧 capability 仍被拒绝，同时父 pytest 进程的 exact class identity 不再污染后续模块。
- public callable surface 未新增通用 mint/seal；未扩大到 gateway、service、dispatch、CLI 或 soak。

## 可复现证据

```text
reload fixed order: 3 passed
六模块邻接: 124 passed, 37 skipped
Ruff: PASS
mypy: PASS
cold import: external SDK、heavy research、service/CLI/soak/reporting modules absent; public mint/seal surface absent
scoped diff-check: PASS
```

主 Agent 串行收尾的当前 focused 证据为 B1 + formal `19 passed`，定向 Ruff/mypy 继续 PASS；未另设内部独立初验阶段。

## 剩余边界

- 当前只完成 Windows 工程验收；未执行 Linux/ext4 文件系统 Gate。
- B1 既有值对象依赖会加载 `quant.backtest` 的 costs/fx 与内部 paper gateway 合同/实现模块；本轮未把该既存边界误报为“整个 gateway/backtest 包均未导入”，冷导入断言只覆盖外部 SDK、研究重依赖和 service/CLI/soak/reporting。
- process-local registry 是 Python 工程来源证明，不是对任意同进程恶意内存修改的安全隔离。
- B2E 只授权 durable store；后续 B2F 仍须重新冻结 gateway/snapshot port 的 exact 消费边界，不得凭 path 或裸 descriptor 重新打开 formal store。
