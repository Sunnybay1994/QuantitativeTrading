# M3 G3A 标签 Artifact 交付报告

日期：2026-08-02

分支：`codex/m3-g2a`

状态：**G3A 工程合同与开发示例闭环通过；正式标签发布因缺少 G8 正式 ExperimentIdentity 而 fail-closed；未关闭 Linux/ext4 Gate，未启动 G3B。**

## 1. 冻结边界

- G3A 只实现标签原语、严格 ExperimentIdentity consumer、标签 Artifact builder/verifier 和共享 receipt 读取加固；ExperimentIdentity 的生产与发布仍归 G8。
- 正式入口只接受 `VerifiedG1Release`、`VerifiedSnapshotArtifact`、`VerifiedProviderArtifact` 和 `VerifiedExperimentIdentity`；开发示例类型保持独立，且始终 `formal_gate_eligible=False`。
- 正式标签固定每次构建一个 horizon，生产只允许 5/10；底层计算保留 h=1 同一交易日 open-to-close 的合法语义。
- 基准唯一采用已批准的 B 路径 `510300.SH`；标签代码不引入第二套基准配置。
- 标签目录严格只有 `labels.parquet`、`diagnostics.parquet`、`label_manifest.json`；receipt 继续使用 E3 公共格式及 verifier。
- 不 import Qlib、不运行真实网络、不写正式 G1/G2 bytes、journal 或候选映射；正式 G3A 只在 G8 身份存在后才能发布。

本轮文件白名单：

```text
src/quant/research/m3/{labels.py,contracts.py,__init__.py,development_example.py,run_state.py}
tests/unit/{test_m3_labels.py,test_m3_label_artifact.py,test_m3_run_state.py}
docs/agent/M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md
docs/agent/M3_G3A标签Artifact交付报告.md
artifacts/formal_g3a_wsl/**  # ignored，只读正式闭包脚本/输出
```

## 2. 实现结果

- `compute_forward_relative_labels` 严格校验输入 schema、唯一递增 SH session calendar、horizon 顺序与有限值；实现 tail、benchmark entry/exit、asset entry/exit、factor entry/exit 的固定优先级与逐候选守恒。
- 新增 `ExperimentIdentitySpec`、`ExperimentIdentityManifestV1`、`VerifiedExperimentIdentity`、`LabelBuildSpec`、`LabelArtifactManifest` 与 `VerifiedLabelArtifact`；开发示例对应 verified capability 与正式类型不可混用。
- ExperimentIdentity 与标签 verifier 从可信 spec/config 重算 identity，拒绝 manifest/key/receipt 整套替换、A/B 产物混配、漏列输入 digest、额外目录项、非规范 JSON、路径逃逸及 symlink/reparse/hardlink 攻击。
- `run_state.verify_stage_receipt_with_bytes` 在同一稳定文件身份上完成 parse/hash；root registry 在读取 digest 前完整验真，嵌套 root 选择最具体 alias。
- 正式 G2A、G2B、G8 产物位于不同 Artifact 根；receipt 寻址现分别从 snapshot、provider、experiment 的可信根解析，不再假定三者共根。新增分离 ExperimentIdentity 根回归，避免开发共根 fixture 掩盖正式链错误。
- 公共边界异常只暴露稳定错误码，不泄露输入路径、payload 或凭据信息。

## 3. 反例覆盖

- 公司行动/factor 手算、Friday→Monday→holiday session、h=1、尾部不足。
- 停牌/缺 entry 或 exit bar、缺两端 factor、benchmark extra/dtype、eligible 污染。
- reason 优先级、candidate/success/diagnostic 守恒、diagnostics 行数与 `sample_count` 总和。
- bars digest 遗漏、A frame+B manifest/receipt、整套 ExperimentIdentity 重签替换。
- 非空输出、额外文件、symlink/reparse/hardlink、读取期间替换、错误脱敏、零 Qlib import。
- snapshot/provider/experiment 分离 Artifact 根与嵌套 root alias。

## 4. 定向验证

在 worktree 根目录执行：

```text
# Windows Miniforge
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_labels.py tests/unit/test_m3_label_artifact.py tests/unit/test_m3_run_state.py -q -p no:cacheprovider
D:\Miniforge3\python.exe -m ruff check src/quant/research/m3/__init__.py src/quant/research/m3/contracts.py src/quant/research/m3/development_example.py src/quant/research/m3/labels.py src/quant/research/m3/run_state.py tests/unit/test_m3_labels.py tests/unit/test_m3_label_artifact.py tests/unit/test_m3_run_state.py
D:\Miniforge3\python.exe -m mypy src/quant/research/m3/__init__.py src/quant/research/m3/contracts.py src/quant/research/m3/development_example.py src/quant/research/m3/labels.py src/quant/research/m3/run_state.py

# WSL Miniforge base
/home/mabw/miniforge3/bin/conda run -n base python -m pytest tests/unit/test_m3_labels.py tests/unit/test_m3_label_artifact.py tests/unit/test_m3_run_state.py -q -p no:cacheprovider
/home/mabw/miniforge3/bin/conda run -n base python -m pytest tests/unit/test_m3_snapshot.py tests/unit/test_m3_provider_materialization.py tests/unit/test_m3_provider_validation.py -q -p no:cacheprovider
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src/quant/research/m3/__init__.py src/quant/research/m3/contracts.py src/quant/research/m3/development_example.py src/quant/research/m3/labels.py src/quant/research/m3/run_state.py tests/unit/test_m3_labels.py tests/unit/test_m3_label_artifact.py tests/unit/test_m3_run_state.py
/home/mabw/miniforge3/bin/conda run -n base python -m mypy --cache-dir=/tmp/mypy-g3a-final-20260802 src/quant/research/m3/__init__.py src/quant/research/m3/contracts.py src/quant/research/m3/development_example.py src/quant/research/m3/labels.py src/quant/research/m3/run_state.py

# WSL Miniforge py312
/home/mabw/miniforge3/bin/conda run -n py312 python -m pytest tests/unit/test_m3_labels.py tests/unit/test_m3_label_artifact.py -q -p no:cacheprovider
```

```text
Windows Miniforge pytest（labels + label artifact + run_state）:
105 passed, 3 skipped

Windows targeted Ruff:
All checks passed

Windows targeted mypy:
Success: no issues found in 5 source files

WSL Miniforge base pytest（labels + label artifact + run_state）:
107 passed, 1 skipped

WSL Miniforge base G2 upstream regression
（snapshot + provider materialization + provider validation）:
81 passed, 2 skipped

WSL Miniforge base targeted Ruff:
All checks passed

WSL Miniforge base targeted mypy（独立 /tmp cache）:
Success: no issues found in 5 source files

WSL py312 pytest（labels + label artifact）:
44 passed, 1 skipped

git diff --check:
PASS
```

Windows 的跳过项是宿主未授予 symlink/reparse 创建能力的能力型跳过。WSL base 对应路径反例已执行；这些开发定向绿测均不等价于 Linux/ext4 不可变发布 Gate。

一次 Windows/WSL mypy 并行运行因共享 `.mypy_cache` 触发 mypy 2.2.0 内部错误；随后 WSL 使用独立 `/tmp/mypy-g3a-final-20260802` 串行复验通过。该次失败属于工具 cache 竞态，不计作代码通过证据，以上仅记录最终独立复验结果。

## 5. 正式输入与阻塞边界

正式闭包在冻结的 WSL py312 环境执行，全程只读：

```text
/home/mabw/miniforge3/bin/conda run --no-capture-output -n py312 \
  python artifacts/formal_g3a_wsl/verify_formal_inputs.py

G1_FRESH_VERIFY=PASS
G2A_FRESH_VERIFY=PASS
G2B_FRESH_VERIFY=PASS
G2C_FRESH_DISK_VERIFY=PASS
provider_validation_key=65bda5759316a1514bc4a8546ec4f2e70a0830ffbfc521bf7fca25cd88e3475e
validation_receipt_sha256=affd75508288548b83420251788e81a3fabc179c47f9209b09cffec73808acfc
G3A_FORMAL_PUBLICATION=BLOCKED_MISSING_G8_EXPERIMENT_IDENTITY
elapsed_seconds=1500.913
```

第一次 preflight 使用 WSL base，得到 G1/G2A PASS 后在 G2B 稳定失败；只读诊断确认 base 缺少冻结 runtime fingerprint 所需的 `fire` 包元数据。改用正式 G2B 所属 py312 后，G2B 单独诊断及上述完整闭包均通过，因此该失败属于环境选择错误，不是正式 Artifact 漂移。

正式 artifacts 中不存在 G8 发布的 `experiment_manifest.json` 与 `experiment-identity` receipt；G3A 没有创建、推导或代签这一身份，也没有写正式 label 目录。

因此当前准确结论为：

- G3A 标签计算与 Artifact consumer 合同：通过。
- 开发示例标签闭环：通过，且不具备正式 Gate 资格。
- 正式 G3A 标签 Artifact：等待 G8 正式 ExperimentIdentity，当前 fail-closed。
- G3B 全量 fresh-Qlib reconciliation：未启动。
- Linux/ext4 Gate：未关闭；当前 WSL 产物与验证位于 `/mnt/f` DrvFS。

下一步应先实现并发布 G8 唯一的正式 ExperimentIdentity 合同，再返回 G3A 对 h=5/h=10 分别构建、发布 receipt、磁盘重验；之后才能启动 G3B。
