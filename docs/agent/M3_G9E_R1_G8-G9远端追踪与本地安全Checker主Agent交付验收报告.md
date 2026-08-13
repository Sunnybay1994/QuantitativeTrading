# M3 G9E R1 G8-G9 远端追踪与本地安全 Checker 主 Agent 交付验收报告

日期：2026-08-13  
状态：**工程实现与定向验证完成；未宣称真实 M3 Gate 通过**

## 1. 结果

G9E 已实现为两个窄边界：

1. `tracking.verify_tracking_remote` 只读查询当前 tracking target 下的唯一远端 run，要求本地 request、marker、远端 tags、run id 和 `FINISHED` 状态完全一致；不创建 run、不写 params/metrics/artifact、不结束 run。
2. `acceptance_tracking.audit_acceptance_tracking` 只消费 G9B 计划引用的 receipt/output，形成固定 G8/G9 结果、按 work key 排序的 observation 和 canonical observation SHA-256。G9 重新验真当前 quality artifact，并只对计划引用的 manifest/receipt/report/log 做有界凭据与绝对路径扫描。

## 2. 关键设计

- acceptance 模块不 import MLflow；生产 CLI 后续在 G9F 注入真实 tracking client/verifier。
- 0 个、2 个以上、非 `FINISHED`、run id/tag/hash 漂移和远端异常统一 fail closed，稳定错误不保留 cause/context。
- 单文本文件上限 2 MiB、总扫描上限 32 MiB；不 glob/rglob，不扫描 workspace、archive 或 legacy data。
- 安全扫描同时识别赋值文本和规范 JSON 键，例如 `password=` 与 `"password":`。
- G8/G9 证据错误形成 Gate FAIL；仅 caller 类型、计划或根注册表非法才返回稳定 public error。

## 3. 变更

- 新增 `src/quant/research/m3/acceptance_tracking.py`。
- 扩展 `src/quant/research/m3/tracking.py` 的只读 remote verifier。
- 更新 `src/quant/research/m3/__init__.py` 安全导出。
- 新增 `tests/unit/test_m3_acceptance_tracking.py`。
- 更新 G9 分包任务状态。

## 4. 验证

- G9E focused：`8 passed`。
- G9C-G9E 联合定向：`29 passed`。
- 定向 Ruff：PASS。
- 定向 mypy（tracking + acceptance_tracking）：PASS。
- 覆盖反例：远端 0/2、RUNNING、tag drift、零远端写调用、hostile exception、JSON secret、无效 caller 脱敏。

首次 pytest 未显式绑定 worktree `src`，收集到根仓库旧模块并报 `ModuleNotFoundError`；随后显式设置当前 worktree `PYTHONPATH` 重跑取得上述有效终态，不计首次命令为产品失败。

## 5. 剩余边界

- 本轮使用 protocol fake，不连接真实 tracking target；真实联网复核只由后续用户显式启动的 acceptance CLI 执行。
- G9F 决策聚合/identity/成功发布/CLI 与 G9G fake 全链尚未实现。
- honest 300 证券三场景、当前远端 tracking 与质量证据未全部闭合，因此不更新 M3 Gate 或路线图完成状态。
