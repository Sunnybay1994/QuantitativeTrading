# M3 G1 P0F：CNINFO 配股全链主 Agent 最终验收报告

状态：**P0F 代码与零网络合同验收通过；正式 CNINFO HISTORY 尚待执行，不等于 G1 Gate**

日期：2026-07-28（Asia/Shanghai）

## 1. 验收对象

- P0F 冻结合同：`d1f944b`
- P0F 实现：`db3b944`
- 首轮独立初验：`48ce457`，结论 FAIL
- R1 冻结任务：`022d3ef`
- R1 实现：`f943e41`
- R1 独立复验：`43c45eb`，结论 PASS

## 2. 返工闭环

首轮初验确认：

1. rights `event_id` / `candidate_id` 未绑定 actual/pre/post 股本；
2. CNINFO receipt projection 未强制官方 57 列。

R1 完成：

- ledger/evidence 持久化 `rights_actual_shares`、`rights_pre_shares`、`rights_post_shares`；
- rights event/candidate ID 升级 v2 并绑定三项股本；
- selection `capital_v4`、mapper v5、planning schema v3、manifest v5、table schema v3；
- `G1ReceiptProjectionV1` 对 `cninfo/stock_allotment` 精确强制 SSOT 57 列；
- 旧版本混搭 fail closed；dividend、P0E、no-event 与同日顺序语义保持。

另一全新外部高模型会话独立重放股本碰撞、三项篡改、重算 digest、57 列少/多/乱序、manifest 降级与版本传播，结论 PASS。

## 3. 主 Agent 验证

### Windows Miniforge

- connector、Schema、P0E、rights market/declared、no-event、同日 dividend+rights、R1 股本碰撞、candidate 版本、manifest v5/projection、planning：
  - `60 passed, 1 skipped`
  - 退出码 0
- Ruff：退出码 0
- mypy（6 个改动生产文件）：退出码 0
- `git diff --check 022d3ef f943e41`：退出码 0

### WSL Miniforge base

工作树 HEAD：`43c45eb`

- Schema 全文件 + R1 股本身份 + dividend null + CNINFO projection + planning version drift：
  - `31 passed`
  - 退出码 0

Windows 与 WSL 的 Pandera/Polars deprecation warnings 为既有依赖告警，不影响本轮退出码或合同结论。

## 4. 主验结论

P0F 的代码、Schema、身份、版本、零网络 status/HISTORY 前置合同通过主 Agent 验收。实现与独立复验职责分离闭环完整；首轮 FAIL 未被绕过。

## 5. 明确未完成

- 正式 637 证券、13 个确定批次的 CNINFO HISTORY 网络抓取；
- 基于新 source tree / candidate key 的正式 candidate、audit、reference、prepare、publish；
- Windows VerifiedG1Release；
- WSL/Linux publish Gate、Linux flock 与 ext4 不可变发布终验；
- G1 Gate 及后续 G2-G9。

下一步只能先运行正式 CLI 零网络 `status`，确认新身份与缺失 receipt；再执行受限 CNINFO HISTORY。不得复用 P0F 前的 candidate/reference/prepare/publish 产物。

