# M3 G2–G3 Provider 与标签对账实现初验任务单

日期：2026-07-13  
状态：**历史合并任务；不再按 P0–P4 一次性交付**  
现行执行入口：[`M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md`](2026-07至09_多Agent治理期/framework/agent/M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md)
设计 SSOT：[`M3实施与Agent交接.md`](2026-07至09_多Agent治理期/framework/M3实施与Agent交接.md) 4.2、4.3、4.5、4.9
审查记录：[`M3_G2-G3设计审查与修订记录.md`](2026-07至09_多Agent治理期/framework/agent/M3_G2-G3设计审查与修订记录.md)

## 1. 目标、边界与流程

> 本文保存首轮业务口径和审查历史。现行实现已拆为 G2A/G2B/G2C/G3A/G3B；接口、verified bundle、
> worker protocol、报告名和执行顺序若与本文不同，以现行分包任务书和 SSOT 为准。

本任务机械实现：权威 snapshot session calendar、固定 Qlib dump 工具注入、provider materialization、全量
provider 结构验真、fresh-process Qlib public API 回读，以及每 horizon 的全量标签三层对账。不修改标签
公式、股票池、Qlib 版本、fold/model/backtest 或 acceptance 规则。

流程固定为：主 Agent 任务书 → 实现 Agent 自测并提交报告 → 未参与实现的初验 Agent 只读验收 → 主 Agent
最终验收。任何阶段失败均写“现象—根因—应遵循规则—最小复现—新增测试—通过条件”，不得只修当前
fixture。默认测试不联网；真实 Qlib 测试显式标记。不读取 `_old/`、Tushare token 或真实券商，不安装或
降级环境，不更新路线图 Gate。

## 2. 前置关闭条件

开始 P0 前必须确认：

1. C0 是唯一 M3 TOML reader，并能提供 `snapshot_config_sha256`、`provider_config_sha256`、
   `provider_validation_config_sha256`、`label_reconciliation_config_sha256` 和只读配置；
2. E3 已实现 provider/runtime、provider-validation、label-reconciliation keys 及严格 receipt；
   所有 key/digest 为裸 64 位小写 hex，不带 `sha256:` 前缀；
3. G1 release 发布通过 `TradeCalendarSchema` 的 SH calendar、标准 bars/membership/benchmark，且 source、
   universe、日期域和 digest 已验真；
4. 固定 `data/external/qlib/v0.9.7/dump_bin.py` 与配置的 URL、21,847 bytes、SHA-256 完全匹配；
5. 当前 WSL base 若不兼容真实 Qlib 0.9.7，只能完成 fake 契约测试，G2/G3 真实 Gate 保持未通过。

## 3. P0：Snapshot 权威 session calendar 与窄身份

修改：

- `src/quant/research/m3/snapshot.py`
- `src/quant/research/m3/contracts.py`
- `src/quant/domain/schemas.py`（唯一 `SnapshotSessionCalendarSchema`）
- `tests/unit/test_m3_snapshot.py`
- `tests/unit/test_schemas.py`

实现 SSOT 的 `build_snapshot_session_calendar`，并升级 `build_snapshot_manifest`：

- calendar 只从已验真的 G1 `TradeCalendarSchema` 过滤 `market="SH"`、`is_open=true` 和显式
  `[history_start,history_end]`；日期唯一、严格递增、非空；
- `history_start/history_end` 来自 snapshot request 的 warmup 至 label tail 域，不能取 staging min/max；
- 发布严格单列 `date: pl.Date` 的 `session_calendar.parquet`，manifest 绑定其 hash/count/start/end；不得保存
  connect/half-day 等与 SH session 无关的列；
- 全部 staging 日期并集必须与权威 calendar 完全一致；任何权威 session 完全无 staging 行都失败；
- manifest 只接收并校验 C0 的 `snapshot_config_sha256`，删除 `config_path` 与整份 TOML hash；
- `write_staging_by_symbol` 只写 StageRunner 分配的空 temp，目标非空立即失败，不覆盖既有文件。

反例：只改 tracking URI 时 snapshot ID 不变；SH 开市日所有证券都缺行时失败，而不是让 dump tool 删除该日。

## 4. P1：固定工具 spec、运行时指纹与精确 materialization

新增/修改：

- `src/quant/research/m3/provider.py`
- `src/quant/research/m3/fetch_qlib_tool.py`
- `src/quant/research/m3/contracts.py`
- `tests/unit/test_m3_provider_materialization.py`

`QlibDumpToolSpec` 唯一定义在 `contracts.py`；实现
`provider.build_qlib_dump_tool_spec(LoadedM3Config)`，把扁平 `dump_script_*` 字段映射到 spec 并固定
`command="dump_all"`。实现 `ProviderRuntimeFingerprint/ProviderBuildSpec/ProviderBuildResult`。下载器不得
解析 TOML，只接收该 spec；已有工具先验 hash，相同复用、不同拒绝。

materializer 只接受已验真的 snapshot/staging 和空 stage temp，使用 `shell=False`、当前
`python_executable` 和以下唯一 argv；禁止额外参数或隐式默认：

```text
<python> <verified dump_bin.py> dump_all
--data_path <staging> --qlib_dir <stage-temp>/provider --freq day
--file_suffix .parquet --date_field_name date --symbol_field_name symbol
--include_fields open,high,low,close,vwap,volume,factor --max_workers 1
```

禁止 `dump_fix/dump_update/limit_nums/backup_dir`。运行前验证 Python、NumPy、pandas、PyArrow、Qlib、Fire、
tqdm、Loguru 的实际版本及精确 Qlib `0.9.7`；其规范 hash 进入 provider key。逻辑 argv 使用占位符，manifest
不得记录绝对路径、PID、wall-clock、非确定性 stdout 或凭据。subprocess 非零、超时、缺依赖或任一输出
验真失败均不发布 final provider。

稳定 logical argv 固定使用 `<PYTHON>/<DUMP_TOOL>/<SNAPSHOT_STAGING>/<PROVIDER_TEMP>/provider` 占位符；
真实绝对 argv 不落盘。运行前重算 runtime fingerprint、要求 tool/runtime Qlib version 相等，并通过 E3
唯一函数重算 provider key。provider StageNode 必须把 `EXTERNAL_QLIB:dump_bin.py`、snapshot manifest/
calendar/全部 staging 与 snapshot receipt 列为输入；handler 不隐式联网。

## 5. P2：Provider manifest 与全量结构验真

实现严格 `ProviderManifestV1` reader/writer、`inspect_provider_structure` 和稳定
`provider_manifest.json`。最终布局只能是 `providers/<key>/provider/**` 加同级 manifest；manifest files
只列 `provider/` 子树，不列自身/receipt/validation。不 import Qlib，至少全量验证：

1. `calendars/day.txt` 与 snapshot `session_calendar.parquet` 完全一致；
2. `instruments/all.txt` 的证券集合、唯一 codec、每证券 min/max 与 staging 一致；
3. 每证券恰有 `open,high,low,close,vwap,volume,factor` 七个 `.day.bin`，无额外字段/证券；
4. bin 为 little-endian float32，首值是整数 calendar offset，文件字节数等于 `4*(1+span)`；
5. emitted staging 值转 `<f4` 后逐位置一致，区间内缺口为 NaN；
6. output tree 无 symlink、未知普通文件、空文件、路径逃逸或大小/hash 冲突。

provider manifest 绑定 schema version、provider/snapshot/config/tool/code/runtime、固定 frequency/fields/dtype、
calendar/instrument 摘要、逻辑 argv和全部普通文件 digest。subprocess return code 0 不能替代这一步。

## 6. P3：确定性 3×20×7 fresh-process Qlib 回读

实现严格 `ProviderValidationSummaryV1`、`ProviderProbePlan/ProviderValidationResult/
plan_provider_probe/validate_provider` 和 Qlib worker。validation key 由 G8 调用 E3 identity 函数预先计算，
`plan_provider_probe` 显式接收并校验该 key，不自行读 receipt 或复制 hash：

- 抽样算法固定为 `provider_market_stratified_hash_first_last_v1`；候选证券至少 20 个 emitted rows；
- 用规范 JSON 数组 `["provider-symbol-v1",snapshot_id,provider_key,symbol]` 的 SHA-256 各选一个 SH/SZ，
  再取剩余最低 hash 的第三只；
- 每证券包含首尾日期，并按 `["provider-date-v1",provider_key,symbol,date]` 的规范数组 SHA-256 选 18 个
  内部日期；另选最多 5 个区间 gap；禁止直接字符串拼接；
- emitted 恰为 60 keys/420 field comparisons；gap 另为 0–15 keys/0–105 comparisons。通过真实
  `qlib.init`/public API 回读；expected 是 staging 转 `<f4` 的值，有限值精确相等，gap 必须 NaN；Qlib
  API 的 calendar/instruments 也全量核对；
- parent 不 import Qlib；每次 validation 启动 fresh Python，只初始化一个显式 provider URI，核对实际版本，
  只通过规范 JSON/Parquet 交换；按命名 MultiIndex level 解析，不假设 level 顺序；
- 证据发布到 `provider-validation/key=<key>/`，分开记录 emitted/gap keys 与 comparisons、七字段
  expected/actual/status、candidate/hash、worker protocol/version、missing/extra/duplicate counts、row-key
  hash 和全量 PASS summary。PID 只由测试 spy 运行时观察，不写持久 JSON。

证券不足、SH/SZ 任一缺失、样本不足、Qlib 不可用、版本不符或任一差异均失败，不得缩小样本或标 SKIP。

## 7. P4：G3 每 horizon 全量标签三层对账

先实现严格 `LabelArtifactManifest/build_label_artifact_manifest/verify_label_artifact`，与 labels/diagnostics
同一 receipt 发布并验证 candidate=success+diagnostic、所有输入输出 digest 和 key hash。再实现严格
`LabelReconciliationSummaryV1/LabelReconciliationResult/reconcile_labels_with_qlib`。每个 horizon 在独立
fresh worker 中对全部成功 label rows 执行，不抽样、不读取 Qlib `LABEL0`：

1. Qlib `Ref($close,-h)/Ref($open,-1)-1` 与同 provider start `$open`/end `$close` 直接手算，误差不超过
   `validation.labels.qlib_expression_atol`；
2. 依据权威 SH calendar 独立推导 start/end，从原始 `H00300.CSI` open/close 重算 benchmark，不调用 label
   builder、不复制 label benchmark，误差不超过 `benchmark_return_atol`；
3. provider float32 raw 与权威 Float64 label raw、provider raw 减独立 benchmark 与 label relative，误差
   不超过 `label_return_atol`。

入口只接收已验真的 provider/label artifacts、snapshot session calendar 与 G1 benchmark digest；所有 hash/
receipt 在启动 Qlib 前复算。主 join key 是
`(as_of,symbol,benchmark,horizon_sessions,label_version)`，start/end 独立推导后逐值比较。expected/actual 键
必须完全相同；重复、missing、extra、日期错位、非 finite 或超容差都失败。details 保存四个
expected/actual/diff/status；summary 绑定 experiment、provider-validation receipt、label manifest、horizon、
benchmark/calendar/dependency/code/label-reconciliation identities，分别记录 expression/direct、benchmark、
raw-label、relative-label 的 max/p99 error 和容差。
容差变化只形成新 reconciliation key/receipt，不重建 snapshot/provider/experiment。

## 8. 并发、发布与恢复

materializer/worker 只能写唯一 stage temp，StageRunner 是 final 目录和 receipt 的唯一 publisher。同一
`(scope,key)` 在 WSL 使用单 writer/`flock`；锁内重新验 receipt。无 receipt 的 temp 可清理重算；final
存在而 receipt 缺失时只能从全新 temp 重算并逐字节一致后认领；冲突 fail-closed。validation 只能读已发布
且 receipt 验真的 provider。不得由 provider helper 自己扫描 artifact tree 或覆盖 final。

## 9. 测试边界与必测反例

fake 单测必须证明：精确 argv/`shell=False`、tool/runtime identity、窄 snapshot hash、权威 calendar 缺日、
tree/bin 结构、确定性抽样、fresh worker（PID 仅测试 spy 观察）/URI、MultiIndex level、float32、三层对账、容差、锁/orphan/
receipt 失败和 parent import isolation。

至少增加这些实现者正常路径之外的反例：

1. 某权威 session 所有 staging 证券无行；
2. dump 返回 0 但少一个 `$factor` bin，或多一个未知文件；
3. `qlib.init(A)` 后验证 B，fake cache 故意仍指 A；必须因 fresh worker 避免污染；
4. label benchmark 错用 `t+2`，若 reconciliation 复制 label 值会假通过；独立 benchmark 必须抓出；
5. Float64 staging 与 Float32 provider 有正常量化差异；G2 应按 `<f4` 精确通过，G3 按分层容差判断；
6. 两个相同 provider key 并发启动，最终只有一个合法 provider/receipt；
7. 只改 LightGBM、NumPy、provider 抽样、label tolerance，分别验证预期身份传播；
8. 用 A 的 DataFrame 搭配 B 的 manifest/receipt/hash，在启动 worker 前失败；
9. provider/validation/reconciliation JSON 含未知字段、duplicate key、NaN 或字符串数字时失败。

fake 不能宣称真实 Qlib Gate。真实验收必须在兼容 WSL base 中用固定脚本 materialize，运行全量结构检查、
fresh Qlib 3×20×7 回读，并对 h=5/h=10 全量 reconciliation。真实依赖不兼容时报告 exit 4/G0 blocker。

## 10. 交付与独立初验

实现报告命名 `docs/M3_G2-G3Provider与标签对账交付报告.md`，逐 P0–P4 列文件/接口/测试/真实运行、全量
pytest/Ruff/mypy、未实现项。独立初验 Agent 不改代码，逐项映射并至少增加五个未公开反例，报告命名
`docs/M3_G2-G3Provider与标签对账初验报告.md`。初验通过只允许写“建议进入主 Agent 终验”，不得更新 Gate。
