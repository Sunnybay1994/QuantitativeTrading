# M3 20260815 retained continuation：LABEL_ARTIFACT_IDENTITY_MISMATCH 只读诊断报告

日期：2026-08-15  
角色：外部只读诊断 Agent（未改源码、测试、配置、artifact、worktree 状态；未 add/commit/push；未跑长链/verifier）  
模型：`cursor-grok-4.6-high`  
范围：worktree `artifacts/dev_worktrees/m1-m4-windows-integration` 临时 detached `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79`；运行目录 `artifacts/agent_runs/m3-twofold-retained-20260814`；resume5 stderr 在 `complete_twofold.py::_ensure_label` → public `verify_label_artifact`。

结论：**首个可证明的 identity 失败点是缺失的 h10 label stage receipt 路径，不是 locator / experiment / snapshot / G1 / `code_version` 字段值漂移，也不需要改恢复脚本的 identity 参数。应删除失败恢复留下的未完成 owned label stage `labels/.../h10` 后由现有脚本重建并正式发布 receipt。h5 已完整且已被同一次 resume5 进程内的 formal resolve 验证通过，禁止删除。**

---

## 现象

`complete_twofold.resume5-20260815.stderr.log` 稳定码：

```text
quant.research.m3.labels.M3LabelArtifactError: LABEL_ARTIFACT_IDENTITY_MISMATCH
```

调用栈（压缩）：

1. `complete()` 第 819 行：`labels = {horizon: _ensure_label(common, horizon) for horizon in (5, 10)}`
2. `_ensure_label` 第 248 行：`verify_label_artifact(...)`
3. `labels.py` 边界包装把内部 `ValueError` 脱敏为 `LABEL_ARTIFACT_IDENTITY_MISMATCH`（不暴露路径/payload）

同一次 resume5 **已经通过** `_common()` → `resolve_formal_backtest_cli_inputs(..., horizon=5)`。该 resolver 在进入 `_ensure_label` 之前就会对 **h5** 调用同一个 public `verify_label_artifact`（`formal_cli_resolve.py` 约 680–699 行）。因此 resume5 的首个失败 **不可能是 h5**；`(5, 10)` 字典推导会再次校验 h5（应通过），然后校验 h10。

---

## 根因

### 1. 第一个具体路径不匹配

| 项 | 证据 |
|---|---|
| 期望 receipt | `{stage_root}/receipts/labels/{experiment_key}-h10.json` |
| 绝对路径 | `...\artifacts\research\m3\_f0r2_9444889ecb4e\receipts\labels\4274090ddeb001bd546fa382c2195e1367327c9e42d9f10f3c2fe9a154edb9a0-h10.json` |
| 实际 | **不存在**。`receipts/labels/` 仅有 `...-h5.json`（2026-08-14 13:09:56 UTC，与原始 producer 同时） |
| h10 label 根 | **存在**，且文件集恰好为 `labels.parquet` / `diagnostics.parquet` / `label_manifest.json`（符合 `_LABEL_FILES`） |
| h10 时间戳 | 2026-08-15 04:12:12 UTC，与 resume2 失败窗口一致，**不是** 2026-08-14 producer |

`verify_label_artifact` → `_verify_labels` 在 tree/manifest 检查之后调用 `_verify_stage_receipt_secure`。`verify_stage_receipt_with_bytes` 对缺失文件返回 `None`，随后 `ValueError("receipt missing")`，被 `@_label_boundary("LABEL_ARTIFACT_IDENTITY_MISMATCH")` 脱敏。

这与 resume2 轨迹闭合：当时 `_ensure_label` 在 `if not root.exists()` 内已跑完 `build_label_artifact`，于 `_rcpt` 失败：

```text
ValueError: artifact 缺失: G8:snapshots/0c57b957…/snapshot_manifest.json
```

即恢复脚本当时仍引用旧名 `snapshot_manifest.json`，正式 snapshot 权威文件名是 `manifest.json`。builder 已写出 h10 三文件，receipt **从未发布**。当前 `complete_twofold.py` 第 243 行已改为 `common.snapshot.root / "manifest.json"`，**identity 参数本身不再需要改**。但 `_ensure_label` 只在 `not root.exists()` 时 `_mkdir` + build + `_rcpt`；h10 根残留导致 resume5 **跳过发布 receipt，直接 verify**，稳定失败。

### 2. 已对齐、因而不是首失败的字段

locator / experiment / h5+h10 `label_manifest.json` 下列字段一致，且与 `_validate_label_spec` / `LabelBuildSpec` 构造一致：

| 字段 | 值 |
|---|---|
| `experiment_key` | `4274090ddeb001bd546fa382c2195e1367327c9e42d9f10f3c2fe9a154edb9a0` |
| `snapshot_id` | `0c57b9579e45f4fa15516b85bd68fe001fd6ce3f9657f21307615b314e745fbb` |
| `g1_release_id` | `fe26912a6e33b4ba9d8daec7664ccf0a0246cf86ca5a3c3380e7d493b3056b2d` |
| `code_version` / `label_build_code_version` | `m3-git-v1-c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79-clean-a1ea75e35afdd4531bd3f99543c8f23b7014fffab01c3ba8dde81f3c37f4902e` |
| `dependency_fingerprint_sha256` | `cac96e56df4a6a9f3ca1354ff9d6e853c3f59b683f4e00abf4cdedda7060b9db` |
| `snapshot_manifest_sha256` | `9f52877861e0d93ff5b31b2775af674075eead743264cad527fd3c962af34640` |
| `experiment_manifest_sha256` | `5837faea5873722ee7fcfc3182031fe6767e8aa968cac8c1db0231ee115d6c89` |
| `g1_release_manifest_sha256` | `63f5b9fb571922371f9fc827bac4ff3d665d4d43dac47d8e9aa2e21d1917d66f` |
| `label_version` | `theoretical_next_open_to_h_close_510300_etf_hfq_proxy_excess_v3` |
| `benchmark` | `510300.SH` |
| config `horizons_sessions` | `[5, 10]` |

h5 receipt 使用 `snapshots/.../manifest.json`（不是旧名）；h5 `label_manifest.json` 与两个 parquet 的文件 SHA-256 与 h5 receipt `outputs` **逐项相等**。h5 不是待删对象。

### 3. 未重跑的检查（非本诊断阻断项）

未执行 `compute_forward_relative_labels` / 再次 `verify_label_artifact`（禁止长链）。因此不声称已现场复算 h10 parquet 与 G1 输入的 frame equality。该残差不改变恢复动作：h10 是失败恢复脚本生成的无 receipt owned stage，无论后续卡在 `receipt missing` 还是（低概率）frame/manifest remake，都必须删除该根后走正式 build+`publish_stage_receipt`。h5 已在同进程 formal resolve 中完整通过，可排除“当前 runtime/`code_version`/G1 逻辑哈希与 retained identity 整体不匹配”。

脚本参数判定：**不修正** `label_build_code_version`、`horizon`、`snapshot_id`、`experiment_key` 或 snapshot 文件名；当前脚本已用 `manifest.json`。需要的是清除未完成 h10 根，而不是改参数。

---

## 应遵循规则

- `AGENTS.md` §5：clean/artifact 必须先过 Schema 与 identity 门禁；失败默认 fail-closed，不得静默补 receipt 或跳过 verifier。
- `AGENTS.md` §9 与 `.ai/workflows/high_risk_change.md`：删除 artifact 用最小权限；只删证明为未完成/失败恢复生成的精确子树，不扩大到整个 owned `stage_root`、G1 release 或 config。
- `labels.py` SSOT：`verify_label_artifact` 要求 label 树闭包 **与** 位于 `receipts/labels/{experiment_key}-h{horizon}.json` 的正式 stage receipt 同时成立；`build_label_artifact` 不等于 stage 完成。
- 不可变发布：禁止手写、复制或改 hash 伪造 h10 receipt 来迁就残留目录。
- 恢复脚本合同：`_ensure_label` 仅在根不存在时 build+`_rcpt`；残留半成品会把后续 resume 锁死在 verify。清除根是与现有脚本兼容的恢复，而不是改 verifier。
- 本诊断边界：不读 parquet/模型/正式 data 内容，不输出 token/账号；不改 worktree HEAD。

---

## 最小复现（只读，本会话未执行）

前置：worktree 仍为 `c9f2f36…`；解释器为 retained 链绑定的 `D:\Miniforge3\envs\m3chain312\python.exe`；`PYTHONPATH` 含 worktree 根。

1. 确认 `Test-Path`：h10 label 根为 True；`...-h10.json` receipt 为 False；`...-h5.json` 为 True。
2. 运行（主 Agent 恢复时，非本诊断）：`complete_twofold.py --locator <run_dir>/locator.json`。
3. 预期：`_common` 成功（h5 fresh verify 通过）→ `_ensure_label(5)` 通过 → `_ensure_label(10)` 在 `verify_label_artifact` 抛 `LABEL_ARTIFACT_IDENTITY_MISMATCH`。
4. 对抗性反例（实现者未写进 resume5 日志、本诊断补）：h5 与 h10 的 `label_manifest` 共享同一组 upstream identity 字段，唯一结构差异是 `horizon_sessions` 与 horizon 专有 `labels_sha256`/`label_key_sha256`；因此把失败归因于 `code_version` 或 snapshot request key 与 HEAD 漂移 **不成立**（那些失败发生在更早的 resume/resume4，且 resume5 已越过 resolve）。

---

## 安全恢复步骤（供主 Agent；本诊断未执行）

1. 保持 worktree detached 在 `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79`，不要切回 `29dabeb` 直到本 continuation 完成。
2. **只删除** 下列目录（失败恢复生成的未完成 owned label stage），不要删父目录 `labels/{experiment_key}/` 或整个 `_f0r2_9444889ecb4e`：
   - `artifacts/dev_worktrees/m1-m4-windows-integration/artifacts/research/m3/_f0r2_9444889ecb4e/labels/4274090ddeb001bd546fa382c2195e1367327c9e42d9f10f3c2fe9a154edb9a0/h10`
3. 删除前核对该目录仅含上述三文件、时间戳为 2026-08-15 04:12:12 UTC、且不存在对应 `...-h10.json` receipt。
4. 用同一 locator、同一 `m3chain312`、已修正的 `complete_twofold.py`（snapshot 文件名为 `manifest.json`）恢复 continuation。脚本应对 h10 走 `_mkdir` → `build_label_artifact` → `_rcpt` → `verify_label_artifact`。
5. 保留 h5 label 树与 `...-h5.json`、G1 release、snapshot、experiment、既有 `work/26e062f8…` 下游 stage。
6. 完成后按既有用户指示把 worktree 恢复到 `codex/m1-m4-windows-integration@29dabeb…`。

---

## 禁止项

- 禁止手写、拷贝 h5 receipt 或改 SHA 生成 h10 receipt。
- 禁止删除 h5、整个 owned `stage_root`、G1 release、`configs/research/_m3_f0r3_twofold_session.toml`、snapshot 或 experiment。
- 禁止为绕过本失败修改 `verify_label_artifact`、放宽 receipt 合同、或把 `root.exists()` 改成跳过 verify。
- 禁止再把 snapshot 权威文件名改回 `snapshot_manifest.json`。
- 禁止读取/输出 parquet、模型、正式 data 内容或 token/ignored 凭据。
- 禁止 add/commit/push；禁止用 Windows 反馈环宣布 Gate 通过。
- 本 Agent 未改任何非本报告文件；本报告不是 Gate 通过声明。

---

## 判定摘要

| 问题 | 判定 |
|---|---|
| 首个不匹配 | 路径：`receipts/labels/{experiment_key}-h10.json` **缺失**（`receipt missing` → `LABEL_ARTIFACT_IDENTITY_MISMATCH`） |
| 字段/版本漂移 | 未发现；locator 与 h5/h10 manifest、experiment、`code_version` 对齐 |
| 删哪个 owned stage | **仅** `labels/{experiment_key}/h10`（resume2 失败恢复半成品） |
| 改哪个脚本参数 | **不需要**；snapshot 文件名已是 `manifest.json` |
| 证据不足项 | 未现场重算 h10 frame rebuild（禁止长链）；**不**因此改为 `INSUFFICIENT`，因缺失 receipt 已足够阻断且恢复动作相同 |
