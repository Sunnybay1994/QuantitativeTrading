# M3 G1-P4C：严格 Reader 与不可变 Release 外部闭环任务单

日期：2026-07-15  
状态：外部实现—独立初验—P0 返工—独立复验—主 Agent 终验完成；P4C 子包已验收  
前置主验：[`M3_G1_P4B主Agent最终验收报告.md`](M3_G1_P4B主Agent最终验收报告.md)  
总设计：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md) §2、§3、§6–§9  
主契约：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.10
最终验收：[`M3_G1_P4C主Agent最终验收报告.md`](M3_G1_P4C主Agent最终验收报告.md)

## 1. 目标与停止边界

P4C 只完成 G1 release 的最后信任边界：

1. 纯函数从 `G1BuildInputs + policy + VerifiedReferenceResponse` 重新执行 P4A/P4B，拒绝 caller 自报
   candidate/audit/quality/PASS；
2. 把 14 张 primary 表、3000-cell detail、严格 summary/quality 写成固定 17 项 artifact；
3. strict reader/verifier 从 final 文件重算 JSON、Schema、逻辑/物理 hash、键范围、primary/release identity；
4. 只在 WSL/Linux 使用目录级 no-clobber 原子发布，已有 release 只允许严格验真复用。

不实现 G2 snapshot，不联网，不调用 connector，不读取配置/TOML/token，不修改 P4A/P4B 算法，不关闭 B4/G1/Gate。

## 2. 文件、环境与禁止项

只允许：

- `src/quant/data/m3_release.py`（新增）；
- `src/quant/data/__init__.py`（只新增冻结导出）；
- `tests/unit/test_m3_g1_release.py`（新增）；
- `docs/M3_G1_P4C不可变发布交付报告.md`；
- 独立初验阶段新增 `docs/M3_G1_P4C不可变发布独立初验报告.md`。

不得修改 `m3_g1_candidate.py`、`m3_reference.py`、domain Schema、配置、路线图或上游测试来迁就 publisher。允许
`m3_release.py` 在同一 `quant.data` 层调用 P4A 已验收的私有 `_primary_candidate_key` 作为唯一 primary identity
实现；不得复制其 canonical envelope。除该明确例外，不依赖上游私有 helper。

外部实现和独立初验使用不同 `cursor-grok-4.5-high` 会话。Windows 只负责启动 Agent；全部 Python/pytest/Ruff/
mypy 经 `wsl.exe` 在 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 使用
`/home/mabw/miniforge3/bin/conda run -n base`。禁止 Windows Python、真实网络、token、`_old/`。

## 3. 公共接口和值对象

在 `quant.data` 包根导出：

```python
class M3ReleaseError(ValueError): ...

@dataclass(frozen=True)
class G1ArtifactEntryV1:
    path: str
    sha256: str
    content_sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    table_schema_version: str
    key_columns: tuple[str, ...]
    min_key: tuple[str, ...] | None
    max_key: tuple[str, ...] | None

@dataclass(frozen=True)
class G1QualityIssueV1:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    count: int
    evidence: tuple[str, ...]

@dataclass(frozen=True)
class G1QualityReportV1:
    schema_version: Literal["m3-g1-quality-v1"]
    release_id: str
    primary_candidate_key: str
    plan_sha256: str
    error_count: int
    warning_count: int
    passed: bool
    issues: tuple[G1QualityIssueV1, ...]

@dataclass(frozen=True)
class G1ManifestV1:
    schema_version: Literal["m3-g1-manifest-v1"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

@dataclass(frozen=True)
class G1Release:
    release_id: str
    root: Path
    manifest_path: Path
    quality_path: Path

@dataclass(frozen=True)
class G1ReleaseInputs:
    build_inputs: G1BuildInputs
    cross_source_policy: G1CrossSourcePolicy
    reference_responses: tuple[VerifiedReferenceResponse, ...]

@dataclass(frozen=True)
class G1PreparedRelease:
    candidate: G1Candidate
    primary_audit: G1PrimaryAuditResult
    reconciliation: CrossSourceReconciliationBundle
    release_id: str
    quality: G1QualityReportV1

@dataclass(frozen=True)
class VerifiedG1Release:
    release: G1Release
    manifest: G1ManifestV1
    manifest_sha256: str
    quality: G1QualityReportV1
    quality_sha256: str
    artifact_paths: tuple[tuple[str, Path], ...]

def prepare_g1_release(*, inputs: G1ReleaseInputs) -> G1PreparedRelease: ...
def publish_g1_release(*, output_root: Path, inputs: G1ReleaseInputs) -> G1Release: ...
def verify_g1_release(*, release: G1Release) -> VerifiedG1Release: ...
def read_g1_manifest(path: Path) -> G1ManifestV1: ...
def read_g1_quality(path: Path) -> G1QualityReportV1: ...
def read_cross_source_summary(path: Path) -> CrossSourceSummaryV1: ...
```

所有 dataclass exact-type 重建；bool 不冒充 int；float finite；tuple/排序/唯一/literal/日期关系/hash/path 自证。
`G1Release` 使用规范绝对 root，`root.name == release_id`，两个 JSON path 必须精确是 root 直属文件。
`VerifiedG1Release.artifact_paths` 精确 17 项，按 manifest path 排序，Path 为 final 下的规范绝对受控路径。

## 4. 稳定失败语义

`M3ReleaseError` 的 `str/repr/args/cause/traceback` 不得泄露绝对路径、raw 值、JSON 内容、PID、ctypes/libc repr 或
凭据；底层 JSON/Polars/Pandera/OSError 统一 `from None`。公开边界只允许：

```text
G1_RELEASE_INPUT_INVALID
G1_RELEASE_QUALITY_FAILED
G1_RELEASE_IDENTITY_MISMATCH
G1_RELEASE_PATH_INVALID
G1_RELEASE_JSON_INVALID
G1_RELEASE_ARTIFACT_INVALID
G1_RELEASE_IO_FAILED
G1_RELEASE_PUBLISH_UNSUPPORTED
G1_RELEASE_CONCURRENT_PUBLISH
G1_RELEASE_VERIFY_FAILED
```

值对象直接非法可抛稳定 `ValueError`；上述六个公开函数必须映射为 `M3ReleaseError`。主异常优先于 cleanup；没有
主异常时 cleanup/fsync/close/post-verify 失败不得静默成功。

## 5. 纯准备、quality 与 release identity

`G1ReleaseInputs.__post_init__` 重建 `G1BuildInputs`、policy 和每个 verified response；不得只检查实例/hex。
`prepare_g1_release` 全程零 IO/网络/环境读取，顺序固定：

1. `build_g1_candidate(inputs.build_inputs)`；
2. `verify_g1_candidate`；
3. `audit_g1_candidate`，不通过即 `G1_RELEASE_QUALITY_FAILED`；
4. `plan_cross_source_reconciliation` 与 `plan_baostock_reference_requests` 重建 sample/request 闭包；
5. `reconcile_cross_source` 从完整原输入 verified responses 重建 bundle，不通过即 quality failed；
6. 以本节 envelope 重算 release ID；
7. 生成 v1 quality。现行 P4A/P4B 无 WARNING，因此可发布 quality 必须 issues 空、两个 count 为 0、passed=true。

release ID 精确为 `SHA256(canonical_json(envelope))`：

```json
{
  "schema_version": "m3-g1-release-identity-v1",
  "primary_candidate_key": "...",
  "sample_plan_sha256": "...",
  "reference_receipts": ["按 (source,endpoint,request_id) 排序的完整 30 个 BaoStock G1ReceiptProjectionV1 对象"],
  "cross_source_detail_sha256": "...",
  "cross_source_summary_sha256": "..."
}
```

canonical JSON：UTF-8、`ensure_ascii=False/sort_keys=True/separators=(",",":")/allow_nan=False`，date 为 ISO，tuple
编码 array，无 BOM/尾换行。quality hash 是严格 quality 对象 canonical bytes SHA-256，不进入 release ID；manifest
绑定它。`G1PreparedRelease` 构造器从 candidate/audit/reconciliation 重算上述 identity 和 quality，不接受 caller
自洽替换其中一层。

## 6. Manifest 自证与 primary identity 补充字段

现行总设计漏了 `price_limit_required_keys_sha256`，导致 final verifier 无法重算 P4A primary key；本任务书已同步
主契约并把它加入 manifest。verifier 必须：

1. 从 14 个 primary artifact 重算按 P4A 表名顺序的 `table_content_digests`；
2. 从 `eligible_keys/price_limit/suspension/calendar/instrument` 和 manifest history window 调用
   `require_g1_price_limit_coverage`，重算并核对 `price_limit_required_keys_sha256`；
3. 从 manifest build 字段构造 `G1BuildSpec`，从 `input_receipts` 只投影 Tushare receipts；
4. 调用 P4A 唯一 `_primary_candidate_key`，用 request plan hash、四日期、Tushare receipts、14 digest、required digest
   重算并核对 `manifest.primary_candidate_key`；
5. 由 primary key、sample hash、manifest 中 30 个 BaoStock receipt、cross detail/summary digest 重算 release ID。

这证明 final 内部 identity 闭包；原始 SDK/raw provenance 仍由 `publish_g1_release` 的原输入重执行证明，不宣称无签名
文件系统可凭空证明外部来源。

manifest dates 精确投影 candidate，满足
`history_start <= signal_start <= signal_end <= history_end`。`input_receipts` 精确等于 Tushare candidate projections
与 30 个 BaoStock projections 的排序拼合；完整 tuple 按 `(source,endpoint,request_id)` 排序且元素不重复。
files 按 path 排序且精确 17 项。所有 version/build/config 字段只能投影 candidate build spec。

## 7. 固定 artifact registry

模块内唯一只读 registry 冻结 path、candidate attr、逻辑 table name、Schema、schema_name、version、key columns；
不得在 writer/reader/test 各复制一份。14 个 primary 项：

| path | candidate attr / logical table | schema_name | key_columns |
|---|---|---|---|
| `universe_membership.parquet` | `membership` / `universe_membership` | `UniverseMembershipSchema` | `universe,symbol,effective_from` |
| `eligible_keys.parquet` | `eligible_keys` / `eligible_keys` | `EligibleKeysV1` | `as_of,symbol` |
| `bar_1d.parquet` | `bars` / `bar_1d` | `Bar1dSchema` | `symbol,trade_date,source` |
| `adjustment_factor.parquet` | `adjustment_factors` / `adjustment_factor` | `AdjustmentFactorSchema` | `symbol,effective_date,source` |
| `adjustment_factor_match.parquet` | `factor_match_evidence` / `adjustment_factor_match` | `AdjustmentFactorMatchSchema` | `symbol,trade_date,source` |
| `benchmark_bar_1d.parquet` | `benchmark_bars` / `benchmark_bar_1d` | `BenchmarkBar1dSchema` | `benchmark,trade_date,source` |
| `suspension_1d.parquet` | `suspensions` / `suspension_1d` | `Suspension1dSchema` | `symbol,trade_date,source` |
| `trade_calendar.parquet` | `calendars` / `trade_calendar` | `TradeCalendarSchema` | `market,date` |
| `instrument.parquet` | `instruments` / `instrument` | `InstrumentSchema` | `symbol` |
| `index_constituent_observation.parquet` | `observations` / `index_constituent_observation` | `IndexConstituentObservationSchema` | `universe,observation_date,symbol,source` |
| `price_limit_1d.parquet` | `price_limits` / `price_limit_1d` | `PriceLimit1dSchema` | `symbol,trade_date,source` |
| `corporate_action_ledger.parquet` | `corporate_actions` / `corporate_action_ledger` | `CorporateActionLedgerSchema` | `event_id` |
| `corporate_action_selection_evidence.parquet` | `corporate_action_selection_evidence` / 同名 | `CorporateActionSelectionEvidenceSchema` | `candidate_id` |
| `corporate_action_reconciliation.parquet` | `corporate_action_reconciliation` / 同名 | `CorporateActionReconciliationSchema` | `symbol,previous_factor_date,effective_date` |

其余三项：

| path | logical content | schema_name | key_columns |
|---|---|---|---|
| `cross_source_reconciliation.parquet` | P4B detail / `cross_source_detail` | `CrossSourceReconciliationDetailV1` | `symbol,trade_date,field` |
| `cross_source_reconciliation.json` | P4B summary canonical object | `CrossSourceSummaryV1` | 空 |
| `quality.json` | quality canonical object | `G1QualityReportV1` | 空 |

所有 `table_schema_version` 精确为 `v1`。Parquet column order 必须等于 canonical candidate/detail；writer 参数固定
`compression="zstd", compression_level=3, statistics=True, row_group_size=65536, use_pyarrow=False`。JSON 必须是
本任务书 canonical bytes。manifest 最后写，不在自身 files 表。

entry `sha256` 为文件 bytes，`content_sha256` 为 `clean_table_content_sha256(logical_table, frame)` 或 JSON canonical
object hash；`size_bytes/row_count` 重算。key tuple 的每格只允许 str/date，date ISO；按 canonical tuple 字典序求
min/max。空 parquet 两者 null；非空均必需。两个 JSON 固定 row_count=1、空 keys、null min/max。

## 8. Strict JSON reader 与 final verifier

三个 reader 拒绝非 UTF-8/BOM、duplicate key、未知/缺字段、错误 exact type、字符串数字、bool 数、NaN/Infinity、
未知 schema/issue code、未排序/重复 tuple、非法 date/path/hash。解析后必须重建全部嵌套 dataclass 并重算 count/
passed；不得只做 JSON Schema。verifier 还要求 JSON bytes 精确等于 canonical bytes，消除同一对象多种物理表示。

`verify_g1_release` 要求：

1. release/root/path exact self-proof，root 与全部祖先无 symlink；final 是真实 directory；
2. final 精确 18 个 entry（manifest+17 artifacts），无未知/隐藏/FIFO/socket/device；每个文件真实 regular、
   `st_nlink==1`，且 `(st_dev,st_ino)` 互不别名；
3. manifest/quality/summary strict reader；manifest bytes SHA 返回为 `manifest_sha256`；
4. files 表 path 集合、排序、bytes hash、size、row count、schema/version/key/min/max 全量重算；
5. Parquet 原 frame 必须已经是 Schema validator 返回的 exact canonical columns/dtypes/values；coercible 错 dtype 也拒绝，
   不能对原 frame 算 bytes、对另一 coerced frame 算 content；
6. 从 cross detail 的 600 个唯一 `(symbol,date)` 重建 `CrossSourceSamplePlan`，从 manifest 取 30 个 BaoStock projections，
   再构造公开 `CrossSourceReconciliationBundle` 重算 3000-cell stats/issues/passed；可发布 final 必须 passed；
7. 执行 §6 primary/release identity 重算；quality 必须 release/primary/plan 对齐、空 issues、passed；manifest
   `quality_sha256/cross_source_summary_sha256` 对齐文件；
8. 成功才返回 17 个按 path 排序的 final 绝对 Path。任何失败不得修补、删除或 quarantine final。

读取过程中对 directory/file identity 做前后快照；祖先、entry 或 inode 在验证期间替换即失败。禁止下游自行拼路径。

## 9. 原子发布状态机

`publish_g1_release`：

1. 先完整 `prepare_g1_release`；失败时 output root 零增量；
2. 准备成功后规范化 output root 为绝对路径，逐祖先 `lstat` 拒 symlink/非目录；安全创建缺失目录并复核 identity；
3. final 已存在：只调用 strict verifier；与 prepared 的 release/primary/sample/summary/quality 精确一致则零写复用，
   否则 `VERIFY_FAILED`，不补写/覆盖/删除；
4. 在 output root 下创建唯一 0700 staging container，内部再建名为 release_id 的 stage-release，使公共 verifier 可
   在发布前验真；
5. 17 项使用 `os.open(O_CREAT|O_EXCL|O_NOFOLLOW)` 的普通文件流写入，flush+file fsync；manifest 最后；fsync
   stage-release 与 staging container；每步 fault 可测试；
6. 发布前在 stage root 调用完整 verifier；
7. 唯一目录 commit primitive 是 libc `renameat2(AT_FDCWD,src,AT_FDCWD,dst,RENAME_NOREPLACE)`。只允许调用导出
   `renameat2`，不得硬编码 syscall number；运行时不支持即 `PUBLISH_UNSUPPORTED`。禁止 `os.rename/os.replace`、
   逐文件 merge 和 check-then-rename fallback；
8. `EEXIST/ENOTEMPTY` 表示 concurrent winner：strict verify final，相同则复用，不同/空/损坏则失败；绝不覆盖；
9. commit 后 fsync output root、立即再次 strict verify，再清理空 staging container。post-fsync/verify/close/cleanup
   失败不得返回成功；主异常优先。失败 cleanup 只清理本 writer 创建且 identity 未漂移的 staging，不碰 final/他人。

发布前后 output root/staging/final 目录 identity 均复核。实现仅面向 WSL/Linux，不写 Windows fallback。

## 10. 实现者必测矩阵

至少覆盖：

1. inputs/policy/response exact rebuild；prepare monkeypatch open/socket/env/clock/RawStore 证明零 IO/network；
2. candidate/response 一格变化、四日期/build spec/receipt/tolerance/行序变化的 release identity 传播与稳定性；
3. caller 自报 candidate/audit/quality 无入口；primary audit 或 cross-source fail 时 output root 零增量；
4. manifest/quality/summary 每个字段的 missing/extra/type/order/duplicate/NaN/Infinity/unknown issue 与 canonical bytes；
5. 17-entry registry exact closure；每个 parquet 少/多列、coercible wrong dtype、row/value/duplicate/order、bytes/content
   hash、size、row count、schema/version/key/min/max 漂移；0 行表；
6. 修改 primary table并同步 entry/manifest/release 自报 hash，primary key 重算仍拒；required price keys 漂移拒；
7. 修改 detail+summary+manifest 为另一自洽套件但 release ID 未对应时拒；600 keys/3000 cells/stats/receipt drift；
8. strict final：extra/hidden entry、symlink、hardlink、FIFO/socket/device、st_nlink、inode alias、祖先/entry 替换；
9. 首次发布、有效 final 零写复用、已有损坏/不同/空 final、两个 writer、winner 在 commit 前创建 final；
10. 每个 open/write/flush/file fsync/dir fsync/renameat2/post-verify/close/cleanup fault；主异常优先；
11. 在真实 WSL tmp_path 验证 renameat2 no-clobber；monkeypatch 不支持/EEXIST/其他 errno；静态无 rename/replace fallback；
12. 四观察面注入绝对路径/raw/token/libc repr；包根 import 无 research/connector/network 反向依赖。

定向通过后运行全量 `pytest -q`、`ruff check src tests`、`mypy src`。默认测试不得联网，只写 pytest 临时目录。

## 11. 独立初验与交付

实现报告 `docs/M3_G1_P4C不可变发布交付报告.md` 必须逐项映射本任务书、列出真实命令/结果/限制，状态只能
“待独立初验/待主验”。独立初验使用全新会话、只读生产代码，至少增加八类实现者未使用反例，必须包含：

- primary table+manifest wholesale 自洽替换；
- summary/detail/receipt 同时重绑；
- coercible dtype 与同 inode/不同 path；
- 并发方先创建空 final；
- rename 成功后的 output-root fsync 或 cleanup 失败；
- strict JSON duplicate/BOM/非 canonical bytes；
- ancestor 在 verify 中途替换；
- `renameat2` 不可用且不得 fallback。

初验失败按“现象—根因—规则—最小复现—新增测试—通过条件”退回原实现 Agent，之后再由全新会话复验，直到
通过才交主 Agent。P4C 通过前不得关闭 B4/G1/M3/Gate 或启动 G2A。
