# M3 G2–G8 机械实现任务单

> 历史任务单：其中 E3 接口已被
> [`M3_E3严格Receipt增量返工任务单.md`](../agent/M3_E3严格Receipt增量返工任务单.md) 取代。后续 Agent 不得按本文
> 的旧 E3 摘要实现；其余内容也须先与最新 [`M3实施与Agent交接.md`](../M3实施与Agent交接.md) 对照。

日期：2026-07-13  
设计与语义 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md)  
前置返工：[`M3_D1-D8二次返工任务单.md`](../agent/M3_D1-D8二次返工任务单.md)

## 1. 使用范围

本任务单当前只保留 E0 与 E3 两个已经冻结的机械实现。原 E1/E2 已被 G4–G6 独立设计审查判定存在
test-label 选择偏差、feature projection、early-stopping 与 model recovery 契约缺口，**禁止按本文旧 E1/E2
内容实现**；新版唯一任务见
[`M3_G4-G6研究链实现与初验任务单.md`](M3_G4-G6研究链实现与初验任务单.md)。

Agent 不负责改变 Alpha158、标签、切分、
回测或产物架构；发现契约无法实现时应停止对应任务并报告，不自行换方案。

开始前完整阅读根目录 `AGENTS.md`、`karpathy-guidelines.md` 和上述 SSOT。不得读取 `_old/`，不得调用
真实 Tushare，不得安装/降级 Python 或 Qlib，不得启用自动交易。

F1–F6 二次返工尚未由主 Agent 验收前，不修改：

- `readiness.py`
- `snapshot.py`
- `evaluate.py`
- `tracking.py`
- 及其现有测试

本文任务按 E0 → E3 独立提交；G4–G6 另按 H0–H5 执行。不要提前实现 `run_m3.py`、真实 provider 回读
或 A 股模拟器。

## 2. E0：补齐 Alpha158 的 VWAP staging 与双向 symbol codec

前置条件：F1–F6 已由主 Agent 验收通过。之后只做 SSOT 2.3/4.2 新冻结的增量：

- 修改 `src/quant/research/m3/snapshot.py`
- 修改 `tests/unit/test_m3_snapshot.py`

`prepare_qlib_staging` 从 clean `amount/volume` 推导 raw VWAP，再乘同一 qlib factor；输出列严格为
`symbol,date,open,high,low,close,vwap,volume,factor`。要求 amount/volume 正且 finite，验证
`vwap/factor == amount/volume`。manifest adjustment 增加 VWAP 公式和单位，任何 VWAP 变化必须改变
snapshot ID。

`build_snapshot_manifest` 必须接收并 hash `g1_release_id/g1_release_manifest_sha256`；测试改变任一值，
snapshot ID 必须改变，绝不能只记录 `source=tushare`。

staging 的 universe 过滤只用于取得历史成分 symbol 并集，不按 effective interval 删除行情。必须
保留并集证券整个 history window 的连续 bars；PIT 样本资格属于新版 H1/H2 的 `eligible_keys`，唯一要求见
[`M3_G4-G6研究链实现与初验任务单.md`](M3_G4-G6研究链实现与初验任务单.md)。新增首次调入前
60 sessions 仍在 staging 的测试，同时证明非目标 universe symbol 被排除。

新增 `from_qlib_symbol`，与 `to_qlib_symbol` 互为逆函数，接受 `SH600000/sh600000/SZ000001`
并输出项目代码；拒绝 HK、未知前缀、非数字或长度错误。不得在别处复制转换规则。

至少覆盖手算 VWAP、输入顺序稳定、amount/volume 的 null/NaN/inf/0、公式关系、manifest hash、双向
round-trip 和非法 symbol。不要顺带实现 provider materialize/validate。

## 3. E1：已废止，不得按本节实现

本节以下历史内容仅用于解释旧任务边界，不是现行实现要求。现行接口、test inference 与 feature bundle
共享规则只见 [`M3_G4-G6研究链实现与初验任务单.md`](M3_G4-G6研究链实现与初验任务单.md)。

## 4. E2：已废止，不得按本节实现

本节以下历史内容被新版 H3 替代；不得使用旧 `fit_lightgbm(train_x, valid_x, ...)` 签名。

## 5. E3：运行身份与 stage receipt

新增：

- `src/quant/research/m3/run_state.py`
- `tests/unit/test_m3_run_state.py`

严格实现 SSOT 4.9 中 `ArtifactDigest`、`StageReceipt`、`compute_provider_key`、`compute_experiment_key`、`compute_work_key`、
`verify_stage_receipt`、`publish_stage_receipt`。接口使用独立 `receipt_path`、显式 `artifact_roots` 和每个
digest 的 `root_alias`，使 work receipt 能引用 snapshot/provider/experiment 输入；禁止实现已经废弃的
单 `artifact_root` 版本。本任务不实现 CLI。

要求全部为标准库纯函数：规范化 JSON、SHA-256、相对 POSIX 路径、稳定排序、临时文件和原子替换。
receipt 禁止时间戳、绝对路径和运行机器信息。相同输入重复发布字节完全相同；已有相同 receipt 复用，
不同 receipt 拒绝覆盖；receipt 自身不得列入 outputs。

至少覆盖：输入顺序不影响 identity/receipt，snapshot/provider receipt/config/code 任一变化改变
experiment key，snapshot/provider 配置、dump tool、Qlib 版本或 code 任一变化改变 provider key，
dependency fingerprint 变化改变 experiment/work 而不改变 snapshot/provider，fold/horizon 任一变化改变
work key；固定字符串 `unavailable` 不是合法 code/dependency fingerprint。另覆盖缺文件、
hash/大小不符、非法 JSON、未知 root alias、重复 `(alias,path)`、`..`、Unix/Windows 绝对路径、符号链接逃逸、receipt 半写入、
已有冲突 receipt、无 receipt 返回 `None`。

## 6. 明确排除

- 不实现 `materialize_qlib_provider` 或真实 3×20 Qlib 回读。
- 不修改 Alpha158 feature 集、独立标签公式、fold 或评估指标。
- 不实现 TopkDrop；M3 当前是无状态 Top-k。
- 不实现 A 股账户循环、公司行动、成本场景或 MLflow 编排。
- 不更新路线图勾选，不宣称关闭 G0–G9。

## 7. 每包交付证据

每个任务包单独报告：修改文件、函数签名符合性、针对性测试、全量 pytest、Ruff、mypy、核心 import
隔离、未实现项和原因。主 Agent 会追加未出现在测试中的反例独立验收；仅原测试通过不代表验收通过。
