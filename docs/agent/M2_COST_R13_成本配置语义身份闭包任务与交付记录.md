# M2-COST-R13 成本配置语义身份闭包任务与交付记录

## 1. 状态与职责

- 状态：实现与普通开发检查完成，待精确安全提交和统筹合流。
- owner：策略开发 session。
- exact base：`3fe3d69967007c5778728733f665a8054918335e`。
- branch：`codex/m2-cost-r13-semantic-provenance`。
- worktree：`artifacts/dev_worktrees/m2-cost-r13-semantic-provenance`。
- 目标：只关闭首个 PIT runner 的 `M2-EVAL-STOP-001/D` 成本来源身份；不宣称其它 M2 runner、C 对称
  coverage、分组单调性、财务版本链或整个评估 STOP 已关闭。

## 2. 精确白名单

1. `src/quant/research/run_classic_factors.py`；
2. `src/quant/research/run_pit_quality_factors.py`；
3. `tests/unit/test_run_classic_factors.py`；
4. `tests/unit/test_run_pit_quality_factors.py`；
5. `configs/research/m2_pit_quality_factors.toml`；
6. 本记录；
7. `docs/roadmaps/M2_策略与因子库并行建设路线图.md` 的 R12/R13、D 边界和证据 exact hunk。

禁止修改 daily/composite/model、R12 `holding_outcomes` 代码块、`lightweight_run`、Schema、publisher、
repository、façade、`pyproject.toml`，禁止新增模块、依赖、runner 或真实研究 run。

## 3. 冻结合同

### 3.1 单 payload 与启动顺序

- PIT 主配置只 `read_bytes()` 一次；同一 payload 同时用于 `tomllib.loads` 和 raw SHA-256。
- 成本配置只读取一次；同一 payload 用 `tomllib.loads(..., parse_float=Decimal)` 解析、严格验证、构造
  `AShareCostPeriod` 和 canonical semantic SHA-256。
- PIT 在任何 bar/daily-basic/financial verifier、repository 读取或 artifact 创建之前，对配置中预注册摘要与
  实际语义摘要做 exact 比对；通过后复用内存中的 periods，不重读磁盘。
- 保留 `_cost_periods(project_root, portfolio)` 的 classic/daily 兼容签名。

### 3.2 canonical `[costs]` 语义

canonical JSON 的 schema 为 `m2-a-share-cost-semantic-v1`，绑定：

- `schedule_version`；
- `sources.stamp_tax` 与 `sources.transfer_fee`；
- 固定压力分量 `commission_rate / commission_min / slippage`；
- 原顺序的全部 period：ISO 生效边界及五个 Decimal 费用字符串。

Decimal 从 TOML 直接进入 `Decimal`，不经过二进制 float；去尾零，正负零统一为 `"0"`。`[costs]`、period
字段集合必须 exact；非末段不得开放，period 必须按原顺序无重叠、无空档。未知/缺失字段、bool、非有限、
负数、乱序、重叠或空档稳定拒绝。tracking/model/acceptance、注释、EOL、映射键顺序和等价 TOML 小数拼写
不进入摘要；成本版本、来源或 period 经济语义改变必须改变摘要。固定压力分量若漂移则因运行时经济语义不匹配
而直接拒绝，不能只重签摘要继续运行。

当前冻结成本配置的 canonical semantic SHA-256 为：
`b2041d8495aa408de0bd264d6c03eb7e4d174e03f120289bc8471cbb5ea0a959`。

### 3.3 run identity

`[portfolio].cost_schedule_semantic_sha256` 必须是 exact 64 位小写十六进制。PIT run inputs 的 canonical
第一项为：

`ResearchInputDigestV1(name="a-share-cost-schedule", rows=3, min_date=None, max_date=None,
content_sha256=<semantic sha>)`。

其后三项继续依次为 `tushare-daily-basic / tushare-financials / tushare-stock-bars`。历史 immutable runs 不
回写、不重签，也不会追溯获得新的来源有效性。

## 4. 反例与普通开发检查

必须覆盖：

1. 非成本 section、注释、EOL、等价小数/科学计数法不改变摘要；
2. 成本 version/source/period 变化改变摘要，固定压力分量漂移稳定拒绝；
3. root/period 未知或缺失 key、乱序、重叠、空档、非末段开放、bool/非有限稳定拒绝；
4. expected 摘要缺失、短值、大写或不匹配在所有 data verifier 与 artifact 创建前拒绝；
5. main config 与 cost payload 各只读一次，读取后的磁盘漂移不改变本次 parse/hash/periods；
6. run input 的名称、顺序、行数和摘要 exact，fresh lightweight verifier 通过；
7. classic/daily `_cost_periods` caller 保持兼容。

定向顺序：focused classic+PIT tests → daily-value 邻接 → Ruff → mypy → classic/daily/PIT cold import → TOML
与 cached diff-check。使用唯一 BelowNormal/`0xF00` 进程、数值线程不超过 2；不运行真实数据、snapshot、完整
pytest 或 WSL Gate。

## 5. 交付证据

当前 revision 的普通开发检查：

- focused：`tests/unit/test_run_classic_factors.py + tests/unit/test_run_pit_quality_factors.py`，`31 passed`；
- 邻接：`tests/unit/test_run_daily_value_factors.py`，`21 passed`；
- Ruff：两生产文件和两改动测试，PASS；
- mypy：两生产文件，PASS；
- fresh cold/TOML：classic、daily、PIT 均从本 worktree 导入，配置摘要与机械重算结果 exact 相等，PASS；
- `git diff --check`：PASS（只有工作树既有 CRLF 转换提示）。

首轮 focused 的无效终态为 `20 passed / 4 failed / 7 setup errors`：测试 fixture 把已有 CRLF 再转换为
CRLF，且承载器未预建 `.tmp` 父目录。归一化 fixture 并预建父目录后，同集合 `31 passed`。首轮 mypy 仅
发现 `_cost_decimal` 的 `object → Decimal` 类型收窄不被 stub 识别；改为 exact `int/Decimal` 分支后，
focused 与 mypy 均绿，运行语义未改变。

安全提交 SHA 以本记录所在 source 提交和提交后的统筹回报为准；不在提交前伪造自引用 SHA。检查期间没有
读取 raw/snapshot，也没有发布 artifact 或启动真实研究 run。最终 `0xF00` Python 为 0。

本地工具的自动审批额度曾在精确递归清理时耗尽，因此实现 session 没有换壳绕过删除限制；统筹随后在
合流窗口校验绝对路径边界，并精确删除 `.tmp/r13-focused`、`.tmp/r13-focused-final` 及空 `.tmp` 父目录。
这些 basetemp 未被暂存或进入 Git，也不改变代码证据。

## 6. 未关闭风险

- 主 PIT config 的 report type 仍为 `UNFROZEN`，本包不授权真实 PIT；
- C 对称 redundancy coverage、20 日分组单调门禁、财务 revision/comp-type 链、audit-v4 与 R3 仍开放；
- classic/daily/composite/model 的全局成本 provenance 没有由本包关闭；`M2-DEBT-002` 继续保留；
- 历史 immutable runs 不回写，不能因本修复追溯获得新身份或准入有效性。
