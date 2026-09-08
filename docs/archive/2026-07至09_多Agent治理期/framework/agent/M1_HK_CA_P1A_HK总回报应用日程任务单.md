# M1 HK-CA P1A：HK 总回报应用日程任务单

日期：2026-08-09  
状态：主 Agent 最终验收通过（仅来源无关 development 合同；正式HK复权/HK60/M1 Gate仍开放）  
性质：来源无关 development 合同；不是正式 HK 复权、HK60 或 M1 Gate

## 1. 目标与分包理由

P0/P1-PRE 已分别建立 PIT canonical HK action、来源确认实施事实；PRE-B R4 已建立逐 bar retained
availability 与 `VerifiedHkBarBundle`。但直接生成研究价格仍会把下列未决语义混在一个 builder 中：

- RIGHTS 的认购/放弃与资金政策；
- CNY 派息的 PIT FX 来源；
- 现金股息的 gross reinvestment 日与价格；
- 停牌或 no-trade 时 ex-date 到下一可观测 bar 的映射；
- BONUS/SPLIT 的 share multiplier 应用顺序。

本包只建立“fresh verified upstream → supported action schedule”的确定性闭包，不计算 adjusted close，不写
research-price store。P1B 再基于本包冻结的 schedule 实现数值公式与发布 receipt。这样可在不猜 RIGHTS/FX 的
前提下继续工程推进，并让数值层不再重复 P0/PRE/PRE-B verifier。

## 2. 权威输入

必须消费并 fresh 验证：

1. `VerifiedImplementedHkCorporateActionSet`，通过
   `verify_implemented_hk_corporate_action_set`；
2. 对应 `VerifiedHkCorporateActionImplementationProjection`、P0 result 与 P0 projection，作为上项 public
   verifier 的完整上下文；
3. `VerifiedHkBarBundle`，通过 `verify_hk_bar_bundle`；
4. 对应 `HKHistoryPlan`、journal/seed/raw/clean roots、`RawStore` 与 aware UTC `as_of`，作为 bar verifier
   的完整上下文。

新增非序列化 `HkTotalReturnFreshContext`（或等价 frozen context）只负责携带上述 verifier 参数；它不进入
schedule identity/wire，不把 path、store、capability token 或对象 repr 写入产物。

builder/verifier 必须在生成任何 schedule 行前分别 fresh 调用两个 public verifier；hostile verifier 失败时零
输出、固定脱敏异常。禁止只比较 capability dataclass 字段或私有 token。

## 3. 支持政策 v1

冻结 policy identity：`HK_GROSS_TOTAL_RETURN_SCHEDULE_V1`。

### 3.1 支持的窗口内行动

- `DIVIDEND`：仅 `declared_currency == "HKD"`、gross cash、`pay_date` 非空；经济作用日为 `ex_date`；
- `BONUS`：使用 `1 + stock_ratio` 作为 share multiplier，经济作用日为 `ex_date`，`stock_list_date` 仍保留为
  实施/审计字段；
- `SPLIT`：使用 canonical `share_multiplier`，经济作用日为 `ex_date`；
- 同一 symbol、同一 ex-date 多事件按 `(ex_date, event_id)` canonical 排序，P1B 必须按一组同时应用，不能依赖
  source 输入顺序。

“经济作用日”只表示研究总回报的除权日归属，不表示现金/股票已可交易。实施事实 capability 已证明事件最终
实施；`implementation_confirmed_at <= as_of`，故本包不会用未来未确认事件改写较早 artifact。

### 3.2 前置拒绝

窗口内出现下列任一情况，整个 plan fail closed：

- `RIGHTS`；
- DIVIDEND 非 HKD；
- 缺少 action schema 已要求的 gross cash/share ratio/multiplier/date；
- action 与 implementation evidence 的 event/symbol/type/source/revision 不是 exact one-to-one；
- `as_of` 不一致、future availability、bar capability 与 action symbol 集不闭合。

RIGHTS 与 CNY 不允许静默忽略、按零处理或近似成现金股息。未来解锁必须先有独立 investor-policy/FX
capability 与新 policy version。

### 3.3 窗口边界

每个 symbol 的研究窗口是 verified bars 的 `[first_trade_date, last_trade_date]`：

- `ex_date <= first_trade_date`：标记 `BASELINE_PREWINDOW`，绑定 identity 但不进入 P1B 窗内 adjustment；原始
  bar 已处于该行动之后，不能重复应用；
- `first_trade_date < ex_date <= last_trade_date`：标记 `APPLY_IN_WINDOW`；
- `ex_date > last_trade_date`：标记 `OUTSIDE_FUTURE_WINDOW`，绑定 identity 但不应用。

对 `APPLY_IN_WINDOW`，`application_trade_date` 为该 symbol verified bars 中第一个 `>= ex_date` 的
`trade_date`。因此 ex-date 停牌/no-trade 会映射到下一 retained bar，不通过系统日历或日期加一猜测。若窗口内
没有这样的 bar，整个 plan 拒绝。

application bar 对应的 `bar_available_at` 必须 `<= as_of`。不得从 `trade_date`、当前时间或文件 mtime 推断。

## 4. 公共输出

新增 `HkTotalReturnApplicationScheduleSchema`（名称可等价）及 process-local
`VerifiedHkTotalReturnApplicationPlan`。schedule 每个 implemented event 精确一行，至少包含：

- `event_id`、symbol、action_type、source/revision；
- `ex_date`、pay/list date、implementation effective/confirmed/observed time；
- `window_disposition`；
- nullable `application_trade_date` 与对应 availability evidence identity；
- HKD gross cash / stock ratio / share multiplier 的 strict 互斥投影；
- `policy_version`、action/implementation/bar upstream identities；
- row identity；plan 另有 ordered rows content hash 与 plan identity。

输出 frozen、exact type、不可 pickle/reload，DataFrame 属性返回 clone。identity 必须绑定完整 implemented set
content、bar bundle publication/plan/content/availability、`as_of`、policy 和全部行；不得只绑定摘要字符串而不
fresh 验证来源。

建议接口：

```python
build_hk_total_return_application_plan(
    *, context: HkTotalReturnFreshContext
) -> VerifiedHkTotalReturnApplicationPlan

verify_hk_total_return_application_plan(
    plan: VerifiedHkTotalReturnApplicationPlan,
    *, context: HkTotalReturnFreshContext,
) -> None
```

verifier 必须 fresh 重建并 exact compare，不信 plan 缓存。

## 5. 禁止项

- 不计算或发布 `ResearchPrice1dSchema`；不改 `adjustment_method` enum/string；
- 不使用 `ResearchPriceUpdatePipeline`、AKShare/Sina/A股 factor/CNINFO/账户 entitlement；
- 不联网、不扫描 data/legacy、不写正式 HK60/artifacts/journal/clean；
- 不实现 RIGHTS、FX、税、手续费、可交易/可卖日期、账户股数或现金账；
- 不按 `implementation_effective_date` 替代 ex-date，也不据日期推断“已实施”；
- 不新增依赖，不改 connector/storage/backtest/M3/M4。

## 6. 失败语义

稳定公开码使用窄集合：

- `HK_TOTAL_RETURN_INPUT_INVALID`
- `HK_TOTAL_RETURN_ACTION_UNSUPPORTED`
- `HK_TOTAL_RETURN_SCHEDULE_INVALID`
- `HK_TOTAL_RETURN_VERIFY_FAILED`

所有 hostile 下游异常离开 active `except` 后重建；cause/context 均 `None`，traceback/repr 不含 path、raw、
TOKEN、source detail。builder/verifier 为零网络、零文件写、零 store mutation。

## 7. 白名单

- `src/quant/domain/schemas.py`
- `src/quant/domain/__init__.py`
- 新增 `src/quant/data/hk_total_return_schedule.py`
- 必要的 `src/quant/data/__init__.py` 窄导出（若该包当前不做根导出则不改）
- `tests/unit/test_schemas.py`
- 新增 `tests/unit/test_hk_total_return_schedule.py`
- 本任务单、唯一交付报告、唯一独立复验报告、主验报告

既有 P0/PRE/PRE-B 生产与测试只读；发现它们缺少 public fresh 参数或身份时停止，不在本包私读字段补洞。

## 8. 必测反例

至少覆盖：

1. ordinary DataFrame/fabricated capability/subclass/pickle/reload；
2. implemented set 或 bar bundle bytes/content/root/as_of 漂移；hostile两个 public verifier；
3. action/implementation 缺失、额外、重复、跨 symbol/type/source/revision；
4. 窗口内 RIGHTS、CNY dividend、缺 pay/list date、无 application bar；
5. 停牌 ex-date 映射下一 verified bar；application availability future 拒绝；
6. 多 symbol、同日 DIVIDEND+SPLIT canonical order；输入 shuffle identity 不变；
7. prewindow action 不重复应用、future-window action 不应用，但两者任一漂移仍改变/拒绝 identity；
8. wholesale plan 重签、schedule 行增删换序、application date 改写后全量重哈希仍被 fresh upstream rebuild 拒绝；
9. ValueError/RuntimeError hostile marker 的 cause/context/traceback/repr 脱敏；
10. monkeypatch open/socket/RawStore write/clock 证明除 public bar verifier 规定的 fresh reads 外零额外 I/O，且
    本模块自身零网络/写入。

最小正例 fixture：两个 HK symbol、连续至少三日，其中一个 ex-date 无 bar后次日恢复；包含 HKD DIVIDEND、
BONUS、SPLIT，以及 prewindow/future 边界。

## 9. 验证与解锁

Windows 定向 pytest/Ruff/mypy；WSL base 对应验证，DrvFS 不等于 ext4 Gate。实现与独立初验使用不同全新
上下文，初验只写唯一报告并补未公开对抗。

本包主验通过后只解锁 P1B 数值公式任务书。正式发布仍须 02983可信 metadata、licensed 01065 issue/spec、
formal V3M migration、真实 HK action source 与 ext4 等各自 Gate。
