# M3 E3 严格 Receipt 独立初验报告（复验）

日期：2026-07-13  
初验 Agent：未参与 E3 实现与本轮返工编码的外部 Agent  
任务单：[`M3_E3严格Receipt独立初验任务单.md`](M3_E3严格Receipt独立初验任务单.md)  
实现合同：[`M3_E3严格Receipt增量返工任务单.md`](M3_E3严格Receipt增量返工任务单.md)  
交付线索：[`M3_E3严格Receipt增量返工交付报告.md`](M3_E3严格Receipt增量返工交付报告.md)（含末尾初验返工补丁）

## 结论

**独立初验通过，进入主验。**

本结论仅表示：R1–R4 合同与上一轮 P0/P1 返工经独立复验可进入主 Agent 终验。  
**不宣称 E3 / M3 / 任一 Gate 通过，不勾选路线图。**

---

## 上一轮问题关闭状态

| 编号 | 问题 | 状态 | 证据 |
|---|---|---|---|
| P0 | `raise ... from exc` 使 `__cause__` / traceback 泄露绝对路径 | **已关闭** | `run_state.py` 全部对外 `raise` 为 `from None`（约 20 处）；无残留 `from <exc>`；新增 `test_exception_chain_and_traceback_omit_absolute_paths`；独立对抗三分支均 `exc.__cause__ is None` 且 `traceback.format_exception` 不含绝对路径 |
| P1 | HOME→`/mnt/g` 祖先 symlink 与挂载盘 `os.link` 边界 | **已关闭（披露，不放宽合同）** | 交付报告末尾已披露：未 resolve 的 `/home/mabw/win/...` 因祖先 symlink 报「路径组件为 symlink」；编排须传入无 symlink 祖先路径或先 `resolve()`；**不得**回退 `os.replace`。挂载盘实测 `os.link` no-clobber 可用（见下） |
| P2 | （本轮返工输入无独立 P2） | **无待关闭项** | — |

问题清单：**无未关闭 P0/P1。**

---

## R1–R4 逐项证据

### R1：版本与严格 JSON

| 检查点 | 源码 | 既有测试 | 独立对抗 |
|---|---|---|---|
| `StageReceipt` frozen/kw_only + 默认 `m3-stage-receipt-v1`；scope 含 `ACCEPTANCE` | `run_state.py` `StageReceipt` / `_SCOPES` | `test_stage_receipt_default_version_and_rejects_bad`；`test_acceptance_scope_round_trip` | 错误 version / list 冒充 tuple 直接构造均拒绝 |
| 字段集精确；duplicate-aware；规范字节精确比较；`allow_nan=False` | `_load_receipt_bytes`、`_duplicate_aware_object`、`_canonical_receipt_bytes` | `test_rejects_duplicate_keys_unknown_fields_bad_types`；`test_rejects_noncanonical_json_bom_crlf_reorder_trailing`；`test_verify_rejects_corrupt_mismatch_and_old_versionless` | —（既有覆盖充分） |
| direct constructor 同校验；裸 hex `scope_key` | `ArtifactDigest`/`StageReceipt` `__post_init__` | `test_artifact_digest_and_receipt_reject_direct_illegal_construct` | `size_bytes=True`、坏 version、`inputs=[]` 均拒绝 |

### R2：路径与 symlink

| 检查点 | 源码 | 既有测试 | 独立对抗 |
|---|---|---|---|
| 完整 root registry 先验真（含未引用条目） | `_validate_artifact_roots` 在 digest 读取前调用 | `test_unused_invalid_root_rejected_before_digest_read` | unused symlink root → `root:unused_illegal 为 symlink`，失败于 digest 前 |
| root/ancestor/leaf 无 symlink；POSIX 相对路径；inode 去重；双侧自引用 | `_assert_no_symlink_components`、`(st_dev,st_ino)`、`_assert_context_consistency` | `test_symlink_cases_rejected`；`test_nested_root_aliasing_and_hardlink_dedupe`；`test_duplicate_physical_root_alias_rejected`；`test_receipt_self_ref_input_output_and_hardlink` | HOME 前缀路径报「路径组件为 symlink」（与披露一致） |
| 错误脱敏（str / chain / traceback） | 全部 `from None`；消息用 alias/类别 | `test_path_safety_and_error_messages_without_abs`；`test_exception_chain_and_traceback_omit_absolute_paths` | 越界 / 缺 parent / 缺 artifact：`__cause__ is None`，traceback 无绝对路径 |

### R3：发布与 DatasetSnapshot 边界

| 检查点 | 源码 | 既有测试 | 独立对抗 |
|---|---|---|---|
| 同目录 temp + fsync + artifact 再验真 + `os.link` no-clobber；仅 `FileExistsError` 复用 | `publish_stage_receipt` L318–345 | `test_concurrent_noclobber_same_and_conflict`；`test_identical_republish_reuses_after_verify`；`test_reuse_refused_when_artifact_mutated`；`test_conflicting_receipt_rejected` | race 三分支：同字节复用 / 冲突不覆盖 / artifact 漂移拒绝；非 `FileExistsError` →「原子创建失败」且无残留 receipt |
| 生产路径无 `os.replace` | `run_state.py` / `contracts.py` / `snapshot.py` 无匹配 | — | 静态 `rg` 确认 |
| `DatasetSnapshot` 去 `provider_path`；裸 hex | `contracts.py` 字段顺序与 `__post_init__` | `test_m3_contracts.py` / `test_m3_snapshot.py` | — |

### R4：六个 public identity + snapshot 裸 hex

| 检查点 | 源码 | 既有测试 | 独立对抗 |
|---|---|---|---|
| 六函数 + 包根导出；统一 JSON 数组 join；裸 64 hex | `run_state.py`；`__init__.py` 导出；`snapshot._stable_hash` → `hexdigest()` | `test_identity_keys_stable_bare_hex_and_sensitive`；`test_json_array_join_collision_via_public_keys`；`test_r4_change_propagation_matrix`；非法输入系列 | PVC 变 → validation 变、experiment/work 不变；reconciliation 随 validation receipt 变；`horizon=True` 拒绝；输出无 `sha256:` |
| snapshot hash 只改输出前缀 | `snapshot.py` `_stable_hash` | `test_m3_snapshot.py` | — |

---

## 挂载盘 `os.link` 证据

在 **resolve 后的 Windows 挂载路径**（非 HOME symlink 前缀）实测：

- 目录：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant/.e3_reverify_tmp_<pid>/`（结束后已删除）
- `publish_stage_receipt` 成功创建 receipt（内部 `os.link`）
- 对已存在 receipt 再 `os.link(temp, receipt)` → `FileExistsError`（no-clobber）
- 冲突参数重发 → `已存在冲突 receipt，拒绝覆盖`，字节未变，`__cause__ is None`
- 同参数复用成功

结论：挂载盘上 E3 合同所需 `os.link` no-clobber **可用**；不建议、也不需要放宽为 `os.replace`。HOME 前缀失败属祖先 symlink 合同执行，应由编排 `resolve()`，披露充分。

---

## 任务单 §4 对抗抽检摘要

| 项 | 结果 |
|---|---|
| unused illegal root | PASS：未引用 symlink root 先验失败 |
| exception chain（越界 / 缺 parent / 缺 artifact） | PASS：`__cause__ is None`，traceback 无绝对路径 |
| race 三分支 + 非 FEE | PASS：复用 / 冲突保留 / 漂移拒绝 / PermissionError→稳定消息 |
| identity 传播 | PASS：PVC 不影响 experiment/work；recon 跟踪 validation receipt |
| 直接构造非法 | PASS：bool size / 坏 version / list I/O |
| HOME 祖先 symlink | PASS：与披露一致，报「路径组件为 symlink」 |

临时目录均在 `/tmp` 与挂载盘受控目录，**已清理**；未写入项目测试树。

---

## 静态禁止项

| 项 | 结果 |
|---|---|
| E3 生产路径无 `os.replace` | `run_state.py` / `contracts.py` / `snapshot.py`：**无** |
| 不返回 `sha256:<hex>` | identity / `_stable_hash` 输出裸 hex；源码无生产返回前缀 |
| 无 data→research 反向 import | `src/quant/research/m3` 内无匹配 |
| 修改范围未扩到 G1/B2A/G8/G9 | 交付清单限于 m3 `run_state`/`contracts`/`snapshot`/`__init__` 与三组单测；初验未改生产代码 |
| 对外 raise 无 `from <exc>` | 仅 `from None` |

注：`fetch_qlib_tool.py` 仍有 `os.replace`，属工具落盘路径，不在 E3 receipt 发布合同内。

---

## 命令结果表

工作目录：`/home/mabw/win/Cursor/quant`；解释器：WSL Miniforge base。

| 命令 | 结果 | 退出码 |
|---|---|---|
| `PYTHONPATH=src conda run -n base --no-capture-output python -m pytest tests/unit/test_m3_run_state.py tests/unit/test_m3_contracts.py tests/unit/test_m3_snapshot.py -q` | **77 passed**, 30 warnings（pandera DeprecationWarning） | **0** |
| `PYTHONPATH=src conda run -n base --no-capture-output python -m pytest -q` | **477 passed**, 1179 warnings（同上类） | **0** |
| `conda run -n base --no-capture-output python -m ruff check src tests` | All checks passed! | **0** |
| `conda run -n base --no-capture-output python -m mypy src` | Success: no issues found in **72** source files | **0** |

Windows conda profile 噪声未出现；上述退出码均为项目真实结果。

---

## 已知限制

1. receipt 原子创建不提供多 artifact 跨文件事务；外部写入在最后一次验真后仍有 TOCTOU，复用/验真 fail-closed。
2. 父目录 `fsync` 在部分挂载上可能落入 `EINVAL/ENOTSUP/EOPNOTSUPP` 忽略分支；已按合同披露，不得回退覆盖式发布。
3. 经 HOME symlink（`/home/mabw/win` → `/mnt/g/...`）的未 resolve 路径会被祖先 symlink 检查拒绝；G8 编排必须传入无 symlink 祖先路径或先 `resolve()`。
4. E3 不实现 DAG/CLI/MLflow/acceptance；这些仍属后续 Gate，**本初验不覆盖**。

---

## 问题清单

**无未关闭 P0/P1。**

（本轮复验未发现新的 P0/P1/P2。）
