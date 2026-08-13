# M3 G8E R1 fresh-process reproducibility 主 Agent 串行交付报告

日期：2026-08-13  
状态：Windows 工程实现与常规开发检查完成；未执行 Linux/ext4 Gate 或真实全链长运行

## 1. 交付结论

本轮在外部 Agent 暂停模式下由主 Agent串行实现。按项目当前协作规则，只执行与风险相称的正常开发反馈，
不另设主 Agent 自己的“独立初验/自我复审”阶段，也未调用内部 subagent 模拟职责分离。

G8E 已实现：

1. 新增只解析到 verified alignment 的 formal reproducibility resolver；它不读取正常 work 的 model、prediction、
   evaluation；原 backtest resolver 复用同一前半链，公共行为保持不变。
2. 父进程构造稳定 comparison key，顺序启动两个 `python -I` fresh process；每个 attempt 使用独占 TEMP/cache，
   自行 fresh resolve 后执行 formal train → predictions → evaluation。
3. 每个 attempt 只发布合同要求的七个文件，并记录无 PID 的 `read_audit.json`；audit 绑定 code、dependency、
   Python executable 内容摘要和实际只读路径摘要。
4. 父进程从两个原始 prediction/metrics 文件重算行键、score 容差、metric key/null/finite/value 容差；模型和
   Parquet 字节允许不同，未使用 hash 相等代替数值比较。
5. 新增 `REPRODUCIBILITY_STAGE_SPEC`，通过现有 `StageRunner.run_static` no-clobber 发布两个 attempt tree、
   `reproducibility.json` 和严格 `REPRO` receipt；任一 worker/比较失败均不发布 comparison。
6. 新 API 使用惰性包导出，冷导入不加载 LightGBM。

## 2. 修改范围

- `src/quant/research/m3/reproducibility.py`
- `src/quant/research/m3/formal_cli_resolve.py`
- `src/quant/research/m3/orchestration.py`
- `src/quant/research/m3/__init__.py`
- `tests/unit/test_m3_reproducibility.py`
- 本报告

工作树中既存的 U12 任务/报告/integration 测试和异常名称目录不属于本轮修改或提交范围。

## 3. 常规开发验证

Windows 原生 Miniforge，显式 `PYTHONPATH=<worktree>/src`：

- focused G8E：`6 passed`
- G8E + formal resolver + orchestration 邻接：`29 passed, 1 skipped`
- Ruff（本轮生产与测试文件）：PASS
- mypy（reproducibility/resolver/orchestration）：PASS
- cold import：`G8E_COLD_IMPORT_PASS`，未加载 `lightgbm`
- scoped `git diff --check`：PASS（只有既有 LF/CRLF 提示）

## 4. 边界与剩余风险

- 本轮没有运行真实 G1→alignment→两次 LightGBM fresh worker 的完整长链；这需要 retained/public formal chain
  或后续已批准的长运行窗口，不能用 unit fake 替代，也未宣称完成。
- 尚未执行 WSL/Linux/ext4 平台 Gate；项目当前目标明确暂不考虑 Linux 实现。
- public CLI `verify-reproducibility` 接线和 G8F fake full-DAG integration 仍是后续独立包。
- G8E 只证明工程合同已实现，不代表 G9、M3 最终 Gate 或策略有效性通过。
