# M3 G1 P0E：小额分红 factor / market 精度主 Agent 最终验收报告

状态：**P0E 通过；正式 G1 仍失败，首败已推进到独立的 000661 配股类事件**

日期：2026-07-28（Asia/Shanghai）
分支：`cursor/g1-p0-rework-20260726`

## 1. 验收对象

- 冻结合同：[`M3_G1_P0E小额分红factor与market精度返工任务单.md`](M3_G1_P0E小额分红factor与market精度返工任务单.md)
- 实现提交：`6d887de`（`Fix G1 small-dividend ratio precision`）
- 外部实现报告：[`M3_G1_P0E小额分红factor与market精度返工交付报告.md`](M3_G1_P0E小额分红factor与market精度返工交付报告.md)
- 独立初验提交：`fab540b`；后续证据整理提交：`b590074`
- 独立初验报告：[`M3_G1_P0E小额分红factor与market精度独立初验报告.md`](M3_G1_P0E小额分红factor与market精度独立初验报告.md)
- P0E 前正式首败：[`20260727_M3_G1_P0D后正式首败_000627小额分红精度.md`](20260727_M3_G1_P0D后正式首败_000627小额分红精度.md)
- P0E 后正式首败：[`20260727_P0E后正式首败_000661无事件大跳.md`](20260727_P0E后正式首败_000661无事件大跳.md)

## 2. 主验结论

P0E 冻结合同通过：

1. event 分支使用
   `x > 1.0 OR abs(x - 1.0) <= rtol` 支持 actual/market 的报价精度带；
2. actual 与 market 仍须在容差内相互匹配；
3. 事件身份、cash、stock 和既有 MATCHED 状态保留；
4. 缺 daily 仍只允许 FULL_DAY 且 declared 公式在容差内；
5. no-event 大跳、远低于 1 的反向 ratio、非法分母和声明公式仍 fail closed；
6. reconciliation version 精确升级为
   `tushare_factor_daily_preclose_v4`，candidate/planning/reference 传播一致，
   旧 v3 被拒绝，未提升无关结构版本。

完整抹成自洽 NO_EVENT 行是 reconciliation 单表验证层的已知边界；正式
`verify_g1_candidate(inputs, candidate)` 会从冻结输入重建公司行动选择、ledger 和
reconciliation 并逐帧比对，因此 P0E 合同要求的“Schema/verifier/candidate audit
至少一层拒绝”成立。生成路径也不会把 event 分支回退为 no-event。

## 3. 验证证据

环境：Windows 原生 `D:\Miniforge3\python.exe`，作为双平台模块的定向反馈环。

| 检查 | 结果 |
|---|---|
| P0E 定向用例 | `9 passed, 61 deselected` |
| candidate/planning/reference 版本传播最小集 | `4 passed` |
| 独立形状探针 | `4/4 passed` |
| Ruff（两生产文件、四测试文件） | 退出码 0 |
| mypy（两生产文件） | 退出码 0 |
| `5c790b7..6d887de` 六代码/测试文件 diff check | 退出码 0 |
| 外部实现四文件回归 | `255 passed, 5 skipped` |
| 独立初验四文件回归 | `255 passed, 5 skipped` |

主验特别复核：

- 小额现金事件且 actual=market=1.0 保持 MATCHED_EVENT；
- actual=market=0.997 即使相互匹配也拒绝；
- no-event actual=1.002 继续拒绝；
- v4 传播和旧 v3 拒绝；
- candidate 的 inputs-rebuild 验证可识别完整表级事件抹除。

## 4. 正式状态

P0E 后正式零网络 `status`：

```text
outcome=FAILED
error_operation=INSPECT
error_code=G1_WORKFLOW_QUALITY_FAILED
```

修正后的首败诊断为：

```text
symbol=000661.SZ
previous_factor_date=2016-04-26
effective_date=2016-04-27
branch=no_event
actual_factor_ratio=1.1455399061032865
code=G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
```

这证明 `000627` 小额分红精度阻塞已解除；新首败是 P0E 明确排除的配股/增发类资本事件，
不能通过恢复宽松 NO_EVENT 或扩大 rtol 处理。

## 5. 边界与剩余风险

- 本报告只关闭 P0E，不宣布 G1、Windows publish、VerifiedG1Release 或 Linux Gate 通过。
- 未进入 REFERENCE / PREPARE / PUBLISH；旧 release `3c9bda84…` 仍不得作 G2A 输入。
- 下一轮必须先冻结配股/增发事件的权威来源、身份、PIT、公式、缺失语义和版本迁移，再进入新的
  “外部实现 → 外部独立初验 → 主 Agent 终验”闭环。
- Windows 验收不替代 WSL Miniforge base 的平台特有 Gate。
