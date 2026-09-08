# M2-R15-PORTABLE-CONFIG-IDENTITY-R2 独立初验报告

## 1. 审查身份与边界

- reviewer agent：`01a0336f-1105-7dd2-9bbb-5f8cf9d040ea`
- implementation agent：`01a0335a-64b7-72f2-9834-dd4635102273`，本审查未复用
- old reviewer：`01a031db-1316-7ff0-aae2-25c65a8c3757`，本审查未复用
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r15-portable-config-identity-r2`
- HEAD：`0341a1add2737210cde6ddb75b6d630aa446feea`
- branch：`codex/m2-r15-portable-config-identity-r2`
- mode：`READ_ONLY_STATIC / STATIC_ONLY`
- 允许读取：本报告指定的 exact4；允许写入：本报告唯一文件。

本轮未创建 agent、top-level task 或 worktree，未使用 external Cursor；未读取或修改 mapping/status，且不将
writer/data/ledger/process 稳定性纳入本 review 证据。先前一次 host process probe 因环境 Access Denied 失败，
仅记录为承载性探针失败，不是产品 finding。未运行 Python、pytest、Ruff、mypy、cold import、real run、network 或真实
数据 I/O。文档中实现者历史自报的测试数字不作为本报告的 PASS 证据。

初始 Git scope inspection 显示仅下列 exact4 为已修改路径，报告文件此前不存在，未发现 staging：

1. `src/quant/research/run_classic_factors.py`
2. `tests/unit/test_run_classic_factors.py`
3. `docs/research/agent/M2_FROZEN_R15_冻结Clean_MAX纠偏重放任务与交付记录.md`
4. `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md`

静态读取前四项的 SHA-256 快照为：`59c6c22e60ec690df53671a599e99869ce76b8f20b7cd25df35ae31f38c01f5f`、
`a0239e765edcc934c304d3473fa98118f89f94a4fdd4f30a74a55395587b7869`、
`9846b4156df1ac7bfd85137831543973a44d69f95b249b2418b229717ee703d7`、
`c5a80a387715b654704d30a088706333db6b648f221f1985848878286d83422d`；审查期间未改写 exact4。

## 2. 严重度分类

- P0：无。
- P1：无。
- P2：无阻断性产品缺陷。实现者测试变体未单独列出相邻 bare CR 与 CRLF 的组合；该缺口作为下方独立
  静态反例记录，但当前代码的两阶段替换对该输入有确定结果，因此不据此否定本次静态结论。

## 3. 逐项证据映射

### 3.1 单次读取、同一 payload 的严格解析和身份绑定

- `src/quant/research/run_classic_factors.py:139-142` 只调用一次
  `config_path.read_bytes()`；同一局部 `config_payload` 经过 `_normalize_main_config_payload` 后供 TOML
  解析。
- `:1796-1807` 先拒绝非精确 `bytes`、leading raw BOM 和 NUL，再使用默认 strict 的
  `payload.decode("utf-8")`；`UnicodeDecodeError` 被转换为明确的 `ValueError`。
- `:150-152` 对 fifth/MAX 使用规范化文本重新编码后的 canonical payload；legacy 使用原始
  `config_payload`。两条路径都把结果写入后续 `LightweightResearchRunV1.config_sha256`（`:649`），没有删除
  字段规避检查。

### 3.2 BOM、NUL、非法 UTF-8 与 interior U+FEFF

- `payload.startswith(b"\\xef\\xbb\\xbf")` 只匹配 byte 0 的 raw EF BB BF；代码没有清理非首位 BOM。
- `b"\\x00" in payload` 对任意位置的 NUL fail closed；strict UTF-8 decode 拒绝非法序列。
- interior U+FEFF 会在 decode/re-encode 中保留为相同 UTF-8 字节，随后 fifth canonical SHA 不再等于
  `baa384bbdcc1406fa53b6b7c689087ac03eeebf99db852f37ba9d03e40ca2c6e`。
- `tests/unit/test_run_classic_factors.py:879-930` 将 leading BOM、NUL、invalid UTF-8 和 interior U+FEFF
  分别映射到预期错误；成本绑定、snapshot verifier、publisher 均由 mock 设为 unexpected，调用序列保持空，
  没有以删除 `config_sha256` 的方式“通过”。

### 3.3 EOL canonicalization 和 frozen fifth identity

- `:1807` 的顺序为 `CRLF -> LF`，再将剩余 bare CR -> LF；除 EOL 外不做 Unicode 或文本清理。
- `:90-92`、`:150-158` 固定 fifth guard 和 run identity 使用
  `baa384bbdcc1406fa53b6b7c689087ac03eeebf99db852f37ba9d03e40ca2c6e`。
- `tests/unit/test_run_classic_factors.py:854-873` 的 full LF、full CRLF、mixed locations、repeated bare CR
  变体均通过 `_run_fifth_main_to_publish` 进入受控 publish boundary，并直接断言 captured run 的
  `config_sha256`；没有把 run identity 字段移除。
- 同一测试文件 `:735-847` 对 legacy 只改变 EOL 的 LF/CRLF payload 分别断言各自 raw SHA，且两者不同；
  `run_classic_factors.py:150-152` 的分支与该 R2-F1 记录一致。

### 3.4 失败顺序和受控发布边界

- `:156-163` 在 fifth SHA guard 和 cost semantic identity 检查后才到达
  `verify_tushare_bulk_clean_snapshot`（`:164-165`）；publisher 只在后续 `:669-670` 调用。
- 因此 frozen identity mismatch、payload hygiene 错误都在 cost binding、snapshot/data reader 和 artifact
  publisher 之前结束；测试 `:448-478`、`:886-930` 对该边界使用 unexpected mocks 和 artifact path 断言。
- `:252-426` 的 fifth mocked runner 捕获完整 `run` 对象并送入 publish mock，验证的是实际
  `LightweightResearchRunV1.config_sha256`，不是只验证常量或绕开发布路径。

### 3.5 旧 STOP/HOLD、trial_delta 和经济 Gate

- 本次生产 diff 只涉及 fifth SHA 常量、主配置 payload 规范化/绑定和新增 helper；没有改动评估、成本倍数、
  单调性、coverage、redundancy、admission 或报告结论逻辑。
- `run_classic_factors.py:2031` 仍要求 `max_lottery.trial_delta == 0`；冻结记录第 9 节明确写明成本 identity、
  R15 STOP/HOLD、经济参数和 `trial_delta=0` 不变。
- 冻结记录第 9 节及路线图 `:362-368` 将 R2 状态写成 `STATIC_DONE`，明确不宣称 Python/Gate/真实 run
  通过，并保留 `STOPPED_VALIDATION_EVIDENCE_LOST` 与 `UNASSESSED/HOLD`；历史段落中的旧 raw SHA 是
  R2 前的交付记录，不是本次 canonical SHA 的替代定义。

## 4. 独立静态对抗反例

反例：在一个 otherwise-valid fifth payload 的某处构造相邻字节 `b"\\r\\r\\n"`，即一个 bare CR 紧邻一个
CRLF。按代码的明确两阶段规则，第一次替换把后一个 `CRLF` 变为 `LF`，中间结果为 `b"\\r\\n"`；第二次
替换把剩余 bare CR 变为 `LF`，最终 canonical bytes 为 `b"\\n\\n"`。预期结果是：该 EOL-only 变化仍绑定
canonical fifth SHA `baa384...ca2c6e`，并到达受控 publish boundary；若同时存在非 EOL 漂移，则应在该 boundary
之前因 frozen identity mismatch 停止。该组合不是实现者列出的四个 EOL 测试变体，故作为本审查新增的静态
counterexample；本轮不以未执行测试宣称运行结果。

追加反例：在 otherwise-valid fifth payload 的合法 TOML comment 行前放入 `b"\\r\\r\\n# interior
\\xef\\xbb\\xbf\\n"`。预期首个 raw BOM 检查不触发（EF BB BF 不在 byte 0），strict UTF-8 与 TOML comment
解析通过；EOL 规范化得到两次 LF，interior U+FEFF 原样保留并参与 canonical bytes，最终 fifth SHA 应为
identity mismatch，并在 cost/snapshot/artifact/publish 之前停止。该组合同时覆盖了“非首位 BOM 不被静默
删除”和“相邻 bare CR+CRLF”的交互，未被实现者现有单独变体使用。

## 5. 结论

结论：`REVIEW_PASS`，但仅限 `READ_ONLY_STATIC / STATIC_ONLY`。

静态证据逐项支持：单次 `read_bytes`、严格 UTF-8 与 payload hygiene、只规范 CRLF/bare CR、fifth canonical
SHA 固定为 `baa384...ca2c6e`、legacy raw SHA、受控 publish boundary、失败先于 cost/snapshot/artifact，
以及 STOP/HOLD、`trial_delta=0` 和经济 Gate 未被本包改写。该结论不等价于 Python、测试、Gate、真实数据或
真实研究运行通过。
