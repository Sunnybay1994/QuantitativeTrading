# M3 G1 P0D：首 bar 前 factor 发布作用域返工任务单

- 冻结日期：2026-07-27
- 主裁定：
  [`20260727_M3_G1_P0返工Codex主验通过但正式G1仍阻塞.md`](20260727_M3_G1_P0返工Codex主验通过但正式G1仍阻塞.md)
- 外部实现模型：全新 `cursor-grok-4.5-high`
- 外部独立初验：另一全新 `cursor-grok-4.5-high`
- 环境：Windows 原生 Miniforge 可作反馈环；Linux/Gate 仍以 WSL Miniforge
  `base` 为准

## 1. 现象—根因—规则—最小复现—通过条件

| 项 | 冻结内容 |
|---|---|
| 现象 | P0 fail-closed 恢复后，正式 `status` 首败 `000553.SZ@2016-06-15`：factor jump 约 19.4bp，第一根 candidate bar 是 `2016-10-17` |
| 根因 | `apply_adjustment_factors_strict` 只消费 bar 日 factor，但 candidate 发布并 reconciliation 全量消费首 bar 前 factor；对应 event 因无 prior candidate bar不能构造证明，形成“event matching 省略、factor transition 仍强制门禁”的作用域矛盾 |
| 应遵循规则 | 发布级 factor 表、factor match、adjusted bars 与 reconciliation 必须审计同一候选可消费作用域；raw receipt 保留全窗，不改 raw |
| 最小复现 | 单 symbol：factor `D0,D1,D2`，bars 仅 `D2...`，`D0→D1` 有超 rtol jump；旧路径失败，新路径必须把 `D0,D1` 排除在发布级 factor/reconciliation 之外 |
| 通过条件 | 见 §5；通过只表示本返工闭合，不表示 G1/Gate 通过 |

## 2. 冻结设计

### 2.1 发布级 factor scope

对每个 candidate symbol：

1. 从已验证的 `bars_no_factor` 取得 `first_bar=min(trade_date)` 和
   `last_bar=max(trade_date)`；
2. 从完整 raw-mapped `adjustment_factors` 投影发布级
   `scoped_adjustment_factors`，只保留
   `first_bar <= effective_date <= last_bar`；
3. `apply_adjustment_factors_strict`、candidate 的 `adjustment_factor` 表、
   candidate audit 重建和 `reconcile_g1_corporate_actions` 全部消费同一个
   `scoped_adjustment_factors`；
4. raw response、receipt、request scope 仍保留完整 history，不删除或重写
   raw/journal；
5. 每个 bar 键必须精确存在 factor，bar/factor 数值与 lineage 规则不弱化；
   首 bar 后停牌日 factor 仍在 scope 内，原公司行动 fail-closed 规则保持。

允许发布级 factor 包含首 bar 后、末 bar 前的停牌 session；本轮不是把 factor
简单裁成“仅 bar 键”。本轮只消除严格位于首 bar 前或末 bar 后、对 candidate
bars 无贡献的边界 observations。

### 2.2 公司行动边界

- ledger 与 selection evidence 继续保存 history 窗内合法经济事件。
- `ex_date` 位于某 symbol scoped factor 范围之外时，不进入 reconciliation
  matching，也不得因此抛 `G1_CORPORATE_ACTION_FACTOR_INVALID`。
- `ex_date` 位于 scoped factor 范围内时，原 P0 合同不变：
  - 无事件 jump 超 rtol → `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`；
  - 有事件缺前收、非法分母、错误 ratio、无可用证明 → fail-closed；
  - 禁止回退成 `NO_EVENT_STABLE_FACTOR`。
- reconciliation 行数精确等于
  `sum(max(scoped_factor_rows_per_symbol - 1, 0))`。

### 2.3 身份与方法版本

该改动改变发布 `adjustment_factor` 内容和 reconciliation 作用域：

- planning 的 `_MAPPER_VERSION` 从 `m3-g1-tushare-mapper-v2` 升为
  `m3-g1-tushare-mapper-v3`；
- `G1_CORPORATE_ACTION_RECONCILIATION_VERSION` 从
  `tushare_factor_daily_preclose_v2` 升为
  `tushare_factor_daily_preclose_v3`；
- 新值必须贯穿 `G1BuildSpec`、planning/candidate/release manifest、严格 reader
  与相关测试；
- 不得为了复用旧 key 保留 v2；旧 candidate/reference/release 均不可作为新
  identity 的终态证据。

若现有 manifest strict-reader 的历史兼容合同要求保留 v1/v2 读取，按既有版本化
reader 方式兼容；不得让旧 manifest 被当前严格 reader 误认成 v3。

## 3. 文件白名单

外部实现可写：

- `src/quant/data/m3_g1_candidate.py`
- `src/quant/data/m3_execution_facts.py`
- `src/quant/research/m3/g1_planning.py`
- 若严格 manifest 贯穿确有必要：`src/quant/data/m3_release.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_execution_facts.py`
- 若 manifest 贯穿确有必要：`tests/unit/test_m3_g1_release.py`
- 仅为 mapper v3 既有断言/fixture 的必要字面量同步：
  `tests/unit/test_m3_g1_planning.py`、`tests/unit/test_m3_reference.py`
- 唯一实现报告：
  `docs/agent/M3_G1_P0D首bar前factor发布作用域返工交付报告.md`

外部独立初验唯一可写：

- `docs/agent/M3_G1_P0D首bar前factor发布作用域独立初验报告.md`

其余生产代码、测试、正式 data/raw/journal/receipt、路线图只读。实现与初验
必须是不同全新会话；独立初验不得修改生产代码或实现者测试。

## 4. 禁止项

- 放宽 `factor_ratio_rtol`；
- 恢复任意 factor jump → `NO_EVENT_STABLE_FACTOR`；
- 发明窗外 prior close/factor，或以前填价格构造证明；
- 新增配股/增发事件源、修改经济事件身份、修正 `600733` 特例；
- 硬编码 symbol/date 白名单；
- 删除或覆盖 raw、journal、receipt、旧 release；
- 重复五个 `510300.SH` 正式 identity 请求；
- 启动 REFERENCE/PREPARE/PUBLISH/G2A；
- reset/checkout、批量换行、输出 token；
- 用 Windows 绿测宣称 Linux Gate。

## 5. 实现测试矩阵

至少新增：

1. **000553 结构反例**：首 bar 前 factor jump + 同日 ledger event，无 prior bar；
   candidate 发布级 scope 排除该 transition，构建不因它失败。
2. **P0 防回退**：首 bar 后无 event 大 jump 仍
   `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。
3. 首 bar 后 FULL_DAY 停牌 event + prior bar，原 declared/no-market-reference
   合同仍通过；PARTIAL/无证明仍失败。
4. 首 bar 前 ledger event 可保留，但不进入 reconciliation；篡改为 scope 内后
   必须重新受严格门禁。
5. bar 日缺 factor、factor 数值/lineage 漂移仍失败。
6. scoped factor 每 symbol 排序、边界包含、行数公式和 digest 重建稳定；
   输入行乱序不改变结果。
7. candidate audit 从冻结 inputs 重建 scope；攻击者只恢复被裁掉的 factor、同步
   table digest/primary key 后仍审计失败。
8. mapper v3 与 reconciliation v3 贯穿 build spec/manifest；v2 伪装 v3、
   current manifest 混入旧版本均失败。
9. 既有 `eligible_keys.head(1)` 对抗与 no-event `1.5` jump 对抗继续通过。

## 6. 自验命令

按最小到整合顺序：

```text
D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_m3_execution_facts.py \
  tests/unit/test_m3_g1_candidate.py -q --tb=line

# 若修改 release/manifest，再定向运行版本与 publish 身份相关测试，
# 不机械运行 Windows 宿主不支持的 mkfifo/symlink 用例。

D:\Miniforge3\python.exe -m ruff check <白名单代码与测试>
D:\Miniforge3\python.exe -m mypy <白名单生产模块>
git diff --check -- <白名单>
```

实现报告只返回压缩证据：改动文件、命令/退出码、失败摘要、未验证项；不得粘贴
长日志，不得宣布 G1/Codex/Linux Gate 通过。

## 7. 独立初验要求

独立初验逐项映射 §2/§5，并新增实现者未使用的反例：

- 构造首 bar 前多个 factor jump、首 bar 后一个 jump，证明只排除边界外；
- 构造 ledger 在 scope 边界前一天、首日、末日、后一天，证明包含边界精确；
- 构造攻击者把完整 raw factor 表重新塞回 candidate 并重绑自包含 hashes，证明
  audit 仍从 inputs 重建并拒绝；
- 核对没有 symbol/date 特例、没有 rtol 放宽、没有 old v2 冒充 current。

初验报告必须明确 PASS/FAIL。FAIL 时按“现象—根因—规则—最小复现—新增测试—
通过条件”返回主 Agent，不得自行修生产代码。

## 8. 主 Agent 后续

实现与独立初验均 PASS 后：

1. Codex 复核 diff、对抗测试、版本贯穿；
2. 运行零网络正式 `status`；
3. 若出现新的 fail-closed 首败，保存首败证据并另立合同，不顺手放宽；
4. 只有 candidate/audit 通过才按新 identity 判断是否需要重新 REFERENCE；
5. 新 PREPARE/PUBLISH 后从磁盘运行 `verify_g1_release`；
6. 新 `VerifiedG1Release` 通过后再启动 G2A。
