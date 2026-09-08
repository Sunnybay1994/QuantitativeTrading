# M3 G8C-C2 R1 正式 Tracking CLI 任务单

日期：2026-08-14  
状态：**实现与正常开发检查完成；真实 honest tracking 尚未运行**

## 1. 目标

在已经完成的 C0 formal resolver、C1 `backtest` public CLI 和 G8D-F1 formal tracking StageRunner 之间补上
唯一窄接线：新增 `tracking --config --snapshot-id --fold --horizon [--no-resume]`。该命令只消费已经存在且
可 fresh verify 的 evaluation/backtest 产物，登记当前配置指定的 MLflow target，并发布本地 tracking
request/marker/receipt；不训练、不回测、不扫描目录猜 work，也不实现 `run-all`。

## 2. 接口与顺序

1. parser 只新增 `tracking`，参数形状与 `backtest` 相同；不接受 stage root、artifact roots、work key、
   tracking URI 或 client。
2. 新 `FormalTrackingCliResolution` 由 C0 的完整 backtest resolution 投影：复用其中 exact target、plan、
   release、experiment、fresh context 及上游 verified values，fresh verify 已存在 evaluation 与 backtest，构造
   `FormalTrackingFreshVerificationContext`。
3. public handler 顺序固定为：加载/锚定 config → zero-write tracking resolve → 从 config 的 canonical tracking
   URI 惰性创建 production client → actual `run_formal_tracking_stage`。
4. 成功 JSON 只含 snapshot/fold/horizon/work_key/reused/`stop_stage="tracking"`；不输出路径、URI、run id、
   receipt 或内部异常。

## 3. 失败与安全

- 复用 C0 稳定失败码与 StageRunner 稳定失败码；MLflow 依赖不可导入映射
  `FORMAL_CLI_DEPENDENCY_UNAVAILABLE`/exit 4，其余未分类异常为 `M3_COMMAND_FAILED`/exit 5。
- config、上游或 StageRunner 失败前不得创建 MLflow client；禁止 caller client、fake offline production
  client、pickle capability、私有 mint 或目录扫描。
- `run-all`、`train`、`evaluate`、`verify-reproducibility` 仍保持当前 fail-closed 状态。

## 4. 文件范围

- `src/quant/research/m3/formal_cli_resolve.py`
- `src/quant/research/run_m3.py`
- 新增 `tests/unit/test_m3_g8c_c2_tracking_cli.py`
- 本任务单与唯一交付报告

禁止修改 G1–G7 算法、StageRunner、tracking remote 协议、配置、receipt Schema 或 honest 300 产物。

## 5. 正常开发检查

- focused C2 + C1 CLI pytest；
- 对改动生产/测试运行 Ruff，生产文件运行 mypy；
- cold import 证明不因新增命令加载 MLflow/Qlib/LightGBM。

至少覆盖：成功/默认 resume、`--no-resume`、C0 与 StageRunner 稳定错误、依赖缺失、hostile client/stage
异常脱敏、失败时 client/stage 零调用，以及 parser 不暴露可信边界参数。

真实 honest 300 tracking 登记和 acceptance 不属于本实现检查；实现完成后另按现有正式产物与运行授权执行。
