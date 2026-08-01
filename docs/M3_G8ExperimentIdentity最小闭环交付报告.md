# M3 G8 ExperimentIdentity 最小闭环交付报告

## 1. 结论

本变更完成正式 G8 第三 continuation 的 ExperimentIdentity 最小工程闭环：通用 M3 运行身份、
单文件 manifest producer、精确四输入一输出 plan、provider-validation 前置 Gate、专用 static-directory
runner、严格 consumer 回接和薄 CLI 已具备。所有执行验证均使用 fixture/fake；未运行正式发布，未修改
G1/G2 bytes、journal 或正式候选目录。

本结果只表示 **ExperimentIdentity 工程契约通过**，不表示正式 G8 artifact 已发布，也不表示完整 G8、
M3 Gate 或 Linux/ext4 Gate 已关闭。

## 2. 变更

- `runtime_identity.py`
  - 首选 Git commit 加受控 source/config/pyproject content identity；clean 与 dirty 均绑定实际源码树，
    `assume-unchanged` 或 ignored Python 文件不能隐藏内容变化；
  - Git metadata 不存在或 Git executable 不存在时才使用 canonical source/config tree fallback；
  - POSIX 环境读取到 Windows 创建的 drive-letter worktree `.git` 指针时，显式使用同一 canonical
    source/config tree fallback；其他 Git metadata 错误仍 fail closed；
  - 完整 dependency fingerprint 包含 Python/platform、`pyproject.toml` 和 15 个研究/回测 distribution，
    缺包稳定记录 `NOT_INSTALLED`；
  - source、Git、platform 和 dependency probe 连续测量两次，任一漂移 fail-closed；值对象可重算验证自身闭包。
- `experiment_identity.py`
  - 使用已有 `ExperimentIdentityManifestV1` 与 `compute_experiment_key` 构造 canonical manifest；
  - plan 只接 verified snapshot/provider/provider-validation capability；validation 必须 PASS 且闭合上游身份，
    但不进入 receipt 内容 inputs；
  - receipt 内容 inputs 精确为 snapshot receipt/manifest 与 provider receipt/manifest，输出精确为
    `experiment_manifest.json`。
- `orchestration.py`
  - 只增加 `experiment-identity` 专用 `StaticDirectoryPublication` 路径；
  - 独占 temp、精确单文件闭包、no-clobber directory commit、目录外 receipt、orphan 恢复、重复执行复验；
  - 发布后通过调用者注入的现有 strict `verify_experiment_identity` 再验真；
  - root alias 校验与 `run_state` 对齐，支持既有正式 receipt 使用的 `G2A/G2B/...` alias。
- `quant.research.run_m3`
  - CLI 只解析路径、加载一次配置、fresh 验真 G1/G2A/G2B/G2C、注入 runtime identity/plan/runner；
  - stdout 为单份 canonical JSON，错误只暴露稳定 code，不回显异常、绝对路径或凭据。
- `quant.research.m3.__init__`
  - 导出新增公共契约。

冻结任务与审计依据见
[`docs/agent/M3_G8ExperimentIdentity最小闭环任务单.md`](agent/M3_G8ExperimentIdentity最小闭环任务单.md)。

## 3. 验证

Windows Miniforge：

```text
Ruff：PASS
mypy：PASS（5 source files）
pytest 新增 identity/experiment/CLI + orchestration + strict label consumer：34 passed, 1 skipped
```

WSL Miniforge `base`：

```text
Ruff：PASS
mypy：PASS（5 source files）
pytest 新增 identity/experiment/CLI + orchestration：15 passed
```

WSL Miniforge `py312`：

```text
Ruff：PASS
mypy：PASS（5 source files）
pytest 新增 identity/experiment/CLI + orchestration + strict label consumer：34 passed, 1 skipped
```

主 Agent 独立对抗审查修复后，Windows、WSL `base`、WSL `py312` 分别复跑 runtime / experiment /
CLI 定向测试，三平台均为 `12 passed`；Ruff 与 mypy 均通过。修复关闭了 Git
`assume-unchanged` 隐藏源码改动以及 Windows reparse/junction 未显式拒绝的问题。

对抗覆盖包括：Git clean/dirty 内容变化、`assume-unchanged`、ignored Python 文件、fallback、
`NOT_INSTALLED`、首尾漂移、Git metadata 损坏不得
静默 fallback、validation FAIL、validation 不进入内容 receipt、精确四输入一输出、首次发布、resume 不重跑
handler、输出目录篡改、CLI 单 JSON 与错误脱敏。既有 label consumer 回归证明新增 manifest/receipt 形态仍由
当前 strict consumer 约束；本任务未伪造正式验证结论。

## 4. 待主 Agent 审查后的正式命令

以下命令仅记录下一步，**本交付未执行**。必须在本提交合入、worktree clean 后运行，否则 code identity 与
`experiment_key` 会变化。输出位于 WSL/Windows DrvFS 轨，不能表述为 ext4 Gate。

```bash
cd /mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g2a
release_id=08eb9b31ab4d8c8473c0a7bb612df83009a68b761b8a35816653b2ce07807359
snapshot_key=fd5350a0b1237c05530da09719ea536658e1125b4652dc480ad6262cdee68d50
provider_key=b6ecc2718bc2899d35d14c1263ec9a2f70c71dfbdc8642dafae21cc39a65c17f
validation_key=65bda5759316a1514bc4a8546ec4f2e70a0830ffbfc521bf7fca25cd88e3475e
g2a="$PWD/artifacts/formal_g2a_windows/release=$release_id"
g2b="$PWD/artifacts/formal_g2b_wsl/release=$release_id"
g2c="$PWD/artifacts/formal_g2c_wsl/release=$release_id"
g8="$PWD/artifacts/formal_g8_wsl/release=$release_id"
mkdir -p "$g8"
env PYTHONPATH=src /home/mabw/miniforge3/bin/conda run --no-capture-output -n py312 \
  python -m quant.research.run_m3 experiment-identity \
  --project-root "$PWD" \
  --config "$PWD/configs/research/m3_qlib_example.toml" \
  --g1-release-root "/mnt/f/AI_Coding/QuantitativeTrading/data/clean/m3_g1/releases/$release_id" \
  --snapshot-artifact-root "$g2a" \
  --snapshot-root "$g2a/snapshot-temp" \
  --snapshot-request-path "$g2a/snapshot-requests/$snapshot_key.json" \
  --snapshot-receipt-path "$g2a/receipts/snapshot/$snapshot_key.json" \
  --provider-artifact-root "$g2b" \
  --provider-root "$g2b/provider-temp" \
  --provider-receipt-path "$g2b/receipts/provider/$provider_key.json" \
  --provider-validation-artifact-root "$g2c" \
  --provider-validation-root "$g2c/provider-validation-temp" \
  --provider-validation-receipt-path "$g2c/receipts/provider-validation/$validation_key.json" \
  --provider-validation-code-version m3-g2c-code-v1-dbb1bf76f421dc0486d68bc0585bfff9e95d1d47 \
  --external-qlib-root /mnt/f/AI_Coding/QuantitativeTrading/data/external/qlib/v0.9.7 \
  --stage-root "$g8"
```

## 5. 剩余风险

- 正式命令仍需主 Agent 审查后执行，并重新 fresh 验真所有 G1/G2 输入；本报告不提前记录 experiment key。
- 正式运行身份必须来自提交后的 clean worktree；任何 source/config/pyproject 或依赖环境变化都会产生新身份。
- `py312` 的实际 full dependency fingerprint 会如实记录未安装包；后续训练前若安装 LightGBM/MLflow 等，
  experiment identity 必然变化并需重新发布，不能复用旧 identity。
- 当前文件系统是 DrvFS；Windows/WSL 绿测不替代 ext4/Linux 平台 Gate。
