# M3 E3 严格 Receipt 增量返工交付报告（R1–R4）

执行范围：[`M3_E3严格Receipt增量返工任务单.md`](M3_E3严格Receipt增量返工任务单.md)  
契约 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.2 / §4.9  
设计审查：[`M3_E3设计审查与修订记录.md`](M3_E3设计审查与修订记录.md)  
日期：2026-07-13

**本报告不勾选路线图 G0–G9，不宣称 E3 / M3 或任何 Gate 已通过。**  
状态：`待初验`（实现 Agent 自测通过，需独立初验 Agent）。未实现 DAG/CLI/MLflow/acceptance；未联网；未触碰 `_old/`、G1/B2A、G8/G9 或路线图。

---

## R1：版本与严格 JSON

- **修改：** `src/quant/research/m3/run_state.py`，`tests/unit/test_m3_run_state.py`
- **行为：**
  - `StageReceipt`：`@dataclass(frozen=True, kw_only=True)`，默认 `receipt_version="m3-stage-receipt-v1"`；scope 含 `ACCEPTANCE`
  - 顶层字段精确为 `receipt_version,stage,scope,scope_key,inputs,outputs`；digest 精确为 `root_alias,relative_path,size_bytes,sha256`
  - 读算法：`read_bytes` → 严格 UTF-8 → duplicate-aware parse（`parse_constant` 拒绝）→ 值对象构造 → 规范重编码 → 与原始 bytes 精确比较
  - 规范编码：`sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False`
  - `ArtifactDigest` / `StageReceipt` 直接构造执行同一套内在校验；`inputs/outputs` 必须为 exact tuple of `ArtifactDigest`；`scope_key` 为裸 64 小写 hex
- **反例：** duplicate 顶层/digest key；未知字段/版本；BOM/CRLF/尾随换行/乱序；`size_bytes=true/"3"`；大写/短 hash；list 冒充 tuple；交叉重复；ACCEPTANCE round-trip；旧无版本 fail-closed

## R2：路径与 symlink

- **行为：**
  - 完整 `artifact_roots` 先验真；root 必须存在、为目录、非 symlink；锚点→root→leaf 全链无 symlink
  - 两 alias 同物理 root 拒绝；嵌套 root 允许布局，按 `(st_dev,st_ino)` 拒绝同一普通文件重复进入 inputs∪outputs（含 hard-link）
  - 相对路径：`PurePosixPath(text).as_posix() == text`；拒绝绝对/UNC/盘符/`./..`/空段/双斜杠/尾斜杠/反斜杠/控制字符/`:`
  - `receipt_path` 必须落在显式 root 内且父目录已存在；publish 不创建未声明父目录
  - receipt 自引用按物理身份在 inputs/outputs 双侧拒绝
  - 对外错误不含本机绝对路径；dangling symlink ≠ ENOENT/`None`
- **反例：** root/祖先/内部 symlink；同物理 root 双 alias；嵌套别名同一文件；hard-link；receipt 在 roots 外；父目录缺失；receipt 作 input / hard-link input；错误文本无绝对路径

## R3：发布与 DatasetSnapshot

- **修改：** `run_state.py`；`contracts.py`；对应单测
- **发布：** 同目录临时普通文件 → flush+`fsync` → artifact 再验真 → `os.link(temp, receipt)` no-clobber；仅 `FileExistsError` 进入「同规范字节 + `verify_stage_receipt` 全量验真」复用；冲突不覆盖；**无 `os.replace`**
- **复用：** 相同 receipt 字节但 artifact 已变更必须拒绝
- **父目录 fsync：** 只忽略 `EINVAL/ENOTSUP/EOPNOTSUPP`；link 成功后 fsync 失败保留已发布文件
- **DatasetSnapshot：** 字段顺序 `snapshot_id,manifest_path,source_fingerprint,row_count,symbol_count,start,end`；移除 `provider_path`；`snapshot_id`/`source_fingerprint` 裸 64 hex；无兼容 alias

## R4：六个 identity 接口 + snapshot 生产入口

- **修改：** `run_state.py`；`snapshot.py`（仅 `_stable_hash` 输出编码）；`__init__.py` 包根导出
- **接口（均输出裸 64 小写 hex，统一 JSON 数组 join）：**
  - `compute_snapshot_request_key`
  - `compute_provider_key`（含 `provider_runtime_fingerprint_sha256`）
  - `compute_provider_validation_key`
  - `compute_experiment_key`
  - `compute_label_reconciliation_key`
  - `compute_work_key`
- **输入：** hash/id 恰为 str 裸 hex；version/fold 稳定字符串且拒 `unavailable`（大小写不敏感）；fold path-safe；horizon 恰为 int 且 >0（拒 bool）
- **传播：** validation 配置变 → experiment/work 相等，validation/reconciliation 不等；LightGBM / NumPy-Qlib / label 容差矩阵按任务单断言
- **碰撞：** 经 public key 证明 `("ab","c") != ("a","bc")`
- **snapshot：** `_stable_hash` / `snapshot_id_from_manifest` 去掉 `sha256:` 前缀，可直接喂给 `compute_provider_key`

---

## 修改文件清单

| 文件 | 变更 |
|---|---|
| `src/quant/research/m3/run_state.py` | R1–R4 全面重写 |
| `src/quant/research/m3/contracts.py` | DatasetSnapshot 去 `provider_path` + 裸 hex |
| `src/quant/research/m3/snapshot.py` | `_stable_hash` 裸 hex 输出 |
| `src/quant/research/m3/__init__.py` | 导出六个 identity 函数 |
| `tests/unit/test_m3_run_state.py` | 反例优先后随实现迁移 |
| `tests/unit/test_m3_contracts.py` | DatasetSnapshot 调用点 |
| `tests/unit/test_m3_snapshot.py` | 裸 hex + 去 `provider_path` |

---

## 命令摘要

```text
PYTHONPATH=src conda run -n base python -m pytest \
  tests/unit/test_m3_run_state.py tests/unit/test_m3_contracts.py tests/unit/test_m3_snapshot.py -q
76 passed

PYTHONPATH=src conda run -n base python -m pytest -q
476 passed

conda run -n base python -m ruff check src tests
All checks passed!

conda run -n base python -m mypy src
Success: no issues found in 72 source files
```

Symlink/hardlink 单测使用 `/tmp` 原生 Linux FS，以避免 Windows 挂载盘对 link 语义的限制；父目录 fsync 在部分挂载上可能落入「不支持」忽略分支，报告不宣称跨文件事务或消除外部 TOCTOU。

---

## 未实现项

| 项 | 原因 |
|---|---|
| DAG / CLI / MLflow / StageRunner | 任务单明确排除；属 G8/G9 |
| Acceptance Gate / 路线图勾选 | 禁止实现者宣称 Gate 通过 |
| 多 artifact 跨文件事务 | SSOT/审查明确不承诺 |

## 合同矛盾

实现过程中未发现任务单与 Python/WSL 文件系统真实行为的不可调和冲突；未自行放宽合同。

---

## 初验返工补丁（2026-07-13）

独立初验 P0：对外 `ValueError` 曾通过 `raise ... from exc` 保留 `FileNotFoundError` /
`Path.relative_to` 等底层异常，导致 `__cause__` 与默认 traceback 泄露绝对路径。已全部改为
`from None`，并新增 `test_exception_chain_and_traceback_omit_absolute_paths`。

独立初验 P1（不放宽合同，仅披露）：实现用 `os.path.abspath`（不解引用）检查祖先组件无
symlink。本机 `/home/mabw/win` → `/mnt/g/BaiduSyncdisk/wsl` 为 symlink，因此经 HOME 前缀的
未 resolve 工作区路径 publish 会报 `路径组件为 symlink`；经 resolve 后的 `/mnt/g/...` 路径可
正常 `os.link` no-clobber。G8 编排必须向 E3 传入无 symlink 祖先的路径（或先 `resolve()`），
不得为此回退 `os.replace`。
