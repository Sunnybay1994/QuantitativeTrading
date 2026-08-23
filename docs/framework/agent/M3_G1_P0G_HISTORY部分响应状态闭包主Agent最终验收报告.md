# M3 G1 P0G：HISTORY 部分响应状态闭包主 Agent 最终验收报告

状态：**PASS**（仅关闭 P0G；不等于 G1 HISTORY、G1 Gate、Windows publish 或 Linux Gate 已完成）

日期：2026-07-28（Asia/Shanghai）  
冻结基线：`123c1c0`  
实现提交：`644995e`  
外部独立初验：`dd4bf59`，结论 PASS

## 1. 主验结论

P0G 修复满足冻结合同：

- Tushare HISTORY 已完整但 CNINFO 缺失或部分完成时，verified workflow 只暴露 INDEX 阶段；
- `history_responses` 与 `cninfo_responses` 只在两批请求均完整验证后同时进入最终状态；
- INDEX/HISTORY 未完成状态拒绝泄漏 CNINFO responses；
- HISTORY 完成状态绑定 Tushare 与 CNINFO 两批精确、有序的 request IDs；
- 正式 `status` 恢复为 exit 0 / `INCOMPLETE`，不再产生 `CLI_INTERNAL_ERROR`；
- Windows 与 WSL 正式状态检查均未创建 CNINFO raw/journal 目录。

实现保持了 counts、CLI JSON、错误码、connector、raw/journal 恢复语义和既有 candidate/release 合同，变更范围最小。

## 2. 证据

### Windows 原生反馈环

- P0G missing/partial/complete/tamper、bounded/unbounded resume、CLI socket/connector poison：**7 passed**
- Ruff：**通过**
- mypy `g1_workflow.py`：**通过**
- 外部独立初验的正式磁盘 `status`：
  - exit 0
  - `outcome=INCOMPLETE`
  - `completed_stages=["INDEX"]`
  - `error_code=null`
  - counts：INDEX 127、HISTORY requests 3190、symbols 637
  - CNINFO raw/state 目录前后均不存在

### WSL Miniforge base

HEAD：`dd4bf59`

- 同一组 7 个 P0G 定向测试：**7 passed**
- 正式命令：

```text
/home/mabw/miniforge3/bin/conda run -n base python -m quant.research.m3.run_g1 --config configs/research/m3_qlib_example.toml status
```

结果：

- exit 0
- `outcome=INCOMPLETE`
- `completed_stages=["INDEX"]`
- `error_code=null`
- counts：INDEX 127、HISTORY requests 3190、symbols 637
- `new_requests_committed=0`
- CNINFO raw/state 目录在命令前后均不存在：`WSL_CNINFO_ZERO_WRITE_PASS`

## 3. 范围与后续

本报告关闭 P0G 并解除“P0G 通过前禁止正式 CNINFO 网络 HISTORY”的冻结条件。下一步可按正式计划执行受限 CNINFO HISTORY（637 个证券、每批最多 50 个证券，计划 13 个请求），随后重新检查 HISTORY/candidate/reference 身份闭包。

尚未在本报告中运行正式 CNINFO 网络 HISTORY、REFERENCE、PREPARE、PUBLISH、全量回归或 Linux publish Gate。
