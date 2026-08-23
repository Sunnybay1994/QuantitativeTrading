# M1 HK-HISTORY-R1 第三批稳定缺行事故与重试裁定

状态：2026-07-22 取证完成；禁止重试与 finalize，等待外部实现/独立初验闭环

## 1. 现象

HK60 strict plan `ffbf8f345626b9db834a7b4c31fa8c31a6b60ffe5053ab4953a27bb2c4c50a03`
在第 3/8 批写入 intent 和 attempt 后以 `HK_HISTORY_RAW_INVALID` 停止。journal 当前为 2 个 receipt、3 个
intent、3 个 attempt、无 finalize，后台 runner 已退出。

失败 request 为 `eb6be66198542a5209cfa7124509bbf82cb4761f8120a4f0ac8ea8c2fc401ece`：冻结计划预期
4,691 个 `(symbol, trade_date)`，不可变 raw 实得 4,690 个，80 个证券均出现且无重复。唯一差异是
`01065.HK` 缺少 `2026-05-05`。

## 2. 根因与真实复现

现行 plan 把证券上市生命周期内的每个 HK 市场开市日都当成强制 bar 键；Tushare `hk_daily` 对没有行情的
证券日不返回占位行。因此“合法无行情/停牌”与“接口漏数”被合同合并成同一个 `RAW_INVALID`。

2026-07-22 在距离上次请求数日后，用一次最小 `hk_daily` 请求复核 `01065.HK`、`2026-05-05`，仍返回
0 行且保留完整列集合。raw-first 证据位于
`data/raw/tushare/hk_daily_targeted_probe/request=e6d5264c5f75fb315c3a1d93ef1d36b13fd65bbbe585b2fd6db8bfbe5d7779b1/`。
相邻的 5 月 4 日和 5 月 6 日均有正常行情。

## 3. 应遵循规则

- raw 不覆盖、不删除，不用合成 OHLC 填补无行情日。
- 不把一次 targeted 0 行直接解释为停牌；修复必须引入可审计的无行情事实来源，或重新冻结“可用观察”而非
  “市场 session 全覆盖”的 Gate 语义。
- 既有 attempt 属于不确定/失败证据；任务书未关闭前不得带 `confirm_uncertain_retry` 重发第 3 批。
- 修复必须从现有 raw 重处理并证明零网络；只有合同明确要求新的事实请求时才允许最小 API 调用。
- HK 修复不抢占用户指定的 A 股全流程优先级。

## 4. 新任务的最小反例与通过条件

至少覆盖：

1. 市场开市但单证券有权威无行情事实：允许该键从 expected bar 集合排除，仍保留审计原因；
2. 没有无行情事实而 raw 缺键：继续 `HK_HISTORY_RAW_INVALID`；
3. targeted probe 为 0 行但缺少权威状态：不得单凭空响应自动豁免；
4. 已有 COMPLETE raw + 无 receipt：修复后应零网络生成 receipt；
5. 任一额外键、重复键、非目标证券或 raw 校验漂移仍 fail closed；
6. 重新生成 plan 必须有新 identity，旧 plan/journal 永久只读；不得在旧 request 下改写预期集合。

外部实现、全新外部独立初验和主 Agent 终验全部通过后，才可建立新 plan 并继续后续批次。当前不关闭 HK60
或 M1 Gate。
