# M3 G1 R1C-B INDEX 身份合同返工任务单

日期：2026-07-17  
状态：**冻结，交外部实现 Agent**  
前置：真实 INDEX 127 个 request/receipt/raw 已完整落盘；独立复验不通过  
边界：本任务只修 membership 身份合同并零网络恢复 INDEX，不授权任何新网络请求或 HISTORY

## 1. 现象—根因—应遵循规则

### 1.1 无关 ETF 阻断

- 现象：全量 SH+SZ clean instrument 共 7135 行，其中 1598 行 ETF；127 个 INDEX request 虽完整，`status`
  仍报 `G1_WORKFLOW_IDENTITY_MISMATCH`。
- 根因：`_prepare_instruments` 对输入超集的每一行执行 STOCK/CNY 断言，而不是只对 observation 实际引用的
  symbol 执行成员资格合同。
- 规则：输入必须先整体通过 `InstrumentSchema` 和 symbol 唯一性；随后 membership 只消费 observation 所需
  symbol。无关合法 ETF/其他非目标 instrument 不影响结果或三表 digest；若 observation 引用的 symbol 缺失、
  非 STOCK、非 CNY、市场后缀错误或生命周期非法，仍 fail closed。

### 1.2 月中退市造成 299 日

- 现象：把输入临时过滤为 STOCK 后，信号窗 2544 个 session 中有 46 天为 299 只，涉及 `600005.SH`、
  `600837.SH`、`601989.SH` 在两次月度 observation 之间退市。
- 根因：原合同把“每个 observation 精确 300”错误扩展成“生命周期裁剪后的每个 signal session 也必须精确
  300”。月频 Tushare observation 无法证明月中替补证券；保留已退市证券又违反生命周期/PIT。
- 规则：
  1. 每个供应商 observation 仍必须精确 300 个唯一 A 股 STOCK，权重合同不变；299/301 observation 继续失败。
  2. membership 仍按 observation 下一 SH session 收盘后激活，并与真实 list/delist 生命周期相交。
  3. `eligible_keys` 对每个 signal open session 必须非空、唯一、确定排序，数量不得大于 300；允许因经验证的
     生命周期裁剪短暂低于 300。不得推断或补造未被月度 observation 证明的替补证券。
  4. 横截面是否足够由下游 readiness 的 `minimum_cross_section_symbols` 门禁负责；membership 不复制该阈值。

该修订取代旧任务书中“每个 signal session 必须恰好 300、生命周期裁剪为 299 必须失败”的条款。旧报告保留
为历史证据，不据此恢复错误合同。

## 2. 身份与复用裁定

- 不修改 `membership_method_version=tushare_monthly_observed_next_session_close_v1`：本次没有改变 observation 的
  可知时点或激活方法。
- 不修改配置、日期、端点、限频、重试或 request ID 生成。
- 生产代码变化由 G1 `source_tree_sha256/code_version` 记录；membership/eligible/derived digests 会自然变化。
- 现有 127 个 raw/receipt 只按冻结 request spec 验真，应零网络复用；禁止删除、搬移或重写真实 evidence。

## 3. 文件白名单

实现 Agent 只可修改：

- `src/quant/data/index_membership.py`
- `tests/unit/test_index_membership.py`
- `docs/agent/M3_G1_R1C-B_INDEX身份合同返工交付报告.md`

其他生产代码、测试、配置、token、真实 `data/**` 和历史报告全部只读。不得初始化 Git。

## 4. 必须新增的回归

1. 在合法 STOCK fixture 外加入无关、Schema 合法的 ETF；输出 observations/membership/eligible 和三个 digest
   必须与无 ETF 输入完全一致。
2. observation 实际引用的 instrument 若为 ETF/非 CNY/错误 market 或缺失，仍以稳定 instrument code 失败。
3. 某 observation 成员在下次 observation 前退市：退市后 symbol 不再出现在 eligible；相关 session 为 299
   且合法；其他 session 与生命周期均正确。
4. 299/301 **observation** 继续失败；不得误把本次修订放宽到供应商 observation 门禁。
5. eligible 空 session、超过 300、重复键、闭市日、窗口外键继续失败；公开异常保持稳定脱敏且无 cause/path。
6. verifier 使用同一修订合同重建，STOCK-only 与合法 instrument 超集均能闭合，伪造结果仍失败。

禁止只对三只真实退市代码做特判，禁止在 workflow 层预过滤后绕过 membership 公共合同，禁止静默填充替补证券。

## 5. 高效验证

先运行：

```bash
python -m pytest tests/unit/test_index_membership.py -q
python -m pytest \
  tests/unit/test_m3_g1_planning.py \
  tests/unit/test_m3_g1_workflow.py \
  tests/unit/test_m3_run_g1.py -q
python -m ruff check src/quant/data/index_membership.py tests/unit/test_index_membership.py
python -m mypy src/quant/data/index_membership.py
```

不跑全量 pytest。随后只运行零网络：

```bash
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

必须满足：

- `outcome=INCOMPLETE`，`completed_stages` 精确为 `[INDEX]`；
- INDEX request/receipt/raw 仍为 127，未发起网络请求；
- 可报告真实 `history_symbols=S` 和 `history_requests=4*S+131`；
- HISTORY/REFERENCE/PREPARE/PUBLISH 均未完成、无新增端点数据；
- 若现有 evidence 因身份合同不能安全复用，立即停止并报告，不得调用 `index` 重新联网。

## 6. 交付

报告必须记录修改、测试摘要、零网络 status 的稳定字段、真实 S/计划数、未启动 HISTORY 的证据及任何未决风险。
不得宣称 R1C-B、G1、M3 或 Gate 完成。完成后交由另一全新、代码/data 只读外部 Agent 复验。
