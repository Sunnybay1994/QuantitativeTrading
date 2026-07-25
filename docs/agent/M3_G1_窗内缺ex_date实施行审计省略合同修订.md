# M3 G1：窗内缺 `ex_date` 实施行审计省略合同修订（ supersede 正式数据阻塞）

- 修订时间：2026-07-23（Asia/Shanghai）
- 授权：用户要求自行拉取/解决 full candidate 前阻塞；Windows 原生优先
- 探针：`artifacts/g1_002131_dividend_probe_20260723/probe_summary.json`
  - 正式 raw 与 live 各 1 次对照：`vendor_ex_date_fixed=false`（恰好 1 次 dividend 网络请求）
  - 同 identity 正式 receipt 已闭合，**不能**覆盖写入更正版

## 1. 现象—根因—新合同—通过条件

| 项 | 内容 |
|---|---|
| 现象 | `002131.SZ` 实施行窗内 `ex_date=null`，供应商 live 仍缺 |
| 根因 | 正式数据残缺 + 无 supersede 通道；禁止用 list/record 发明除权日 |
| **新合同** | 凡 `div_proc=实施` 且 `ex_date` 为 null：**一律省略**（不入 ledger、不发明日期）。raw 保留为供应商事实。非法非空 `ex_date` 字符串仍 fail closed |
| 取代 | [`M3_G1_正式数据缺陷裁定_002131缺ex_date窗内.md`](M3_G1_正式数据缺陷裁定_002131缺ex_date窗内.md) 中“窗内必须 fail closed 直至新 raw”的解除条件；窗外 skip 合同并入本统一省略规则 |
| 通过条件 | 单元：窗内/窗外/跨越 null ex_date 均省略且同响应有效实施仍可选；正式零网络 select `002131.SZ` 不再因该行失败；Windows 分层诊断越过 `corporate_action_selection` |

## 3. 追加：零经济效果实施行

正式样本 `600600.SH` 存在窗内 `实施` 且 `cash_div_tax=0`/`stk_div=0`（或规范化后双零）。
此类行无法入账，**一律省略**，不得发明金额。与 null `ex_date` 省略同属“不发明、不阻塞整证券选择”。
