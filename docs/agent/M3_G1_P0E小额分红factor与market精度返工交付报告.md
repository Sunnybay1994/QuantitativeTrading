# M3 G1 P0E：小额分红 factor / market 精度返工交付报告

状态：**外部实现已交付（Windows 定向自测）；不得据此宣布 G1 / Codex / Linux Gate 通过**

角色：外部实现 Agent（全新会话，非独立初验）  
任务书：[`M3_G1_P0E小额分红factor与market精度返工任务单.md`](M3_G1_P0E小额分红factor与market精度返工任务单.md)  
首败证据：[`20260727_M3_G1_P0D后正式首败_000627小额分红精度.md`](20260727_M3_G1_P0D后正式首败_000627小额分红精度.md)

## 1. 变更摘要

在完整实施分红事件路径上，将原先无条件的 `actual <= 1` / `market <= 1` 拒绝，改为冻结算法：

```text
supported_ratio(x) := x > 1.0 OR abs(x - 1.0) <= rtol
```

- event 分支：`actual` /（有 daily 时）`market` 必须落在支持域，且
  `abs(actual/market-1)<=rtol`；declared 仍要求 `>1`，分母非法等继续 fail closed。
- 保留 `MATCHED_EVENT_DECLARED_FORMULA` /
  `MATCHED_EVENT_MARKET_REFERENCE` /
  `MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE`，以及全部
  event ids / cash / stock；不得回退为 `NO_EVENT_STABLE_FACTOR`。
- Schema 行条件与 verifier 公式校验同步改为 `supported_ratio` 语义。
- `G1_CORPORATE_ACTION_RECONCILIATION_VERSION`：
  `tushare_factor_daily_preclose_v3` → `tushare_factor_daily_preclose_v4`。
  candidate / planning / reference 经 SSOT 常量传播；未提升 mapper / manifest
  等无关结构版本。
- 旧宽松无事件 jump 合同文档此前已废止并指向 P0E；本轮未改其正文噪声。

## 2. 白名单改动

| 路径 | 说明 |
|---|---|
| `src/quant/data/m3_execution_facts.py` | `_supported_ratio`；event 分支与 verifier；版本 v4 |
| `src/quant/domain/schemas.py` | matched 状态 `actual`/`market` 支持域 |
| `tests/unit/test_m3_execution_facts.py` | 任务书矩阵 1–8 + 额外 FULL_DAY 边界；版本钉 |
| `tests/unit/test_m3_g1_candidate.py` | v4 钉；旧 v3 build_spec 拒绝 |
| `tests/unit/test_m3_g1_planning.py` | 静态计划传播 v4；旧 v3 拒绝 |
| `tests/unit/test_m3_reference.py` | v4 传播；`_restrict_bar_symbols` 同步裁剪 factor/recon 以闭合 P0D audit |
| 本报告 | 唯一交付报告 |

未改白名单外生产代码；未硬编码证券/日期/金额；未处理 000661 配股或 600733 重复实施行。

## 3. 测试矩阵映射

1. cash=`0.005` / prev=`2.91` / actual=`market=1.0` → `MATCHED_EVENT_MARKET_REFERENCE`，ids/cash 保留  
2. actual=`0.9995`、market=`1.0`、rtol=`0.001` → 允许（对称容差）  
3. actual=`market=0.998` → 拒绝（远离 1 的反向 ratio）  
4. actual=`1.0`、market 明显 `>1` 且超差 → 拒绝  
5. actual=`1.0`、无 daily、非 FULL_DAY → 拒绝  
6. FULL_DAY + 无 daily + declared error `>rtol` → 拒绝  
7. no-event `actual=1.0` 稳定；no-event 大 jump 拒绝  
8. 伪装 NO_EVENT / 清空 ids / 改 cash → Schema 或 verifier 拒绝  
9. 版本常量与 planning/candidate/reference 为 v4；旧 v3 build_spec 非法  
额外：FULL_DAY + 极小 cash 使 declared 落在 rtol 内 + actual=`1.0` →
`MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE`

## 4. 自测命令与结果

解释器：`D:\Miniforge3\python.exe`（Windows 原生反馈环）

```text
pytest tests/unit/test_m3_execution_facts.py \
       tests/unit/test_m3_g1_candidate.py \
       tests/unit/test_m3_g1_planning.py \
       tests/unit/test_m3_reference.py -q --tb=line
ruff check <白名单生产与测试文件>
mypy src/quant/data/m3_execution_facts.py src/quant/domain/schemas.py
git diff --check -- <白名单文件>
```

（具体退出码见提交后压缩摘要；本报告不宣称 Gate/Codex 通过。）

本次自测结果（Windows `D:\Miniforge3\python.exe`）：

| 检查 | 退出码 | 摘要 |
|---|---|---|
| pytest（上列四文件） | 0 | 255 passed, 5 skipped |
| `git diff --check`（白名单） | 0 | 通过 |
| ruff check（白名单） | 0 | All checks passed |
| mypy（两生产文件） | 0 | no issues found |

## 5. 非目标与残留风险

- 未跑正式 `status` / reference / prepare / publish / G2A；未宣称 Linux Gate。
- 000661 配股、600733 重复实施行仍不在本轮范围。
- 独立初验须另加实现者未使用的边界反例；主 Agent 再跑隐藏反例与零网络 status。
