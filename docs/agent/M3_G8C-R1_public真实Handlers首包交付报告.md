# M3-G8C-R1 public real-handlers continuation 首包交付报告

日期：2026-08-02
状态：独立复验与主 Agent 定向终验通过
任务书：[`M3_G8C-R1_public真实Handlers首包任务单.md`](M3_G8C-R1_public真实Handlers首包任务单.md)

## 结果

- public `readiness` 与 `snapshot` 已接到默认真实 dispatcher；其余六个 public 命令仍返回
  `M3_COMMAND_HANDLER_UNAVAILABLE`，未伪造后续 handler。
- 调用顺序固定为：C0 配置一次加载 → 精确 release ID 的 `verify_g1_release` → 从已验真 manifest
  receipt 闭包重算 benchmark source snapshot identity → `audit_m3_readiness` → runtime code identity →
  `make_snapshot_run_plan` / `StageRunner.run_snapshot` → `verify_snapshot_artifact`。
- `readiness` 不写产物；`snapshot` 只有在 identity/readiness/runtime 全通过后才创建配置指定的 M3
  artifact root。正式 G1 路径只读，测试仅写 `tmp_path`/ignored `artifacts/test_tmp`。
- G1 benchmark snapshot identity 的既有唯一算法已抽成公共纯函数，mapper 与 readiness caller 共同复用，
  避免 CLI 复制规范 hash 或从被审计表自报期望值。
- 独立初验发现的配置 TOCTOU 已关闭：`LoadedM3Config` 保存入口唯一一次读取所得 raw SHA-256；
  `compute_m3_runtime_identity` 新增可选冻结配置 digest 接口。public handler 使用该接口后，runtime 的
  source collection 与 Git probe 均不再打开或重新观察配置路径，snapshot config/document、runtime
  source identity 与 stage code version 来自同一入口快照。未传冻结 digest 的既有 caller 行为保持不变。
- e0487e3 已包含既有 G8D tracking journal；本包未修改 tracking，定向回归包含
  `test_m3_tracking_journal.py`。

## 修改文件

- `src/quant/research/run_m3.py`：真实 readiness/snapshot dispatcher、身份/路径解析、snapshot handler。
- `src/quant/research/m3/config.py`：在单次加载时保留 raw config SHA-256。
- `src/quant/research/m3/runtime_identity.py`：支持经严格路径闭包校验的冻结 config source digest；既有
  默认双探测接口保持兼容。
- `src/quant/data/m3_mappers.py`：公开并复用 benchmark response closure identity 纯函数。
- `tests/unit/test_m3_run_cli.py`：身份先行零写、顺序、ERROR 阻断、WARNING 放行、未实现命令反例，
  以及 readiness 后原子替换配置仍单次读取和同一冻结身份的回归。
- `tests/unit/test_m3_runtime_identity.py`：冻结 digest 模式不重开配置路径、替换磁盘配置后身份稳定。
- 本任务单与本交付报告。

## 验证

| 环境 | 命令摘要 | 结果 |
| --- | --- | --- |
| Windows `D:\Miniforge3\python.exe` | 定向 Ruff | PASS |
| Windows | 定向 mypy（2 个生产文件） | PASS |
| Windows | CLI/orchestration/snapshot/G1 mapper/tracking journal pytest | **104 passed**，154 个既有 Pandera deprecation warnings |
| WSL Miniforge `base` | 对应定向 Ruff | PASS |
| WSL `base` | 对应定向 mypy | PASS |
| WSL `base` | 对应定向 pytest | **104 passed**，154 个既有 Pandera warnings，另 1 个 DrvFS `.pytest_cache` permission warning |
| 两平台 | `git diff --check` | PASS（Git 仅提示 Windows 行尾转换） |

### 配置冻结返工验证

- Windows Miniforge：返工文件 Ruff、mypy PASS；runtime/CLI 核心 `38 passed`；扩展定向回归
  `227 passed`（154 个既有 Pandera warnings）。
- WSL Miniforge base：返工文件 Ruff、mypy PASS；扩展定向回归 `227 passed`（154 个既有
  Pandera warnings）。
- 新反例实测 public snapshot 对入口配置 `Path.read_bytes` 恰一次；readiness 后使用原子替换写入另一份
  raw 时，runtime `source_files`、stage config 与 code version 仍绑定旧 raw digest，且测试未产生
  artifact/stage/receipt 目录。

## 限制与 Gate 边界

- Windows 与当前 WSL base 均为 Python 3.13；冻结 readiness policy 是 `<3.13`，因此真实 readiness 会如实
  返回 `PYTHON_UNSUPPORTED`，不会绕过到 snapshot。py312/正式 G0 证据需由后续 Gate 单独闭合。
- 本轮没有读取或修改正在运行的正式 G1 journal、候选或发布目录，没有联网，也没有运行正式 snapshot。
- 这些结果证明 public readiness/snapshot 编排开发合同与双平台定向回归；不证明正式 G1、Linux/ext4、
  G8、G9 或 M3 Gate 通过。
