# M3 E3 严格 Receipt 增量返工任务单

日期：2026-07-13  
状态：**已通过**；外部返工与独立复验关闭主验问题，主 Agent 最终验收通过  
原交付：[`M3_E0_E3交付报告.md`](M3_E0_E3交付报告.md)  
缺口来源：[`M3_G9设计审查与修订记录.md`](M3_G9设计审查与修订记录.md)  
设计审查：[`M3_E3设计审查与修订记录.md`](M3_E3设计审查与修订记录.md)  
主验返工：[`M3_E3严格Receipt主验一次返工任务单.md`](M3_E3严格Receipt主验一次返工任务单.md)  
最终验收：[`M3_E3严格Receipt主Agent最终验收报告.md`](M3_E3严格Receipt主Agent最终验收报告.md)

## 1. 范围

只加固 `src/quant/research/m3/run_state.py`、`contracts.py`、`snapshot.py` 中 snapshot hash 的单行迁移、
包导出和对应单测；不实现 DAG、CLI、MLflow、acceptance 或业务算法。保留规范 JSON、字段排序和 join
编码；按 SSOT 增补 provider/runtime、validation 与 reconciliation 的身份字段属于必要迁移，不得为了
保持旧 key 而遗漏新契约。不得修改 `_old/`、Tushare 配置、G1/B2A 或路线图 Gate 状态。

## 2. R1：版本与严格 JSON

`StageReceipt` 固定为 `@dataclass(frozen=True, kw_only=True)`，首字段
`receipt_version: Literal["m3-stage-receipt-v1"] = "m3-stage-receipt-v1"`，scope 增加 `ACCEPTANCE`。读取时严格要求
顶层字段精确为 `receipt_version,stage,scope,scope_key,inputs,outputs`；digest 字段精确为
`root_alias,relative_path,size_bytes,sha256`。未知/缺失字段、未知版本、duplicate JSON key、NaN/Infinity、
bool 冒充 int、字符串数字和宽松 `str()/int()` 强转全部拒绝。

`stage/scope_key/root_alias/relative_path` 必须是非空、无控制字符的字符串；stage/key 不是路径，拒绝
`/`、`\\`、`.`、`..` 和纯空白。`size_bytes` 是非负 int，SHA-256 是 64 位小写 hex。输入输出分别排序且
不重复；同一 `(alias,path)` 同时出现在 input/output 也拒绝。`ArtifactDigest`、`StageReceipt` 由 Python
直接构造时执行相同校验；禁止构造无效对象后依赖 publish/verify 偶然拦截。
`inputs/outputs` 必须是 exact tuple，元素必须是 `ArtifactDigest`；值对象只做内在合同校验，root、inode、
文件存在性与内容 hash 由 publish/verify 上下文校验。`scope_key` 是 scope identity，必须为裸 64 小写 hex。

JSON duplicate 检测必须覆盖顶层和每个 digest object。读取算法固定为 `read_bytes`、strict UTF-8 decode、
duplicate-aware parse 且 `parse_constant` 拒绝、strict object construction、canonical encode、原始 bytes 精确比较。
合法文件字节必须恰等于规范重编码：
`sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False`，不接受仅语义等价的缩进、字段乱序、
UTF-8 BOM、CRLF、尾随换行或非 ASCII 直写。这样 receipt 自身 SHA 才具有唯一含义。

## 3. R2：路径和 symlink

每个 artifact root 必须存在、是目录且自身不是 symlink；从已有文件系统锚点到 root，以及从 root 到
artifact 的每个已有组件均不得是 symlink，即使最终仍指向 root 内。两个 alias 若指向同一物理 root 必须
拒绝。不同 root 可按实际 artifact 布局嵌套，但必须再按现有普通文件的稳定物理身份去重，拒绝同一文件
通过父/子 root 两种相对路径或 hard-link 重复进入 inputs、outputs 或两者交叉集合。文件必须是普通文件。
稳定物理身份固定为 `lstat` 的 `(st_dev,st_ino)` 或 `os.path.samestat` 等价判断；`resolve()` 与内容 hash
不能识别 hard-link，无法取得可靠身份时 fail-closed。

相对路径必须是规范 POSIX 字节表示：`PurePosixPath(text).as_posix() == text`；拒绝 POSIX/Windows 绝对路径、
UNC、盘符相对路径、`.`、`..`、空段、双斜杠、尾斜杠、反斜杠、控制字符和 `:`。继续拒绝未知 alias、
路径逃逸和 receipt 自引用。receipt 已存在时，其自身及父链 symlink/非普通文件必须拒绝；发布时已存在
父链也须无 symlink。`receipt_path` 必须位于至少一个显式 artifact root 内，直接父目录必须已存在且为
无 symlink 普通目录；publish 不创建未声明父目录。receipt 自引用在 inputs/outputs 任一侧都拒绝，按物理
文件身份判断，不只比较字符串路径。完整 `artifact_roots`（包括没有被 digest 引用的条目）必须在任何
artifact 读取前全部验真。
错误信息只使用稳定类别或 alias+relative path，不输出 receipt/root/artifact 的本机
绝对路径，也不把底层 `OSError` 的绝对路径串接到对外消息。
verify 先验证完整 root registry、receipt containment、parent 与 leaf 的 `lstat`；只有 leaf 真正 ENOENT
才返回 `None`。dangling symlink 的 `.exists()==False` 不能解释成“尚未运行”。

## 4. R3：发布与 DatasetSnapshot 边界

`publish_stage_receipt` 使用同一严格 validator 构造对象，规范 JSON显式 `allow_nan=False`。相同字节只有在
调用 `verify_stage_receipt` 对现有 receipt 及全部 artifact 重新验真后才可复用；仅比较 receipt 字节不够。

发布固定为同目录临时普通文件写入、flush+`fsync`、artifact 再验真、Linux/WSL 原子 no-clobber 创建
（可用同文件系统 `os.link(temp, receipt)`）。并发目标已存在时重新走“相同规范字节 + 全量验真”规则；
不同字节冲突拒绝。禁止 `os.replace` 或其他覆盖式 fallback。清理 temp，父目录 `fsync` 尽力执行并在报告
披露不支持的文件系统边界；不得宣称多 artifact 跨文件事务或消除外部写入 TOCTOU。
只捕获 `FileExistsError` 进入并发复用；其他 link 错误脱敏失败。cleanup 不得掩盖主异常。父目录 fsync
只忽略 `EINVAL/ENOTSUP/EOPNOTSUPP`；其他错误以稳定消息失败。若 link 已成功而目录 fsync 失败，保留已发布
receipt，重试按严格 verifier 复用，不删除或覆盖。

`contracts.DatasetSnapshot` 最终字段依次为 `snapshot_id,manifest_path,source_fingerprint,row_count,
symbol_count,start,end`，移除 `provider_path`；`snapshot_id/source_fingerprint` 均为裸 64 位小写 hex，
snapshot 只保留 snapshot manifest/内容摘要，provider
始终由独立 `provider_key/provider_dir/receipt` 表达。修正调用和单测，不增加兼容 alias。

## 5. R4：Provider、validation 与 reconciliation 身份

严格实现并统一加固 SSOT 4.9 的全部六个 public identity 接口：

- `compute_provider_key` 加入 `provider_runtime_fingerprint_sha256`；
- 新增 `compute_provider_validation_key`，绑定 provider key/receipt、`provider_validation_config_sha256`、provider runtime 和 code；
- 新增 `compute_label_reconciliation_key`，绑定 experiment、horizon、provider-validation receipt、label
  manifest、`label_reconciliation_config_sha256`、完整 dependency fingerprint 和 code。
- 新增 `compute_snapshot_request_key`，绑定 G1 release/manifest、narrow snapshot config 与 code；G8 不得
  自行直接拼接这些字段。
- 现有 `compute_experiment_key` 与 `compute_work_key` 同步执行相同严格输入校验，不保留 `"snap-a"`、
  `"recv-a"` 等旧宽松值。

这些函数只消费已经校验的 64 位小写 hash、非空稳定版本和正 horizon，不读取环境或文件。hash 参数和
具名 `*_key/*_id` 参数必须是 **type 恰为 str** 的裸 64 位小写 hex；版本/fold 是无首尾空白、无控制字符、
非 `unavailable`（大小写不敏感）的稳定字符串；fold 另须 path-safe，拒绝 `/\\:.`、`..`；horizon 是
**type 恰为 int** 且大于 0，bool 拒绝。逐函数分类如下：

- snapshot request：`g1_release_id/g1_release_manifest_sha256/snapshot_config_sha256` 是 hash/id，
  `code_version` 是稳定 version；
- provider：`snapshot_id/provider_config_hash/dump_tool_sha256/provider_runtime_fingerprint_sha256` 是 hash/id，
  `qlib_version/code_version` 是稳定 version；
- provider validation：除 `code_version` 外全部是 hash/id；
- experiment：除 `code_version` 外全部是 hash/id；
- label reconciliation：除 `horizon/code_version` 外全部是 hash/id；
- work：`experiment_key` 是 hash/id，`fold` 是 path-safe 稳定字符串，`horizon` 是正 int。

只改 LightGBM
时 provider key 不变，experiment/reconciliation/work 改变；只改 NumPy/pandas/Qlib 时 provider、experiment、
reconciliation、work 都改变；只改 provider 抽样时 snapshot/provider/experiment/features/work 不变，
provider-validation、所有绑定其 receipt 的 reconciliation 与 acceptance 改变；只改 label 对账容差时仅
reconciliation/acceptance 改变，snapshot/provider/experiment/features/work 均不变。provider-validation PASS
是 experiment/features 的编排前置，不进入其内容 receipt inputs。
六个接口必须从 `quant.research.m3` 包根导出；不得让 G8/G9 import 私有 `_identity_key`。

所有 key/digest 输出统一为裸 64 位小写 hex，禁止 `sha256:` 前缀；join 仍用原规范 JSON 数组算法。当前
项目位于 Windows 挂载盘，冒号不能进入目录名。旧带前缀测试必须迁移且不得双格式兼容。
所有具名 key 函数复用同一个规范 JSON 数组 join；禁止直接字符串拼接。增加
`("ab","c") != ("a","bc")` 的碰撞反例，不为此给既有数组编码增加无关 namespace 或迁移既有字段顺序。

`snapshot.py::_stable_hash` / `snapshot_id_from_manifest` 是 `snapshot_id` 的当前生产入口，本次同步去掉
`sha256:` 前缀；只迁移返回编码，不改变 manifest 字段、hash 输入、排序或 snapshot 业务逻辑。否则 E3
会严格拒绝项目自身生产的 snapshot ID，属于不可接受的断裂。

## 6. 必测反例

除原 E3 测试外至少增加：duplicate 顶层/digest key；未知字段/版本；非规范但语义等价 JSON；BOM/CRLF；空 stage/key；`size_bytes=true/"3"`；
大写/短 hash；input/output 交叉重复；root 自身 symlink；root 内文件/父目录 symlink；内部 symlink 指内部
文件；root 祖先 symlink；两个 alias 同物理 root；receipt 文件/父链 symlink；控制字符；错误文本无绝对路径；
ACCEPTANCE 合法 round-trip；旧无版本 receipt fail-closed；DatasetSnapshot 不再接受 provider path；直接
构造非法 `ArtifactDigest/StageReceipt` 失败。
另测：省略 receipt version 得到 v1，显式错误版本失败，list 冒充 tuple 失败，dangling receipt symlink 拒绝。

路径测试另含：父/子嵌套 root 对同一文件的别名、同 inode hard-link、receipt 位于全部 roots 外、receipt
父目录不存在、receipt 与 output 为 hard-link。嵌套 root 本身合法，仅物理文件重复非法。
另增加 existing receipt 被列为 input、receipt 与 input 为 hard-link 的反例；两者均须拒绝。

另覆盖 R4 的变化传播、snapshot request 绑定 G1 manifest/narrow config、validation key 绑定 provider receipt、h=5/h=10 reconciliation key 不同，以及
非法 hash、空/空白/大小写 unavailable 版本、`horizon=true/0` 全部 fail-closed。增加并发 no-clobber 测试：
在最终创建前模拟另一个发布者写入相同/冲突 receipt；相同且有效复用，冲突不覆盖。增加相同 receipt 字节
但 artifact 已变更的反例，必须拒绝复用。
变化传播必须明确断言：provider-validation 配置变化时 experiment/work 相等，provider-validation 与
reconciliation 不等；不能继续断言“仅 provider-validation 改变”。碰撞反例通过 public key 函数完成。

## 7. 交付与初验

报告命名 `docs/M3_E3严格Receipt增量返工交付报告.md`，列 R1–R4、针对性测试、全量
pytest/Ruff/mypy、未实现项。独立初验不修改代码，另造至少五个 JSON/path 反例并核对旧 identity key 未
发生无关迁移、R4 的预期迁移已经发生。实现 Agent 自测至少执行：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_run_state.py tests/unit/test_m3_contracts.py tests/unit/test_m3_snapshot.py -q
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

不得联网、不得更新 G8/G9、路线图 Gate 或宣称 E3/M3 完成。
