# M3 Development Example Release 开发并行轨任务单

日期：2026-07-31
状态：**开发契约已实现并完成定向验证；不代表正式 G1、G2、G8、G9 或 M3 Gate 通过**
适用范围：G1 长时真实 I/O 运行期间，解锁 G2–G9 的无网络工程开发与契约验证
验证证据：[`M3_DevelopmentExampleRelease主Agent验证报告.md`](M3_DevelopmentExampleRelease主Agent验证报告.md)、
[`M3_DevelopmentExampleProvider主Agent验证报告.md`](M3_DevelopmentExampleProvider主Agent验证报告.md)

## 1. 冻结身份与目录边界

开发发布物的信任域固定为 `development_example`，`formal_gate_eligible=false`，身份使用
`development-example-<sha256>`。它使用独立名义类型
`VerifiedDevelopmentExampleG1Release`，不会创建、返回或模拟 `VerifiedG1Release`。

调用方必须显式提供一个空的开发输出目录。建议根目录为
`artifacts/research/m3-development-example/`；构建器不会发现或写入正式 G1 发布根、正式 candidate、正式
journal、正式 request mapping 或 `data/legacy/`。开发快照的 receipt stage 固定为
`development-snapshot`，路径固定在开发 StageRunner 根的
`receipts/development-snapshot/`；正式 `snapshot` stage 不接受开发节点。

以下混用永久禁止：

- 把开发对象包装、转换或重命名为 `VerifiedG1Release`；
- 把开发 manifest、receipt 或 snapshot 作为正式 Gate、性能结论或真实数据证据；
- 把开发输出写入正式 G1 根、journal、candidate 映射或正式发布目录；
- 为方便测试而放宽正式 snapshot 入口的 `VerifiedG1Release` 精确类型检查；
- 在开发构建或验证中发出 Tushare、BaoStock 或其他网络请求。

## 2. 外部契约与最小 fixture

实现复用正式数据 Schema、Parquet 文件名、snapshot manifest/request、内容哈希和通用
`StageReceipt/ArtifactDigest` 机制，不复制第二套 snapshot 格式。开发 G1 顶层使用独立 manifest/request/
receipt 类型和 schema marker，避免名义上冒充正式 G1 质量报告。

固定 fixture 包含 3 个 A 股证券、2026-01-05 至 2026-01-07 三个连续交易日，并覆盖：

- `600000.SH` 的现金分红、复权因子跳变、公司行动 ledger/evidence/reconciliation；
- `000001.SZ` 在中间交易日的全天停牌及 bar/eligible 闭包；
- `000002.SZ` 在窗口末日退市的证券生命周期边界。

包内包含正式 snapshot 消费所需的 17 个合同文件，以及 `fixture-spec.json`、`manifest.json`、
`request.json`、`receipt.json`。验证器检查 canonical JSON、目录闭包、普通文件/单链接、size/hash、主键范围、
跨表集合、停牌闭包、公司行动与因子比例、生命周期和抽样对账。

## 3. 公开入口

包级公开接口位于 `quant.research.m3`：

- `build_development_example_g1_release` / `verify_development_example_g1_release`；
- `derive_development_example_m3_config` / `compute_development_snapshot_request_key`；
- `build_development_example_snapshot_artifact` 及对应 request/build/final verifier；
- `make_development_snapshot_run_plan` / `StageRunner.run_development_snapshot`。

开发 plan 必须从已重新验证的 release 派生 manifest、bar、universe membership、trade calendar 四个
`ArtifactDigest`，调用方不得自行声明这四个摘要。发布、重复执行、已有 final 恢复、request mapping 和 receipt
校验复用 G8 runner；开发 receipt stage 保持独立。

## 4. 可解锁范围与仍阻塞范围

开发发布物可用于推进：G2 snapshot/staging 接口、G3 标签接口、G4–G7 的训练/评估纯工程边界、G8
编排/恢复/重复执行、G9 收据/验收结构，以及 Windows/WSL 的确定性与兼容性反馈。

以下事项仍等待正式 G1：正式 `VerifiedG1Release` 输入下的 G2A 主验、真实全量覆盖和性能结论、真实 provider/
训练/评估结果、正式不可变发布验收、Linux Gate 与任何正式 Gate 关闭。Windows 绿测只代表 Windows 开发反馈；
WSL 定向绿测也只代表本开发契约，不自动关闭正式 Linux Gate。

### 4.1 已解锁的 G2B 开发合同

开发 Provider 复用正式 `ProviderManifestV1`、固定 `dump_all` argv、七字段 `<f4` bin、tree digest 和
`StageReceipt`，但使用独立 `compute_development_provider_key`、
`VerifiedDevelopmentExampleProviderArtifact`、`development-provider` stage 与显式
`development-example` 根目录。正式和开发 materialize/inspect/verify 均为不同公开入口，精确名义类型在
任何 subprocess 或写入前拒绝混用。pinned `dump_bin.py` 由 `.gitattributes` 固定为 binary，防止 Windows
checkout 把 LF 改为 CRLF 后破坏冻结的 21847 bytes/SHA-256。

开发 G2B 可验证真实 pinned Qlib dump、calendar/instrument/七字段静态回读、receipt 闭包与跨平台接口。
fixture 已扩为 21 个连续开市日：`000001.SZ` 保留一个全日停牌并恰有 20 个 emitted rows，另两证券各 21
行；公司行动/复权和退市生命周期边界继续保留。开发 G2C 因此直接复用正式 `3×20×7` sampling policy，
不降低抽样数量。开发 validation 使用独立 domain-separated key、`development-provider-validation` stage、
显式 development/example 输出根和开发专用 nominal verified 类型；不得将其描述为正式 G2C 或任何 Gate。

## 5. 最小验收

定向验收必须覆盖：双构建 byte-level 确定性、正式/开发类型与 identity-domain 互斥、hash/tree 漂移拒绝、
停牌/公司行动/生命周期反例、开发 snapshot 完整闭包、runner 首次发布/幂等 resume/已有 final 恢复，以及正式
runner 拒绝 development node。Windows 和 WSL base 各运行相关 Ruff、mypy、pytest；WSL1 不支持正式
no-replace 目录提交时，状态机测试只可注入与项目既有测试一致的 test-only primitive，不能据此宣称平台发布
Gate 通过。
