```text
G1_EXECUTION_FACT_RESPONSE_INVALID
G1_EXECUTION_FACT_ENDPOINT_MISMATCH
G1_EXECUTION_FACT_EMPTY
G1_EXECUTION_FACT_COLUMNS_INVALID
G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH
G1_EXECUTION_FACT_VALUE_INVALID
G1_EXECUTION_FACT_DUPLICATE_KEY
G1_PRICE_LIMIT_UNPROVEN
G1_PRICE_LIMIT_SCHEMA_INVALID
G1_PRICE_LIMIT_COVERAGE_INVALID
G1_CORPORATE_ACTION_EVENT_INVALID
G1_CORPORATE_ACTION_VERSION_CONFLICT
G1_CORPORATE_ACTION_SCHEMA_INVALID
G1_CORPORATE_ACTION_RESULT_INVALID
G1_CORPORATE_ACTION_CALENDAR_INVALID
G1_CORPORATE_ACTION_FACTOR_INVALID
G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
G1_CORPORATE_ACTION_RECONCILIATION_INVALID
```

不为纯诊断增加更多 code；身份、Schema、日期和主业务错误不得降级为 warning。

## 12. 允许修改文件

- `src/quant/data/m3_execution_facts.py`（新增）；
- `src/quant/domain/schemas.py`；
- `src/quant/data/__init__.py`、`src/quant/domain/__init__.py`（只新增导出）；
- `src/quant/research/m3/config.py`（只收紧 factor rtol 最大值）；
- `tests/unit/test_m3_execution_facts.py`（新增）；
- `tests/unit/test_schemas.py`；
- `tests/unit/test_m3_config.py`；
- 本包交付/复验报告。

不得修改 B2A/B2B/P2 已验收生产代码、配置示例数值、G1 release publisher、路线图勾选或已有测试期望以迁就
错误实现。发现需改冻结接口时停止并提交最小证据，由主 Agent 先更新 SSOT。

## 13. 实现 Agent 必测矩阵

至少覆盖：

1. `stk_limit/dividend` 单 response 与 reconciliation 的全部 `daily` verified objects 构造后
   spec/receipt/hash/frame 漂移，均在读值前失败；
2. price limit missing/extra/reorder columns、跨 symbol/date scope、空、duplicate、bool/不可损 string/List/Struct、
   nonfinite/负数、正 pre-close 时 null/单侧 limit、上下限不包围昨收；null/zero pre-close sentinel 只生成空缺，
   不生成 clean false/zero 行；
3. mapper 所有 emitted 行永远为 true；全 sentinel response 返回 typed empty；Schema 可表达 false 不等于 G1
   mapper 可发布 false；
4. price coverage：next session 起算、调出后继续到 history end、delist 截断、闭市日排除；FULL_DAY 缺 limit
   合法且不进 required keys，PARTIAL/无 suspension 缺一行以及 false/重复均失败，首次 eligible 前 extra 可保留；
5. dividend 全历史中范围外缺 pay/ann 不阻塞；范围内实施 ex_date 无法解析必须失败；非实施不进入 ledger；
6. 纯现金、纯送转、现金+送转、全零、负数/nonfinite、record/ex/pay/list 顺序、零分量伪日期；
7. 合法空 dividend/窗口内零事件结果；ann/imp null 的 total order、同 rank 相同重复聚合 row_count、
   candidate_count 只计不同 candidate、同 rank 数值或 pay/list 冲突、旧版本证据；
8. event/group/candidate/event-set hash 按冻结规范数组且行序稳定；`event_ids_json` 是排序去重的规范 JSON 且
   count/hash 均从它重算；经济数值变化改变 event ID，pay/list 变化不改 event ID但改变 candidate ID 和内容 digest；
9. ledger 与 selection 的 rank/count/selected/数值闭包；构造后单独 frame/hash drift；
10. no-event factor 稳定、无事件 jump、纯现金、纯送转、同日多 event 的排序 `math.fsum`、分母非正、缺前收、
    event 无 factor、第一 factor row event、market-reference 超 rtol、rtol=0/0.01/越界/bool；event-date daily
    FULL_DAY 缺行且 declared 公式闭合输出 NO_MARKET_REFERENCE，FULL_DAY 超差或 PARTIAL/无 suspension 缺行失败；
11. factor gap 无事件可稳定；gap 中 event 不得挪到下一 factor；previous close 可早于 previous factor；declared
    公式内/外 rtol 分别产生两个 MATCHED status，不能靠放宽 rtol 合并；
12. daily responses 少/多/重复/跨 symbol/scope/identity drift、raw duplicate、close 与 bars 不一致、evidence
    lineage 指向错误 request/stable digest 均失败；每个 bar factor 与独立 factor 表不一致失败；证据行数为
    每 symbol factor rows-1；
13. 三个 clean digest 对行序稳定、对值/dtype/重复敏感，并复用 P2 工具；
14. 底层错误与恶意 raw 字符串携带绝对路径/token marker 时，message/repr/cause/traceback 均脱敏；
15. 生产模块无网络、文件写入、config path、research/Qlib/provider 反向 import。

## 14. 独立初验 Agent 的未公开反例

至少从下列十类选择六类，且不得只改实现者 fixture 的一个数：

- Verified frame 和 receipt/content hash 同时伪造为另一自洽形状；
- price limits 只覆盖 next-buy 日但在调出后一个非 FULL_DAY session 缺一日，证明持仓延续域有效；
- `has_price_limit=false` 且上下限 null 能通过通用 Schema，但必须被 G1 coverage 拒绝；
- 相同 null/zero raw sentinel 分别有 FULL_DAY、PARTIAL、无 suspension：只有 FULL_DAY 可从 required keys 排除；
- 范围外 1990 年代实施行缺 pay 与范围内同形缺 pay 的对照；
- null imp/ann 与合法日期混排、同 rank identical duplicate、同 rank 仅 pay date 冲突的组合；
- 两个不同 economic group 同 ex-date，必须分别选版、对账时才聚合；
- action 落在 factor gap 内而下一 factor jump 数值恰好可解释，仍必须失败；
- previous factor date 与 previous close date 不同的停牌形态；
- dividend 通式超 `0.001` 但 raw pre-close 能在 `0.001` 内闭合，必须显式输出
  `MATCHED_EVENT_MARKET_REFERENCE`；把 raw pre-close 换成 caller 自算值必须失败；
- FULL_DAY event 没有 daily row、declared 公式闭合时必须输出
  `MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE`；同步改成超差不得借 `stk_limit.pre_close=0` 变绿；
- 把同一缺 daily 样本的 suspension 改为 PARTIAL、删除或跨 source，必须从 NO_MARKET_REFERENCE 变为失败；
- event_ids_json/event-set hash/event_count/cash sum 中只改一项，verify 必须失败；只改 event-set hash 并同步整表
  digest 也必须失败；同步替换 json/count/hash/digest 的全套自洽来源替换留给 B4 从原输入重执行关闭；
- rtol 被改为 1.0 或 NaN，不能把 unexplained jump 变绿；
- result 内部只改 frame/hash 的 drift；并在报告明确“全套自洽替换须由 B4 从原输入重算关闭”的信任边界；
- Polars/Pandera 异常携带绝对路径和 token marker 的全 traceback 扫描。

P0/P1 必须返工；不影响主业务的 P2 可登记后置。但价格覆盖域、公司行动范围、版本冲突、factor 解释、
Schema-first、identity closure 和凭据泄露不得降为 P2。

## 15. 验证命令与交付门槛

仅在 WSL Miniforge base：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_execution_facts.py tests/unit/test_schemas.py \
  tests/unit/test_m3_config.py tests/unit/test_m3_backfill_requests.py \
  tests/unit/test_m3_g1_mappers.py tests/unit/test_index_membership.py \
  tests/unit/test_m3_identity.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

报告列出文件、冻结签名、测试数量、全量/Ruff/mypy、C0 回归、import 隔离、是否联网、脱敏证明、未实现项。
外部闭环通过只表示可交主 Agent 终验，不关闭 B2/G1/M3。下一包按
[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)
先执行 P4A；它将消费本包结果并重新验证完整 plan/receipt、required price keys 和三张公司行动表。P4A
主验通过后才依次执行 P4B 跨源证据与 P4C 不可变 release。
