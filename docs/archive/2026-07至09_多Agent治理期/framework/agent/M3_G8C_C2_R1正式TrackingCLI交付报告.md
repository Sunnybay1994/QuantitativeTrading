# M3 G8C-C2 R1 正式 Tracking CLI 交付报告

日期：2026-08-14  
结论：**单 work formal tracking CLI 接线已完成；未运行真实 MLflow/300 证券 tracking，不宣称 G8/G9 总 Gate。**

## 改动

- `formal_cli_resolve.py` 新增 `FormalTrackingCliResolution` 与
  `resolve_formal_tracking_cli_inputs`。resolver 先走现有完整 C0 backtest fresh closure，再从其 process-local
  context 构造 evaluation fresh context，验真既有 evaluation 与 backtest，最后形成 G8D-F1 所需的唯一
  `FormalTrackingFreshVerificationContext`。
- `run_m3.py` 新增窄命令
  `tracking --config --snapshot-id --fold --horizon [--no-resume]`。production MLflow client 只在 config 与全部
  本地产物成功 resolve 后惰性创建；随后调用 actual `run_formal_tracking_stage`。
- 新测试覆盖成功与 resume、稳定 C0/StageRunner 错误、依赖缺失、hostile client、失败短路、输出脱敏、
  parser 可信边界和冷导入。

## 正常开发检查

- C2 + C1 CLI：`50 passed, 1 skipped`。
- Ruff：两个生产文件与两个 CLI 测试文件通过。
- mypy：`run_m3.py`、`formal_cli_resolve.py` 通过。
- cold import：未加载 MLflow、Qlib、LightGBM。
- C2 + G8D-F1 全文件邻接曾在 180 秒承载上限只输出 7 个通过节点后超时，未取得完整摘要，未记为
  通过证据，也未机械重跑；既有 G8D-F1 生产与测试未改。
- `git diff --check` 通过；本轮两个 pytest 临时目录已精确删除。

## 边界与下一步

本轮没有实现 `run-all`、train/evaluate handler、reproducibility CLI 或 acceptance orchestration，也没有创建
真实 tracking DB/run。下一步可在现有 honest 300 stage tree 仍可解析时按四个 work 逐一执行 public
`tracking`，再运行 `acceptance-audit`；若正式 session-owned tree 已按任务清理，则必须从留存正式产物或一次
受控重建获得输入，禁止伪造 capability 或扫描目录猜 work。
