# M3-G8D 开发示例 Tracking 主 Agent 阶段验收报告

日期：2026-08-02

结论：**development/example tracking 契约通过；真实 MLflow、完整 G8 DAG 与正式 Gate 尚未验收。**

## 已实现

- 严格、规范化、no-clobber 的 `TrackingRequestV1` 与 `TrackingMarkerV1` journal。
- 唯一 `compute_tracking_key`，以 work key 与请求摘要绑定远端 run 身份。
- `(tracking_target_key, tracking_key)` 跨平台 writer lock；0/1/2 个远端 run、非终态、tag 冲突及本地 marker 冲突均失败闭合。
- 远端已完成、marker 写入前崩溃时恢复同一 run ID，不重复创建 run；artifact 上传保留相对层级并在调用远端前复核摘要。
- development/example evaluation/backtest 请求构造，null 科学指标不作为 numeric metric 上传；递归拒绝凭据和绝对本机路径。
- MLflow 客户端仅在真实 adapter 创建时延迟导入，普通 `quant.research.m3` 导入不加载 MLflow。

## 主 Agent 验证

Windows 原生 Miniforge，显式 `PYTHONPATH` 指向隔离 worktree，独立 `--basetemp`：

```text
pytest tests/unit/test_m3_tracking.py tests/unit/test_m3_tracking_journal.py -q
18 passed
ruff check src/quant/research/m3/tracking.py tests/unit/test_m3_tracking_journal.py
All checks passed!
mypy src/quant/research/m3/tracking.py tests/unit/test_m3_tracking_journal.py
Success: no issues found in 2 source files
```

实现阶段 WSL Miniforge `base` 同组测试：`18 passed`。该路径位于 `/mnt/f` DrvFS，只构成 Linux 解释器兼容反馈，不替代 ext4 或正式 Gate。

## 边界

- 未启动真实 MLflow server，也未执行网络请求。
- 产物和标签显式标记 `development_example` / `formal_gate_eligible=false`，不生成或冒充正式 G8 产物。
- G8A-G8C、G8E-G8F 与真实 handler continuation 仍需分别完成；正式 M3 结论继续等待正式 G8 identity 与后续 Gate。
