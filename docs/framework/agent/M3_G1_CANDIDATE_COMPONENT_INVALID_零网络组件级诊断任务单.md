# M3 G1：正式 `G1_CANDIDATE_COMPONENT_INVALID` 零网络组件级诊断任务单

## 1. 已冻结事实

- HISTORY 正式闭包：`637 symbols / 3190 requests`；旧 3185 股票 identity 不变；新增五项均为 `510300.SH`。
- 五个正式基金 identity 的 intent/candidate/receipt 已提交；行数 791/972/851、22、2614。
- 基金五响应严格映射成功：2614 bars，`2015-10-09..2026-07-10`，source snapshot
  `a4cd3f23aab767e4f1af090cc3a283df8570ebd59af8a402e4173653fa28582c`。
- 正式 full candidate 失败：
  - WSL `status` ≈1993.4s → `INSPECT:G1_WORKFLOW_QUALITY_FAILED`
  - Windows 只读诊断 ≈1457.7s → `G1_CANDIDATE_COMPONENT_INVALID`
- `build_g1_candidate` / workflow 边界把底层异常折叠为 `G1_CANDIDATE_COMPONENT_INVALID` /
  `G1_WORKFLOW_QUALITY_FAILED`；必须绕过折叠做分层诊断，而不是反复 full build。

## 2. 目标

在**零网络**条件下，复用已验真 raw/receipt/responses，定位导致正式候选失败的**首个具体不变量**：

优先顺序（股票路径；基金 mapper 已排除）：

1. daily / adj_factor 映射与行级合法性
2. 严格复权覆盖（`bar_keys ⊆ factor_keys` 及 lineage/范围）
3. stk_limit / suspend 选择与对齐
4. 公司行动选择与复权对账
5. membership / 最终组合 Schema

输出必须脱敏：稳定错误码、异常类型、模块:行号、受影响证券/日期计数摘要；禁止 token、绝对个人路径、完整 traceback 刷屏。

## 3. 边界与禁止

可写：

- `docs/framework/agent/M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断任务单.md`（本文件，仅协调更新状态）
- `docs/framework/agent/M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md`
- `docs/framework/agent/20260722_Codex至Cursor后续整体交接_协调Agent进度与交付报告.md`
- 可选临时诊断脚本仅允许写入 `artifacts/` 下新建子目录，且不得提交凭据；诊断结束后可保留脚本作证据

只读：全部 `src/`、正式 `data/raw` / `data/run_state` / receipt、配置、测试。

禁止：

- 任何 Tushare/BaoStock/AKShare 网络请求
- 重复五个 510300 正式 API identity
- 修改正式 raw / journal / receipt / intent
- 进入 REFERENCE / PREPARE / PUBLISH
- 降低原子发布合同或把 Windows 绿测写成 Linux Gate
- 静默填充缺失因子/价格/停牌

## 4. 方法（冻结）

1. 用现有正式 config + layout 装载 INDEX/HISTORY 已提交 responses（与 workflow inspect 同源路径）。
2. 不调用折叠后的公开边界作为唯一证据；对 `_build_candidate_body` 或等价分层步骤捕获底层异常（保留 `__cause__`/`__context__` 仅用于本地定位，报告只写稳定摘要）。
3. 逐层断言：map daily → map adj_factor → apply_adjustment_factors_strict → limits/suspend → corporate actions → assemble/schema。
4. 一旦命中首个失败不变量即停止扩大范围；写清现象—疑似根因类别（实现/正式数据/SSOT）—最小复现线索—建议下一动作。
5. 长命令使用持久日志；已知 full candidate 约 24–34 分钟；禁止分钟级空轮询。

## 5. 验收（诊断包本身）

诊断包“完成”仅当记录中写明：

- 首个失败点（模块/函数/稳定码或异常类型）
- 是否已排除 510300 基金 mapper
- 是否零网络、零正式写入
- 分流建议（实现返工 / 数据裁定 / 先修 SSOT）

诊断完成 ≠ Gate 通过；不得更新路线图为完成。
